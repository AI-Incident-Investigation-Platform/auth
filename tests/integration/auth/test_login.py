import asyncio
import dataclasses
import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import cfg
from src.core.db.models import User
from src.core.security.dto import OtpChallenge
from src.core.security.otp_challenges import OtpChallenges
from src.main import container
from tests.support.auth import (
    Account,
    Mailbox,
    client_with_cookies,
    error_code,
    sign_in,
    start_login,
    verify,
)


async def shift_challenge(
    challenge_id: str,
    code_expires_at: datetime | None = None,
    resend_available_at: datetime | None = None,
) -> None:
    challenges = await container.get(OtpChallenges)
    challenge = await challenges.get(challenge_id)
    assert challenge is not None
    shifted = dataclasses.replace(
        challenge,
        code_expires_at=code_expires_at or challenge.code_expires_at,
        resend_available_at=resend_available_at or challenge.resend_available_at,
    )
    assert await challenges.replace(shifted)


@pytest.mark.case(id="AUTH-LOGIN-001")
async def test_code_request_is_identical_for_known_and_new_email(
    client: AsyncClient, account: Account, mailbox: Mailbox
) -> None:
    client.cookies.clear()

    known = await start_login(client, account.email.upper())
    known_letter = await mailbox.next_letter()
    new = await start_login(client, "newcomer@example.com")
    new_letter = await mailbox.next_letter()

    assert known.status_code == new.status_code == 202
    assert known.json().keys() == new.json().keys()
    assert known.json()["masked_email"] == "u***@example.com"
    assert known.json()["delivery_status"] == "queued"
    assert known.json()["expires_in"] == cfg.auth.otp_code_ttl_seconds
    assert known.json()["resend_after"] == cfg.auth.otp_resend_interval_seconds
    assert "set-cookie" not in known.headers and "set-cookie" not in new.headers
    assert known_letter.body["template"] == new_letter.body["template"] == "auth.login_code"
    assert known_letter.body["to"] == account.email
    assert new_letter.body["to"] == "newcomer@example.com"
    assert len(known_letter.code) == 6 and known_letter.code.isdigit()
    assert known_letter.message.message_id == known_letter.body["message_id"]
    assert known_letter.message.expiration is not None


@pytest.mark.case(id="AUTH-LOGIN-002")
async def test_code_for_new_email_creates_account_once(
    app: FastAPI, client: AsyncClient, db: AsyncSession, mailbox: Mailbox
) -> None:
    first = await sign_in(client, mailbox, "Newcomer@Example.com")
    async with client_with_cookies(app, {}) as other_device:
        second = await sign_in(other_device, mailbox, "newcomer@example.com")

    assert first.status_code == second.status_code == 200
    assert first.json()["account_created"] is True
    assert second.json()["account_created"] is False
    assert first.json()["user"]["email"] == "newcomer@example.com"
    assert first.json()["user"]["id"] == second.json()["user"]["id"]
    assert {"access_token", "refresh_token"} <= set(client.cookies.keys())
    assert (await client.get("/api/v1/auth/me")).json()["email"] == "newcomer@example.com"
    assert await db.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.case(id="AUTH-LOGIN-003")
async def test_wrong_code_counts_attempts_and_exhaustion_kills_challenge(
    client: AsyncClient, mailbox: Mailbox
) -> None:
    started = await start_login(client, "user@example.com")
    challenge_id = started.json()["challenge_id"]
    code = (await mailbox.next_letter()).code
    wrong = "000000" if code != "000000" else "111111"

    left = []
    for _ in range(cfg.auth.otp_max_attempts):
        response = await verify(client, challenge_id, wrong)
        assert response.status_code == 401
        assert error_code(response) == "auth.otp_invalid"
        left.append(response.json()["error"]["details"]["attempts_left"])
    after = await verify(client, challenge_id, code)

    assert left == list(range(cfg.auth.otp_max_attempts - 1, -1, -1))
    assert after.status_code == 410
    assert error_code(after) == "auth.challenge_invalid"
    assert "access_token" not in client.cookies


@pytest.mark.case(id="AUTH-LOGIN-004")
async def test_code_works_once_and_only_until_it_expires(
    app: FastAPI, client: AsyncClient, mailbox: Mailbox
) -> None:
    started = await start_login(client, "user@example.com")
    challenge_id = started.json()["challenge_id"]
    code = (await mailbox.next_letter()).code
    assert (await verify(client, challenge_id, code)).status_code == 200
    async with client_with_cookies(app, {}) as replay:
        repeated = await verify(replay, challenge_id, code)

    expiring = await start_login(client, "user@example.com")
    expiring_code = (await mailbox.next_letter()).code
    await shift_challenge(
        expiring.json()["challenge_id"], code_expires_at=datetime.now(UTC) - timedelta(seconds=1)
    )
    expired = await verify(client, expiring.json()["challenge_id"], expiring_code)

    assert repeated.status_code == 410
    assert error_code(repeated) == "auth.challenge_invalid"
    assert expired.status_code == 410
    assert error_code(expired) == "auth.otp_expired"


@pytest.mark.case(id="AUTH-LOGIN-005")
async def test_resend_respects_interval_and_replaces_code(
    client: AsyncClient, mailbox: Mailbox
) -> None:
    started = await start_login(client, "user@example.com")
    challenge_id = started.json()["challenge_id"]
    old_code = (await mailbox.next_letter()).code

    too_early = await client.post("/api/v1/auth/otp/resend", json={"challenge_id": challenge_id})
    await shift_challenge(challenge_id, resend_available_at=datetime.now(UTC))
    resent = await client.post("/api/v1/auth/otp/resend", json={"challenge_id": challenge_id})
    new_code = (await mailbox.next_letter()).code
    old = await verify(client, challenge_id, old_code) if old_code != new_code else None
    fresh = await verify(client, challenge_id, new_code)

    assert too_early.status_code == 429
    assert error_code(too_early) == "auth.otp_rate_limited"
    assert 0 < int(too_early.headers["retry-after"]) <= cfg.auth.otp_resend_interval_seconds
    assert resent.status_code == 202
    assert resent.json()["challenge_id"] == challenge_id
    assert old is None or old.status_code == 401
    assert fresh.status_code == 200


@pytest.mark.case(id="AUTH-LOGIN-006")
async def test_letters_per_email_are_limited(
    client: AsyncClient, mailbox: Mailbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cfg.auth, "otp_sends_per_email_per_hour", 2)

    accepted = [await start_login(client, "user@example.com") for _ in range(2)]
    limited = await start_login(client, "USER@example.com")
    other = await start_login(client, "other@example.com")

    assert [response.status_code for response in accepted] == [202, 202]
    assert limited.status_code == 429
    assert error_code(limited) == "auth.otp_rate_limited"
    assert 0 < int(limited.headers["retry-after"]) <= 3600
    assert other.status_code == 202


@pytest.mark.case(id="AUTH-LOGIN-007")
async def test_unroutable_letter_is_503_and_leaves_no_challenge(
    client: AsyncClient, mailbox: Mailbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[str] = []
    original_save = OtpChallenges.save

    async def remember_save(self: OtpChallenges, challenge: OtpChallenge) -> None:
        saved.append(challenge.challenge_id)
        await original_save(self, challenge)

    monkeypatch.setattr(OtpChallenges, "save", remember_save)
    await mailbox.detach()

    response = await start_login(client, "user@example.com")

    assert response.status_code == 503
    assert error_code(response) == "email.unavailable"
    assert len(saved) == 1
    assert await (await container.get(OtpChallenges)).get(saved[0]) is None


@pytest.mark.case(id="AUTH-LOGIN-008")
async def test_parallel_verification_of_new_email_creates_one_account(
    app: FastAPI, db: AsyncSession, mailbox: Mailbox
) -> None:
    async with (
        client_with_cookies(app, {}) as first,
        client_with_cookies(app, {}) as second,
    ):
        first_started = await start_login(first, "newcomer@example.com")
        first_code = (await mailbox.next_letter()).code
        second_started = await start_login(second, "newcomer@example.com")
        second_code = (await mailbox.next_letter()).code

        responses = await asyncio.gather(
            verify(first, first_started.json()["challenge_id"], first_code),
            verify(second, second_started.json()["challenge_id"], second_code),
        )

    assert [response.status_code for response in responses] == [200, 200]
    assert sorted(response.json()["account_created"] for response in responses) == [False, True]
    assert await db.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.case(id="AUTH-LOGIN-009")
async def test_code_and_challenge_never_reach_logs(
    client: AsyncClient, mailbox: Mailbox, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="src")

    started = await start_login(client, "user@example.com")
    challenge_id = started.json()["challenge_id"]
    code = (await mailbox.next_letter()).code
    await verify(client, challenge_id, "000000" if code != "000000" else "111111")
    signed_in = await verify(client, challenge_id, code)

    assert signed_in.status_code == 200
    logged = " ".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert challenge_id not in logged
    assert f"'{code}'" not in logged and f'"{code}"' not in logged
    assert any(record.message == "auth.signed_in" for record in caplog.records)

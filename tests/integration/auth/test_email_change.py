import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response

from tests.support.auth import (
    Account,
    Letter,
    Mailbox,
    UserEvents,
    client_with_cookies,
    error_code,
    register,
    sign_in,
    start_login,
)


async def start_change(client: AsyncClient, new_email: str) -> Response:
    return await client.post("/api/v1/auth/email/change", json={"new_email": new_email})


async def confirm_change(
    client: AsyncClient, challenge_id: str, code: str, new_code: str
) -> Response:
    return await client.post(
        "/api/v1/auth/email/change/verify",
        json={"challenge_id": challenge_id, "code": code, "new_code": new_code},
    )


async def letters_by_template(mailbox: Mailbox, count: int) -> dict[str, Letter]:
    letters = [await mailbox.next_letter() for _ in range(count)]
    return {str(letter.body["template"]): letter for letter in letters}


def other_code(code: str) -> str:
    return "000000" if code != "000000" else "111111"


@pytest.mark.case(id="AUTH-EMAIL-001")
async def test_email_change_needs_both_codes_and_closes_other_sessions(
    app: FastAPI,
    client: AsyncClient,
    account: Account,
    mailbox: Mailbox,
    user_events: UserEvents,
) -> None:
    registered = await user_events.next_event()
    async with client_with_cookies(app, {}) as other_device:
        assert (await sign_in(other_device, mailbox, account.email)).status_code == 200

        started = await start_change(client, "New@Example.com")
        letters = await letters_by_template(mailbox, 2)
        current = letters["auth.email_change_current_code"]
        new = letters["auth.email_change_new_code"]
        confirmed = await confirm_change(
            client, started.json()["challenge_id"], current.code, new.code
        )
        event = await user_events.next_event()
        notice = await mailbox.next_letter()
        other_refresh = await other_device.post("/api/v1/auth/refresh")

    assert started.status_code == 202
    assert started.json()["masked_email"] == "u***@example.com"
    assert started.json()["masked_new_email"] == "n***@example.com"
    assert current.body["to"] == account.email
    assert current.body["params"]["new_email"] == "new@example.com"
    assert new.body["to"] == "new@example.com"
    assert confirmed.status_code == 200
    assert confirmed.json()["email"] == "new@example.com"
    assert event["type"] == "user.email_changed"
    assert event["user_id"] == registered["user_id"]
    assert event["email"] == "new@example.com"
    assert notice.body["template"] == "auth.email_changed"
    assert notice.body["to"] == account.email
    assert notice.body["params"] == {"new_email": "new@example.com"}
    assert other_refresh.status_code == 401
    assert (await client.get("/api/v1/auth/me")).json()["email"] == "new@example.com"
    assert (await start_login(client, account.email)).status_code == 404
    assert (await start_login(client, "new@example.com")).status_code == 202


@pytest.mark.case(id="AUTH-EMAIL-002")
async def test_email_change_codes_are_not_interchangeable(
    app: FastAPI, client: AsyncClient, account: Account, mailbox: Mailbox
) -> None:
    started = await start_change(client, "new@example.com")
    challenge_id = started.json()["challenge_id"]
    letters = await letters_by_template(mailbox, 2)
    code = letters["auth.email_change_current_code"].code
    new_code = letters["auth.email_change_new_code"].code

    swapped = await confirm_change(client, challenge_id, new_code, code)
    one_wrong = await confirm_change(client, challenge_id, code, other_code(new_code))
    as_login = await client.post(
        "/api/v1/auth/otp/verify", json={"challenge_id": challenge_id, "code": code}
    )
    async with client_with_cookies(app, {}) as stranger:
        assert (await register(stranger, mailbox, "stranger@example.com")).status_code == 200
        foreign = await confirm_change(stranger, challenge_id, code, new_code)
    confirmed = await confirm_change(client, challenge_id, code, new_code)

    assert swapped.status_code == one_wrong.status_code == 401
    assert error_code(swapped) == error_code(one_wrong) == "auth.otp_invalid"
    assert as_login.status_code == foreign.status_code == 410
    assert error_code(as_login) == error_code(foreign) == "auth.challenge_invalid"
    assert confirmed.status_code == 200


@pytest.mark.case(id="AUTH-EMAIL-003")
async def test_email_change_rejects_taken_same_and_anonymous(
    app: FastAPI, client: AsyncClient, account: Account, mailbox: Mailbox
) -> None:
    async with client_with_cookies(app, {}) as other:
        assert (await register(other, mailbox, "taken@example.com")).status_code == 200

    taken = await start_change(client, "taken@example.com")
    same = await start_change(client, account.email.upper())
    async with client_with_cookies(app, {}) as anonymous:
        unauthenticated = await start_change(anonymous, "new@example.com")

    assert taken.status_code == 409
    assert error_code(taken) == "auth.email_taken"
    assert same.status_code == 422
    assert error_code(same) == "auth.email_unchanged"
    assert unauthenticated.status_code == 401
    assert await mailbox.is_empty()

import asyncio
import dataclasses
import hashlib
import hmac
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid7

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)
from jwt import PyJWK
from jwt.utils import base64url_encode

from src.config import cfg
from src.core.security.dto import AccessTokenClaims
from src.core.security.exc import (
    MalformedRefreshTokenError,
    NotAuthenticatedError,
    SigningKeyUnavailableError,
)
from src.core.security.service import SecurityService


def claims_payload(**overrides: object) -> dict[str, object]:
    now = int(datetime.now(UTC).timestamp())
    payload = {
        "iss": "auth",
        "aud": "aiip",
        "sub": str(uuid7()),
        "sid": str(uuid7()),
        "iat": now,
        "exp": now + 300,
        **overrides,
    }
    return {key: value for key, value in payload.items() if value is not None}


def signing_key() -> rsa.RSAPrivateKey:
    key = load_pem_private_key(Path(cfg.auth.private_key_path).read_bytes(), password=None)
    assert isinstance(key, rsa.RSAPrivateKey)
    return key


@pytest.mark.case(id="AUTH-TOKEN-001")
def test_access_token_roundtrip_carries_user_and_session() -> None:
    security = SecurityService()
    claims = AccessTokenClaims(user_id=uuid7(), session_id=uuid7())

    assert security.decode_access_token(security.issue_access_token(claims)) == claims


@pytest.mark.case(id="AUTH-TOKEN-002")
@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int((datetime.now(UTC) - timedelta(seconds=1)).timestamp())},
        {"sid": "not-a-uuid"},
        {"iss": "someone-else"},
        {"aud": "other-system"},
        {"aud": None},
    ],
    ids=["expired", "bad-session-id", "foreign-issuer", "foreign-audience", "no-audience"],
)
def test_invalid_access_token_is_rejected(overrides: dict[str, object]) -> None:
    token = jwt.encode(claims_payload(**overrides), signing_key(), algorithm="RS256")

    with pytest.raises(NotAuthenticatedError):
        SecurityService().decode_access_token(token)


@pytest.mark.case(id="AUTH-TOKEN-003")
def test_access_token_signed_with_other_key_is_rejected() -> None:
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(claims_payload(), attacker_key, algorithm="RS256")

    with pytest.raises(NotAuthenticatedError):
        SecurityService().decode_access_token(token)


@pytest.mark.case(id="AUTH-TOKEN-004")
def test_hs256_token_keyed_with_public_key_is_rejected() -> None:
    public_pem = (
        signing_key().public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    header = base64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = base64url_encode(json.dumps(claims_payload()).encode())
    signature = hmac.new(public_pem, header + b"." + body, hashlib.sha256).digest()
    token = b".".join([header, body, base64url_encode(signature)]).decode()

    with pytest.raises(NotAuthenticatedError):
        SecurityService().decode_access_token(token)


@pytest.mark.case(id="AUTH-JWKS-001")
def test_token_verifies_with_key_published_in_jwks() -> None:
    security = SecurityService()
    claims = AccessTokenClaims(user_id=uuid7(), session_id=uuid7())
    token = security.issue_access_token(claims)
    published = dataclasses.asdict(security.jwks()[0])

    assert jwt.get_unverified_header(token)["kid"] == published["kid"]
    payload = jwt.decode(
        token, PyJWK(published).key, algorithms=["RS256"], issuer="auth", audience="aiip"
    )
    assert payload["sub"] == str(claims.user_id)
    assert "d" not in published


@pytest.mark.case(id="AUTH-TOKEN-005")
def test_refresh_token_roundtrip_and_hash_check() -> None:
    security = SecurityService()
    issued = security.issue_refresh_token(uuid7())
    stored_hash = security.hash_token(issued.secret)

    parsed = security.parse_refresh_token(str(issued))

    assert parsed == issued
    assert security.verify_token(parsed.secret, stored_hash)
    assert not security.verify_token("other-secret", stored_hash)


@pytest.mark.case(id="AUTH-TOKEN-006")
@pytest.mark.parametrize("token", ["", "no-dot", "not-a-uuid.secret", f"{uuid7()}."])
def test_malformed_refresh_token_is_rejected(token: str) -> None:
    with pytest.raises(MalformedRefreshTokenError):
        SecurityService().parse_refresh_token(token)


@pytest.mark.case(id="AUTH-PASSWORD-001")
async def test_password_hash_is_salted_and_verifiable() -> None:
    security = SecurityService()

    first = await security.hash_password("password-1")
    second = await security.hash_password("password-1")

    assert first != second
    assert first.startswith("$argon2")
    assert await security.verify_password(first, "password-1")
    assert not await security.verify_password(first, "password-2")
    assert not await security.verify_password("not-a-hash", "password-1")


@pytest.mark.case(id="AUTH-KEY-001")
def test_missing_signing_key_stops_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.auth, "private_key_path", "/nonexistent/private.pem")

    with pytest.raises(SigningKeyUnavailableError):
        SecurityService()


@pytest.mark.case(id="AUTH-PASSWORD-004")
async def test_concurrent_password_hashing_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    security = SecurityService()
    running = 0
    peak = 0
    lock = threading.Lock()

    class SlowHasher:
        def hash(self, password: str) -> str:
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with lock:
                running -= 1
            return "$argon2id$stub"

    monkeypatch.setattr(security, "_password_hasher", SlowHasher())

    await asyncio.gather(*(security.hash_password("password-1") for _ in range(8)))

    assert peak == cfg.auth.password_hashing_concurrency

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, EmailStr, Field

type NormalizedEmail = Annotated[EmailStr, Field(max_length=254), AfterValidator(str.lower)]
type ChallengeId = Annotated[str, Field(pattern=r"^ch_[A-Za-z0-9_-]{20,120}$")]
type OtpCode = Annotated[str, Field(pattern=r"^[0-9]{6}$")]


class LoginRequest(BaseModel):
    email: NormalizedEmail


class RegisterRequest(BaseModel):
    email: NormalizedEmail


class EmailChangeRequest(BaseModel):
    new_email: NormalizedEmail


class EmailChangeVerifyRequest(BaseModel):
    challenge_id: ChallengeId
    code: OtpCode
    new_code: OtpCode


class OtpVerifyRequest(BaseModel):
    challenge_id: ChallengeId
    code: OtpCode


class OtpResendRequest(BaseModel):
    challenge_id: ChallengeId


class LoginChallengeResponse(BaseModel):
    challenge_id: str
    masked_email: str
    delivery_status: Literal["queued"] = "queued"
    expires_in: int
    resend_after: int


class EmailChangeChallengeResponse(BaseModel):
    challenge_id: str
    masked_email: str
    masked_new_email: str
    delivery_status: Literal["queued"] = "queued"
    expires_in: int
    resend_after: int


class OtpResendResponse(BaseModel):
    challenge_id: str
    delivery_status: Literal["queued"] = "queued"
    expires_in: int
    resend_after: int


class UserResponse(BaseModel):
    id: UUID
    email: str
    created_at: datetime


class AuthSessionResponse(BaseModel):
    user: UserResponse
    account_created: bool

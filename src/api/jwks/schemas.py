from pydantic import BaseModel


class JwkResponse(BaseModel):
    kty: str
    n: str
    e: str
    kid: str
    use: str
    alg: str


class JwksResponse(BaseModel):
    keys: list[JwkResponse]

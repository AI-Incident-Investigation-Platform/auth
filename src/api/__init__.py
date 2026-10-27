from fastapi import APIRouter

from src.api.auth.v1.router import router as auth_v1_router

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(auth_v1_router)

router = APIRouter(prefix="/api")
router.include_router(v1_router)

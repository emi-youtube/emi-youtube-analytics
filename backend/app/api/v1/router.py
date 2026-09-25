from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.execucoes import router as execucoes_router
from app.api.v1.health import router as health_router
from app.api.v1.modelos_analise import router as modelos_analise_router
from app.api.v1.painel import router as painel_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(modelos_analise_router, tags=["modelos-analise"])
api_router.include_router(execucoes_router, tags=["execucoes"])
api_router.include_router(painel_router, tags=["painel"])

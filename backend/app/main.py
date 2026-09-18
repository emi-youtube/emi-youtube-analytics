from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(title="Emi YouTube Analytics API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    # A sessão é HTTPBearer: o token vai no header Authorization, nunca em cookie.
    # Sem credenciais o navegador não anexa cookie nem TLS client cert a estas
    # requisições, então uma origem liberada por engano não herda sessão nenhuma.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Erro 422 sem ecoar o valor enviado.

    O formato padrão do Pydantic inclui `input` com o dado recebido — numa falha de
    validação de senha isso devolveria a senha em texto plano no corpo da resposta.
    Aqui sai só onde falhou e por quê.
    """
    erros = [
        {"loc": erro["loc"], "msg": erro["msg"], "type": erro["type"]} for erro in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": erros}
    )


app.include_router(api_router, prefix="/api/v1")

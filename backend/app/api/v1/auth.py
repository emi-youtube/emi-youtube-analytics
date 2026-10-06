from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_usuario_atual
from app.core.database import get_db
from app.core.limite import LimitePorChave
from app.models.usuario import Usuario
from app.schemas.auth import (
    ConsultarConviteRequest,
    ConviteParaCadastroResponse,
    EsqueciSenhaRequest,
    EuResponse,
    MensagemResponse,
    RedefinirSenhaRequest,
    RefreshRequest,
    TokenPairResponse,
    TrocarSenhaRequest,
    UserLogin,
    UserRegister,
    UserResponse,
)
from app.services import auth as auth_service
from app.services import email as email_service
from app.services import termos as termos_service

router = APIRouter(prefix="/auth")

Sessao = Annotated[AsyncSession, Depends(get_db)]

# "Esqueci minha senha" é rota pública que dispara e-mail: 5 pedidos por IP a cada
# 15 min. Por e-mail o limite é outro, silencioso, no serviço (3 links/hora/conta).
limite_esqueci_senha = LimitePorChave(maximo=5, janela_segundos=15 * 60)

PEDIDO_REDEFINICAO_ACEITO = (
    "Se houver uma conta com este e-mail, enviaremos um link para redefinir a senha."
)


def ip_do_cliente(request: Request) -> str:
    """IP de quem chamou.

    No App Service a API fica atrás do proxy do Azure, que ACRESCENTA o IP do
    cliente ao fim do X-Forwarded-For; os itens anteriores vêm do próprio cliente e
    podem ser forjados, por isso vale o último.
    """
    encaminhado = request.headers.get("x-forwarded-for", "")
    if encaminhado.strip():
        ultimo = encaminhado.split(",")[-1].strip()
        # O Azure anexa a porta ("1.2.3.4:5678"); IPv6 vem entre colchetes.
        if ultimo.startswith("[") and "]" in ultimo:
            return ultimo[1 : ultimo.index("]")]
        return ultimo.rsplit(":", 1)[0] if ultimo.count(":") == 1 else ultimo
    return request.client.host if request.client else "desconhecido"


@router.post("/registrar", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def registrar(dados: UserRegister, db: Sessao) -> Usuario:
    """Cria a empresa e a conta de dono (`nome_empresa`) ou entra por convite."""
    return await auth_service.register_user(db, dados)


@router.post("/convites/consultar", response_model=ConviteParaCadastroResponse)
async def consultar_convite(
    dados: ConsultarConviteRequest, db: Sessao
) -> ConviteParaCadastroResponse:
    """E-mail e empresa de um convite pendente: a tela de cadastro trava o e-mail nele.

    404 com a mesma mensagem para convite inexistente, usado ou vencido.
    """
    convite, empresa = await auth_service.consultar_convite(db, dados.token)
    return ConviteParaCadastroResponse(
        email=convite.email, nome_empresa=empresa.nome, papel_empresa=convite.papel_empresa
    )


@router.post("/login", response_model=TokenPairResponse)
async def login(dados: UserLogin, db: Sessao) -> TokenPairResponse:
    usuario = await auth_service.authenticate(db, dados.email, dados.senha.get_secret_value())
    access_token, refresh_token = await auth_service.issue_token_pair(db, usuario)
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(dados: RefreshRequest, db: Sessao) -> TokenPairResponse:
    """Rotação: devolve um PAR novo e invalida o refresh enviado.

    Reenviar um refresh já trocado é tratado como cópia: todos os refresh tokens do
    usuário são revogados e a resposta é 401.
    """
    access_token, refresh_token = await auth_service.rotate_refresh_token(db, dados.refresh_token)
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(dados: RefreshRequest, db: Sessao) -> None:
    await auth_service.revoke_refresh_token(db, dados.refresh_token)


@router.get("/eu", response_model=EuResponse)
async def eu(usuario: Annotated[Usuario, Depends(get_usuario_atual)], db: Sessao) -> EuResponse:
    """Quem é o dono do token, e se falta aceitar a versão vigente dos termos.

    `termos_pendentes` não bloqueia a API: quem barra é o modal do frontend. A
    pendência existe para quem tinha conta antes do aceite (ou antes de uma versão
    nova); o cadastro já grava o aceite.
    """
    resposta = UserResponse.model_validate(usuario)
    return EuResponse(
        **resposta.model_dump(),
        termos_pendentes=await termos_service.termos_pendentes(db, usuario.id_usuario),
    )


@router.post("/trocar-senha", response_model=TokenPairResponse)
async def trocar_senha(
    dados: TrocarSenhaRequest,
    usuario: Annotated[Usuario, Depends(get_usuario_atual)],
    db: Sessao,
) -> TokenPairResponse:
    """Troca a senha. Revoga todos os refresh tokens e devolve um par novo para a
    sessão atual — as outras sessões terão de entrar de novo."""
    access_token, refresh_token = await auth_service.trocar_senha(
        db,
        usuario,
        dados.senha_atual.get_secret_value(),
        dados.nova_senha.get_secret_value(),
    )
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/esqueci-senha",
    response_model=MensagemResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def esqueci_senha(
    dados: EsqueciSenhaRequest,
    request: Request,
    tarefas: BackgroundTasks,
    db: Sessao,
) -> MensagemResponse:
    """Sempre 202 com o mesmo corpo, exista ou não a conta.

    O e-mail sai em segundo plano, depois da resposta: o tempo de envio não pode
    entrar no tempo de resposta, senão ele diria quem tem conta.
    """
    espera = limite_esqueci_senha.registrar(ip_do_cliente(request))
    if espera is not None:
        # Depende só do IP, nunca do e-mail: o 429 não revela existência de conta.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitos pedidos. Tente novamente mais tarde.",
            headers={"Retry-After": str(max(1, int(espera)))},
        )

    gerado = await auth_service.solicitar_redefinicao(db, dados.email)
    if gerado is not None:
        destinatario, token = gerado
        assunto, texto = auth_service.email_redefinicao(token)
        tarefas.add_task(email_service.enviar, destinatario, assunto, texto)
    return MensagemResponse(detail=PEDIDO_REDEFINICAO_ACEITO)


@router.post("/redefinir-senha", status_code=status.HTTP_204_NO_CONTENT)
async def redefinir_senha(dados: RedefinirSenhaRequest, db: Sessao) -> None:
    """Troca a senha pelo link do e-mail. Revoga todos os refresh tokens e zera o
    bloqueio por tentativas."""
    await auth_service.redefinir_senha(db, dados.token, dados.nova_senha.get_secret_value())

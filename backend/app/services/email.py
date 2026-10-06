"""Envio de e-mail transacional: convite para empresa e redefinição de senha.

Chamado em segundo plano (BackgroundTasks), depois de a resposta sair: o tempo de
resposta de "esqueci minha senha" não pode depender de o e-mail existir, e uma
falha do provedor não pode virar erro para quem pediu. Por isso esta função nunca
levanta exceção — ela registra e segue.

O destinatário não vai para o log em produção, só um hash curto: e-mail é dado
pessoal, e o hash basta para correlacionar com uma reclamação.
"""

import logging

import httpx

from app.core.config import settings
from app.core.security import hash_token

logger = logging.getLogger(__name__)

URL_RESEND = "https://api.resend.com/emails"
PROVEDOR_RESEND = "resend"


def _ref(destinatario: str) -> str:
    return hash_token(destinatario)[:12]


async def enviar(destinatario: str, assunto: str, texto: str) -> None:
    provedor = settings.email_provedor.strip().lower()

    if provedor == PROVEDOR_RESEND and settings.resend_api_key.strip():
        try:
            async with httpx.AsyncClient(timeout=settings.email_timeout_seconds) as cliente:
                resposta = await cliente.post(
                    URL_RESEND,
                    headers={"Authorization": f"Bearer {settings.resend_api_key.strip()}"},
                    json={
                        "from": settings.email_remetente,
                        "to": [destinatario],
                        "subject": assunto,
                        "text": texto,
                    },
                )
                resposta.raise_for_status()
        except httpx.HTTPError as erro:
            logger.error(
                "falha ao enviar e-mail provedor=resend destinatario_ref=%s assunto=%r erro=%s",
                _ref(destinatario),
                assunto,
                type(erro).__name__,
            )
            return
        logger.info(
            "e-mail enviado provedor=resend destinatario_ref=%s assunto=%r",
            _ref(destinatario),
            assunto,
        )
        return

    if settings.app_env.strip().lower() == "production":
        logger.warning(
            "e-mail NAO enviado: nenhum provedor configurado (EMAIL_PROVEDOR/RESEND_API_KEY) "
            "destinatario_ref=%s assunto=%r",
            _ref(destinatario),
            assunto,
        )
        return

    # Desenvolvimento: o "envio" é o log. É assim que se testa o fluxo sem provedor.
    logger.info("[e-mail modo log] para=%s assunto=%r\n%s", destinatario, assunto, texto)

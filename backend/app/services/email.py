"""Envio de e-mail transacional: convite para empresa e redefinição de senha.

Chamado em segundo plano (BackgroundTasks), depois de a resposta sair: o tempo de
resposta de "esqueci minha senha" não pode depender de o e-mail existir, e uma
falha do provedor não pode virar erro para quem pediu. Por isso esta função nunca
levanta exceção — ela registra e segue.

O destinatário não vai para o log em produção, só um hash curto: e-mail é dado
pessoal, e o hash basta para correlacionar com uma reclamação.
"""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from app.core.config import settings
from app.core.security import hash_token

logger = logging.getLogger(__name__)

URL_RESEND = "https://api.resend.com/emails"
PROVEDOR_RESEND = "resend"
PROVEDOR_SMTP = "smtp"
NOME_REMETENTE = "Emi Analytics"


def _ref(destinatario: str) -> str:
    return hash_token(destinatario)[:12]


def _smtp_configurado() -> bool:
    return all(v.strip() for v in (settings.smtp_host, settings.smtp_usuario, settings.smtp_senha))


def _enviar_smtp(destinatario: str, assunto: str, texto: str) -> None:
    """Envio síncrono (smtplib): roda numa thread, para não travar o laço da API.

    O remetente é o próprio usuário SMTP, porque o Gmail reescreve qualquer outro. A
    senha de app aparece no Google em grupos de 4 letras; os espaços saem aqui.
    """
    mensagem = EmailMessage()
    mensagem["From"] = formataddr((NOME_REMETENTE, settings.smtp_usuario.strip()))
    mensagem["To"] = destinatario
    mensagem["Subject"] = assunto
    mensagem.set_content(texto)

    with smtplib.SMTP(
        settings.smtp_host.strip(), settings.smtp_porta, timeout=settings.email_timeout_seconds
    ) as servidor:
        servidor.starttls(context=ssl.create_default_context())
        servidor.login(settings.smtp_usuario.strip(), settings.smtp_senha.replace(" ", ""))
        servidor.send_message(mensagem)


async def enviar(destinatario: str, assunto: str, texto: str) -> None:
    provedor = settings.email_provedor.strip().lower()

    if provedor == PROVEDOR_SMTP and _smtp_configurado():
        try:
            await asyncio.to_thread(_enviar_smtp, destinatario, assunto, texto)
        except (smtplib.SMTPException, OSError) as erro:
            # OSError cobre timeout e conexão recusada. A mensagem do erro não vai para
            # o log: em falha de login, o servidor pode ecoar parte da credencial.
            logger.error(
                "falha ao enviar e-mail provedor=smtp destinatario_ref=%s assunto=%r erro=%s",
                _ref(destinatario),
                assunto,
                type(erro).__name__,
            )
            return
        logger.info(
            "e-mail enviado provedor=smtp destinatario_ref=%s assunto=%r",
            _ref(destinatario),
            assunto,
        )
        return

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
            "e-mail NAO enviado: nenhum provedor configurado (EMAIL_PROVEDOR e RESEND_API_KEY "
            "ou SMTP_HOST, SMTP_USUARIO e SMTP_SENHA) "
            "destinatario_ref=%s assunto=%r",
            _ref(destinatario),
            assunto,
        )
        return

    # Desenvolvimento: o "envio" é o log. É assim que se testa o fluxo sem provedor.
    logger.info("[e-mail modo log] para=%s assunto=%r\n%s", destinatario, assunto, texto)

"""Aceite dos Termos de Uso e da Política de Privacidade (ADR-012).

A versão vigente é `config.VERSAO_TERMOS`, lida a cada chamada (e não importada
como nome): trocar a constante muda quem está pendente sem tocar no banco.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config
from app.models.aceite_termos import AceiteTermos

logger = logging.getLogger(__name__)


async def termos_pendentes(db: AsyncSession, id_usuario: int) -> bool:
    """Verdadeiro se não há aceite da versão vigente."""
    aceite = await db.scalar(
        select(AceiteTermos.id_aceite).where(
            AceiteTermos.id_usuario == id_usuario,
            AceiteTermos.versao_termos == config.VERSAO_TERMOS,
        )
    )
    return aceite is None


def registrar_aceite(db: AsyncSession, id_usuario: int) -> None:
    """Acrescenta o aceite da versão vigente à transação em curso. NÃO faz commit.

    Quem chama decide a transação: no cadastro, o aceite entra no mesmo commit da
    conta — não existe conta nova sem aceite, nem aceite de conta que não nasceu.
    """
    db.add(AceiteTermos(id_usuario=id_usuario, versao_termos=config.VERSAO_TERMOS))


async def aceitar(db: AsyncSession, id_usuario: int) -> None:
    """Grava o aceite da versão vigente. Idempotente: aceitar de novo não duplica.

    Dois cliques simultâneos podem passar os dois pela checagem; o UNIQUE
    (id_usuario, versao_termos) recusa o segundo INSERT, e o resultado é o mesmo:
    aceito.
    """
    if not await termos_pendentes(db, id_usuario):
        return
    registrar_aceite(db, id_usuario)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return
    logger.info(
        "evento=termos_aceitos id_usuario=%s versao_termos=%s", id_usuario, config.VERSAO_TERMOS
    )

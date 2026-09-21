"""Regras do modelo de análise (UC02).

Segurança (Seção 4.3.1): NENHUMA consulta aqui busca só por `id_modelo`. Toda
leitura ou escrita de um registro específico passa por `get_owned`, que filtra
por `id_modelo` E `id_usuario` do token. Quando o modelo é de outro usuário a
resposta é 404 — um 403 confirmaria que aquele id existe.
"""

import logging
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execucao import Execucao
from app.models.modelo_analise import ModeloAnalise
from app.models.usuario import Usuario
from app.schemas.modelo_analise import ModeloAnaliseCreate, ModeloAnaliseUpdate

logger = logging.getLogger(__name__)

ESCOPO_SEM_VIDEO = (
    "Informe ao menos um ID de vídeo nos filtros: a coleta busca comentários "
    "de vídeos curados manualmente."
)


def _validar_escopo(filtros: dict | None) -> None:
    """UC02: o modelo só tem escopo com pelo menos um vídeo em `filtros.videos`.

    São os vídeos que definem o que coletar — `commentThreads.list` parte de um
    ID de vídeo, e descobrir vídeos por texto exigiria `search.list`, proibido
    pelo CLAUDE.md (regra 4) por custar 100 unidades de cota contra 1.

    O termo de pesquisa é opcional: ele descreve a campanha e viaja congelado no
    payload do job, mas não delimita a coleta sozinho.
    """
    if not (filtros or {}).get("videos"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=ESCOPO_SEM_VIDEO
        )


async def create(db: AsyncSession, usuario: Usuario, dados: ModeloAnaliseCreate) -> ModeloAnalise:
    filtros = dados.filtros.model_dump() if dados.filtros is not None else None
    _validar_escopo(filtros)

    modelo = ModeloAnalise(
        id_usuario=usuario.id_usuario,
        nome=dados.nome,
        termo_pesquisa=dados.termo_pesquisa,
        filtros=filtros,
    )
    db.add(modelo)
    await db.commit()
    await db.refresh(modelo)

    logger.info(
        "modelo de analise criado id_modelo=%s id_usuario=%s",
        modelo.id_modelo,
        usuario.id_usuario,
    )
    return modelo


async def list_for_user(db: AsyncSession, usuario: Usuario) -> Sequence[ModeloAnalise]:
    resultado = await db.scalars(
        select(ModeloAnalise)
        .where(ModeloAnalise.id_usuario == usuario.id_usuario)
        .order_by(ModeloAnalise.criado_em.desc(), ModeloAnalise.id_modelo.desc())
    )
    return resultado.all()


async def get_owned(db: AsyncSession, usuario: Usuario, id_modelo: int) -> ModeloAnalise:
    """Único caminho para alcançar um modelo por id. Filtra pelo dono; 404 se não for dele."""
    modelo = await db.scalar(
        select(ModeloAnalise).where(
            ModeloAnalise.id_modelo == id_modelo,
            ModeloAnalise.id_usuario == usuario.id_usuario,
        )
    )
    if modelo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Modelo de análise não encontrado."
        )
    return modelo


async def update(
    db: AsyncSession, usuario: Usuario, id_modelo: int, dados: ModeloAnaliseUpdate
) -> ModeloAnalise:
    modelo = await get_owned(db, usuario, id_modelo)
    alteracoes = dados.model_dump(exclude_unset=True)

    if "filtros" in alteracoes:
        filtros = dados.filtros.model_dump() if dados.filtros is not None else None
        alteracoes["filtros"] = filtros

    # Revalida o estado final: sem isso um PATCH conseguiria deixar o registro na
    # mesma situação que o POST recusa.
    _validar_escopo(alteracoes.get("filtros", modelo.filtros))

    for campo, valor in alteracoes.items():
        setattr(modelo, campo, valor)

    await db.commit()
    await db.refresh(modelo)
    return modelo


async def delete(db: AsyncSession, usuario: Usuario, id_modelo: int) -> None:
    modelo = await get_owned(db, usuario, id_modelo)

    # EXECUCOES referencia MODELOS_ANALISE sem cascade (CLAUDE.md Seção 4): apagar um
    # modelo já executado apagaria o histórico da análise, então é barrado.
    tem_execucao = await db.scalar(
        select(Execucao.id_execucao).where(Execucao.id_modelo == id_modelo).limit(1)
    )
    if tem_execucao is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível remover um modelo que já possui execuções.",
        )

    try:
        await db.delete(modelo)
        await db.commit()
    except IntegrityError:
        # Corrida: uma execução pode ter sido criada entre a checagem e o commit.
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível remover um modelo que já possui execuções.",
        ) from None

    logger.info(
        "modelo de analise removido id_modelo=%s id_usuario=%s", id_modelo, usuario.id_usuario
    )

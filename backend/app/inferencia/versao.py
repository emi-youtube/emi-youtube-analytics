"""Resolve o `DescritorVersao` do classificador na linha de VERSOES_MODELO.

Toda análise aponta para a versão que a produziu — é o que permite, meses depois,
saber se aquele "negativo" no painel saiu do léxico ou do BERTimbau, e com que
recurso. Sem isso, trocar de classificador apagaria o significado do histórico.

A linha nasce sozinha, na primeira vez que aquela versão classifica algo. A
alternativa seria semear as versões numa migration, e ela seria pior: a migration
passaria a carregar o `sha256` do arquivo do SentiLex e a versão do pacote, dados que
vêm do artefato e mudam sem schema mudar. Quem sabe a identidade é a implementação.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.inferencia.base import DescritorVersao
from app.models.versao_modelo import VersaoModelo

logger = logging.getLogger(__name__)

STATUS_ATIVO = "ativo"


async def garantir_versao(db: AsyncSession, descritor: DescritorVersao) -> VersaoModelo:
    """Devolve a linha de VERSOES_MODELO do descritor, criando-a se for a primeira vez.

    Idempotente: reprocessar uma execução não cria uma segunda linha para a mesma
    versão, senão as análises da mesma implementação apontariam para ids diferentes e
    o painel mostraria dois classificadores onde só existe um.

    Faz commit da linha ANTES de a inferência começar, e de propósito: as análises
    referenciam `id_versao` por chave estrangeira, e uma falha no meio do lote não
    pode levar a versão embora junto — ela não é resultado da execução, é identidade
    do classificador.
    """
    versao = await _buscar(db, descritor)
    if versao is not None:
        return versao

    versao = VersaoModelo(
        nome_modelo=descritor.nome_modelo,
        versao=descritor.versao,
        # A avaliação do Capítulo 5 entra aqui depois, ao lado da proveniência, e só
        # contra o gabarito HUMANO (CLAUDE.md regra 6). Hoje a chave não existe: um
        # dicionário vazio de métricas seria lido como "avaliado e deu zero".
        metricas_avaliacao={"proveniencia": descritor.proveniencia},
        status=STATUS_ATIVO,
    )
    db.add(versao)

    try:
        await db.commit()
    except IntegrityError:
        # Dois workers subindo ao mesmo tempo com a mesma versão. O UNIQUE de
        # (nome_modelo, versao) é quem garante a regra de fato; aqui só relemos a
        # linha que o outro criou.
        await db.rollback()
        versao = await _buscar(db, descritor)
        if versao is None:
            raise
        return versao

    await db.refresh(versao)
    logger.info(
        "versao de modelo registrada id_versao=%s nome=%s versao=%s",
        versao.id_versao,
        versao.nome_modelo,
        versao.versao,
    )
    return versao


async def _buscar(db: AsyncSession, descritor: DescritorVersao) -> VersaoModelo | None:
    return await db.scalar(
        select(VersaoModelo).where(
            VersaoModelo.nome_modelo == descritor.nome_modelo,
            VersaoModelo.versao == descritor.versao,
        )
    )

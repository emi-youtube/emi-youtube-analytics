"""Enfileira o recálculo dos tópicos de uma execução já concluída.

    python -m app.workers.recalcular_topicos --id-execucao 4
    python -m app.workers.recalcular_topicos --id-execucao 4 --confirmar

**Para que serve.** O método de tópicos melhora — stopwords de marca, lista de
stopwords nova, outro valor de `k`. As execuções antigas continuam com os temas
que o método antigo produziu. Este comando enfileira um job que APAGA os temas
daquela execução e refaz a modelagem sobre os MESMOS comentários, sem recoletar
nada: zero unidade de cota da YouTube API.

**Por que um comando e não uma rota.** Refazer a análise de uma execução
concluída troca, debaixo de um painel que o usuário já leu, os temas que ele viu.
Isso é manutenção deliberada, não algo que se dispara sem saber — e uma rota na
API convidaria exatamente isso. O caminho explícito é a decisão.

**O que ele NÃO faz:** não recoleta comentário, não reclassifica sentimento e não
toca em ANALISES_SENTIMENTO. Só os temas da execução são refeitos.

Sem `--confirmar` o comando só mostra o que faria.
"""

import argparse
import asyncio
import logging

from sqlalchemy import func, select

from app.core.database import async_session_factory
from app.models.comentario import Comentario
from app.models.execucao import Execucao
from app.models.job import Job
from app.models.tema import Tema
from app.models.video import Video
from app.workers.pipeline import TIPO_TOPICOS

logger = logging.getLogger(__name__)

STATUS_PENDENTE = "pendente"


async def enfileirar(id_execucao: int, *, confirmar: bool) -> int:
    """Publica o job de recálculo. Devolve o id do job, ou 0 em ensaio/erro."""
    async with async_session_factory() as db:
        execucao = await db.get(Execucao, id_execucao)
        if execucao is None:
            print(f"execucao {id_execucao} nao existe")
            return 0

        temas = await db.scalar(
            select(func.count()).select_from(Tema).where(Tema.id_execucao == id_execucao)
        )
        comentarios = await db.scalar(
            select(func.count())
            .select_from(Comentario)
            .join(Video, Video.id_video == Comentario.id_video)
            .where(Video.id_execucao == id_execucao)
        )
        videos = await db.scalar(
            select(func.count()).select_from(Video).where(Video.id_execucao == id_execucao)
        )

        print(
            f"execucao {id_execucao}: status={execucao.status} videos={videos} "
            f"comentarios={comentarios} temas_atuais={temas}"
        )

        # Job pendente do mesmo tipo já na fila: enfileirar outro faria a
        # modelagem rodar duas vezes seguidas, e a segunda apagaria a primeira.
        ja_na_fila = await db.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.id_execucao == id_execucao,
                Job.tipo == TIPO_TOPICOS,
                Job.status.in_(("pendente", "processando")),
            )
        )
        if ja_na_fila:
            print("ja existe job de topicos pendente para esta execucao; nada a fazer")
            return 0

        if not confirmar:
            print(f"ENSAIO: apagaria {temas} tema(s) e remodelaria {comentarios} comentario(s).")
            print("Nenhuma unidade de cota da YouTube API e gasta.")
            print("Rode de novo com --confirmar para enfileirar de verdade.")
            return 0

        job = Job(
            tipo=TIPO_TOPICOS,
            id_execucao=id_execucao,
            status=STATUS_PENDENTE,
            payload={"recalcular": True},
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        print(f"job {job.id_job} enfileirado (tipo=topicos, recalcular=true).")
        print("Suba o worker para processa-lo: python -m app.workers.runner")
        return job.id_job


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id-execucao", type=int, required=True)
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="enfileira de verdade; sem isto o comando so mostra o que faria",
    )
    argumentos = parser.parse_args()

    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
    asyncio.run(enfileirar(argumentos.id_execucao, confirmar=argumentos.confirmar))


if __name__ == "__main__":
    main()

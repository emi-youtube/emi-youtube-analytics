"""Por quanto tempo o Emi guarda o que vem do YouTube (ADR-015, docs/BANCO.md).

As políticas dos YouTube API Services separam duas coisas:

- **O que vem da API** sem login do autor (o comentário público coletado com a chave,
  o título do vídeo, o nome do canal) é *Non-Authorized Data*: no máximo **30 dias**,
  depois apagar ou atualizar (III.E.4.d).
- **O que o Emi calcula** a partir disso (sentimento, temas, percentuais) é métrica
  derivada e, com as visualizações e curtidas da coleta, pode ficar até **36 meses**
  (*derived metrics policy*, que exige aceitar a emenda no formulário de auditoria).

Aqui só ficam os prazos, para a tela e o expurgo usarem a MESMA conta. Quem apaga é
`app/workers/expurgo.py`.
"""

from datetime import datetime, timedelta

from app.core.config import settings

# O expurgo roda de hora em hora e pode atrasar (worker reiniciando, ciclo longo de
# inferência). Apagar um dia antes garante que nada passe do 30º dia.
MARGEM = timedelta(days=1)


def prazo_dos_comentarios() -> timedelta:
    """Quanto tempo, contado do início da execução, o texto dos comentários fica."""
    return timedelta(days=settings.youtube_guarda_dias) - MARGEM


def prazo_dos_resultados() -> timedelta:
    """Quanto tempo, contado do início da execução, a execução inteira fica."""
    return timedelta(days=settings.youtube_guarda_resultados_dias)


def comentarios_disponiveis_ate(iniciado_em: datetime | None) -> datetime | None:
    """Até quando os comentários da execução podem ser lidos. Nulo se não começou.

    O relógio é o `iniciado_em`, e não a hora em que cada comentário foi gravado: a
    coleta só grava depois de reivindicar o job, então contar do início apaga no
    máximo algumas horas mais cedo, nunca mais tarde.
    """
    if iniciado_em is None:
        return None
    return iniciado_em + prazo_dos_comentarios()

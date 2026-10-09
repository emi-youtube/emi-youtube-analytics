"""Configuração de log compartilhada pela API e pelo runner.

**Por que existe.** O runner sempre configurou o próprio log (`workers/runner.py`),
mas a API não: o uvicorn configura só os loggers dele (`uvicorn`, `uvicorn.access`),
e os loggers da aplicação (`app.*`) caíam no logger raiz sem handler, que só
deixa passar WARNING para cima. Resultado: todo `logger.info` dos serviços
(cadastro, exclusão de conta, mudança de papel, aceite dos termos) sumia em
produção, e só o reuso de token, que é WARNING, aparecia no Log stream.

Os loggers do uvicorn têm `propagate=False`, então configurar o raiz aqui não
duplica as linhas de acesso.
"""

import logging

FORMATO = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configurar_logs(nivel: str) -> None:
    """Põe um handler no logger raiz no `nivel` pedido. Idempotente.

    `basicConfig` não faz nada se o raiz já tem handler (outro processo, testes);
    o nível é aplicado mesmo assim, para valer o `LOG_LEVEL` configurado.
    """
    logging.basicConfig(level=nivel, format=FORMATO)
    logging.getLogger().setLevel(nivel)
    # Em INFO o httpx loga a URL completa de cada requisição. Hoje a chave do YouTube
    # vai no cabeçalho (workers/youtube.py), mas qualquer parâmetro sensível que
    # entre na query cairia no log. WARNING mantém erro de rede visível e cala o resto.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

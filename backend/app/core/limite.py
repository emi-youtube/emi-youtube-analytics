"""Limite de requisições por chave, em memória, para rotas públicas sensíveis.

Usado no "esqueci minha senha" e no cadastro, por IP. Fica em memória do processo de propósito: a
API roda com UM worker do uvicorn (startup.sh), e o pior caso de um reinício é o
contador zerar — aceitável para um freio de abuso. A fila e o resto do estado
continuam no Postgres; isto não é estado de negócio.
"""

import time
from collections import deque


class LimitePorChave:
    def __init__(self, maximo: int, janela_segundos: float) -> None:
        self.maximo = maximo
        self.janela = janela_segundos
        self._eventos: dict[str, deque[float]] = {}

    def _podar(self, agora: float) -> None:
        # Poda na própria escrita, como `tentativas_login`: o dicionário não cresce
        # com chaves que já saíram da janela.
        for chave in [
            c for c, ev in self._eventos.items() if not ev or ev[-1] <= agora - self.janela
        ]:
            del self._eventos[chave]

    def registrar(self, chave: str) -> float | None:
        """Conta um evento. Devolve os segundos de espera se estourou, ou None."""
        agora = time.monotonic()
        self._podar(agora)
        eventos = self._eventos.setdefault(chave, deque())
        while eventos and eventos[0] <= agora - self.janela:
            eventos.popleft()
        if len(eventos) >= self.maximo:
            return eventos[0] + self.janela - agora
        eventos.append(agora)
        return None

    def limpar(self) -> None:
        self._eventos.clear()

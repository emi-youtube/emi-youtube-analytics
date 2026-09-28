"""O cofre do Colab, lido do ambiente do contêiner (o teste passa a `DATABASE_URL`)."""

import os


def get(nome: str) -> str:
    valor = os.environ.get(nome)
    if not valor:
        raise KeyError(f"segredo {nome} nao existe no cofre (variavel de ambiente)")
    return valor

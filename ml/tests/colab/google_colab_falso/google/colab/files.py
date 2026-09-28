"""`files.download` do Colab: aqui só confere que o arquivo pedido existe."""

from pathlib import Path


def download(caminho: str) -> None:
    if not Path(caminho).is_file():
        raise FileNotFoundError(f"download de arquivo inexistente: {caminho}")
    print("[download simulado]", caminho)

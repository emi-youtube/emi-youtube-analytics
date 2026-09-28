"""Roda DENTRO do contêiner que simula o Colab. Quem o chama é `test_notebook_colab.py`.

Dois cenários, e cada um é um bug que já aconteceu numa sessão de verdade:

- `inteiro` — "Executar tudo" num ambiente recém-criado: clona, instala por cima do
  torch da casa, treina (ensaio reduzido) e confere que todo artefato prometido existe;
- `reinicio` — o kernel morre depois da instalação (reinício manual, desconexão,
  falta de memória) e a pessoa continua de onde parou. O disco sobrevive, a memória do
  kernel não: `sys.path`, diretório de trabalho e variáveis somem. A célula de
  verificação tem que dizer isso com todas as letras, e "Executar tudo" de novo tem que
  funcionar — clone já existente, pacotes já instalados.

Um kernel NOVO é o reinício: é exatamente o que o Colab faz ao reiniciar a sessão.

O repositório vem de `/entrada/repo.tar` (a árvore de trabalho de quem roda o teste,
sem o que o `.gitignore` exclui) e vira um git local em `/src`, de onde o notebook
clona — como no Colab, só que da cópia em teste e não do GitHub. O caderno executado
é gravado em `/saida`, com erro ou sem, para quem precisar ver a saída das células.
"""

import os
import subprocess
import sys
import tarfile
import traceback
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

ORIGEM = Path("/src")
CONTEUDO = Path("/content")
SAIDA = Path("/saida")
NOTEBOOK = ORIGEM / "ml" / "treino" / "colab_bertimbau.ipynb"
TEMPO_LIMITE_CELULA = 3600


def preparar_origem() -> None:
    """Descompacta a árvore em teste e faz dela um repositório clonável."""
    ORIGEM.mkdir(parents=True, exist_ok=True)
    with tarfile.open("/entrada/repo.tar") as arquivo:
        arquivo.extractall(ORIGEM, filter="data")
    for comando in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=teste", "-c", "user.email=teste@local", "commit", "-qm", "x"],
    ):
        subprocess.run(comando, cwd=ORIGEM, check=True)


def indice(celulas: list, trecho: str) -> int:
    for posicao, celula in enumerate(celulas):
        if celula.cell_type == "code" and trecho in celula.source:
            return posicao
    raise AssertionError(f"nenhuma celula de codigo contem {trecho!r}")


def rodar(notebook, posicoes: list[int], nome: str) -> None:
    """Executa as células pedidas, em ordem, num kernel novo."""
    cliente = NotebookClient(
        notebook,
        timeout=TEMPO_LIMITE_CELULA,
        kernel_name="python3",
        resources={"metadata": {"path": str(CONTEUDO)}},
    )
    ambiente = {**os.environ, "EMI_REPOSITORIO": f"file://{ORIGEM}"}
    try:
        with cliente.setup_kernel(env=ambiente):
            for posicao in posicoes:
                print(f"[{nome}] celula {posicao}", flush=True)
                cliente.execute_cell(notebook.cells[posicao], posicao)
                # A cada celula, e nao so no fim: se o conteiner morrer (ja aconteceu,
                # pelo proprio Docker), o que rodou ate ali fica no disco para ler.
                nbformat.write(notebook, SAIDA / f"{nome}.ipynb")
    finally:
        nbformat.write(notebook, SAIDA / f"{nome}.ipynb")


def artefatos_prometidos() -> list[Path]:
    """Os caminhos da célula de constantes, calculados como o Colab os calcularia."""
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    espaco: dict[str, object] = {}
    fonte = notebook.cells[indice(notebook.cells, "RAIZ = ")].source
    exec(compile(fonte, "<celula de constantes>", "exec"), espaco)
    ignorar = {"RAIZ"} | (set() if os.environ.get("RODAR_ONNX") else {"RELATORIO_ONNX"})
    return [
        valor for nome, valor in espaco.items() if isinstance(valor, Path) and nome not in ignorar
    ]


def inteiro() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    codigo = [i for i, celula in enumerate(notebook.cells) if celula.cell_type == "code"]
    rodar(notebook, codigo, "inteiro")

    faltando = [str(caminho) for caminho in artefatos_prometidos() if not caminho.exists()]
    assert not faltando, "o notebook rodou ate o fim mas nao gravou: " + ", ".join(faltando)
    print("OK: notebook inteiro, todos os artefatos no disco")


def reinicio() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    verificacao = indice(notebook.cells, "importlib.import_module")
    ate_verificacao = [
        i
        for i, celula in enumerate(notebook.cells[: verificacao + 1])
        if celula.cell_type == "code"
    ]

    # 1. Instala e verifica: a sessão saudável.
    rodar(notebook, ate_verificacao, "reinicio-1-instalacao")

    # 2. Kernel reiniciado; a pessoa roda só a verificação. Tem que falhar AVISANDO.
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    try:
        rodar(notebook, [verificacao], "reinicio-2-so-verificacao")
    except CellExecutionError as erro:
        mensagem = str(erro)
        assert "ModuleNotFoundError" not in mensagem, (
            "depois de reiniciar, a verificacao quebrou com ModuleNotFoundError em vez de "
            "dizer o que fazer:\n" + mensagem[-2000:]
        )
        assert "Executar anteriores" in mensagem, (
            "a verificacao falhou, mas sem dizer como sair:\n" + mensagem[-2000:]
        )
    else:
        raise AssertionError("verificacao passou num kernel sem as celulas anteriores")

    # 3. "Executar tudo" de novo, no mesmo disco: clone existe, pacotes instalados.
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    rodar(notebook, ate_verificacao, "reinicio-3-de-novo")
    print("OK: reinicio avisado e segunda execucao limpa")


if __name__ == "__main__":
    SAIDA.mkdir(parents=True, exist_ok=True)
    preparar_origem()
    cenario = {"inteiro": inteiro, "reinicio": reinicio}[sys.argv[1]]
    try:
        cenario()
    except (CellExecutionError, AssertionError):
        traceback.print_exc()
        sys.exit(1)

"""O notebook do Colab roda inteiro, de ponta a ponta, num kernel de verdade?

**Por que este arquivo existe.** As correções anteriores do notebook foram feitas lendo
o código, e todas passaram no `ruff` e nos testes estáticos. Mesmo assim a sessão
seguinte no Colab quebrou — `asyncio.run` dentro de um kernel que já tem laço de
eventos, um clone que criou uma cópia dentro da outra, a célula final procurando
relatório num caminho que ninguém escreveu. Nada disso aparece lendo célula; aparece
executando.

Este teste executa **todas** as células no `ml/.venv`, com `ENSAIO_REDUZIDO=1`: corpus
de 150 exemplos, grade de uma configuração, duas sementes e a medição ONNX em 40
comentários. O que ele prova não é a qualidade de nada — é que nenhuma célula levanta
exceção e que **todo caminho que o notebook promete gravar existe no fim**. Era
exatamente esse o buraco: o notebook "rodou" e voltou sem o `.onnx` e sem o relatório.

**Não roda por padrão.** Precisa de banco, de CPU e de uns 20 minutos (o fine-tuning é
de verdade, só que pequeno; a exportação ONNX de um BERT em CPU é a parte lenta):

    TESTE_NOTEBOOK=1 ml/.venv/Scripts/python.exe -m pytest ml/tests/test_notebook.py

Rode-o depois de mexer no notebook e antes de gastar uma sessão de GPU com ele.

**O que ele não cobre.** As células que só existem no Colab — clone, `pip install`,
cofre de credenciais e `files.download` — ficam atrás do `NO_COLAB` e não executam
aqui. Quem cobre a instalação é `ml/tests/test_ambiente_colab.py`, que monta um
ambiente limpo com a lista que o próprio notebook declara. O download em si não é
testável fora do navegador; o que dá para provar — e é o que faltou — é que os arquivos
que ele pediria estão no disco.
"""

import json
import os
from pathlib import Path

import pytest

from ml.config import RAIZ_REPO

NOTEBOOK = RAIZ_REPO / "ml" / "treino" / "colab_bertimbau.ipynb"

# Minutos, não segundos: a célula da busca treina de verdade, e a exportação ONNX em
# CPU leva alguns minutos só para quantizar o grafo.
TEMPO_LIMITE_CELULA = 3600

EXECUTA_NOTEBOOK = bool(os.environ.get("TESTE_NOTEBOOK"))
MOTIVO = (
    "executa o notebook inteiro num kernel (precisa de banco e de ~20 min). "
    "Rode com TESTE_NOTEBOOK=1 depois de mexer no notebook."
)


def celula_das_constantes() -> str:
    """O código da primeira célula do notebook — a que define `RAIZ` e o resto."""
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for celula in notebook["cells"]:
        if celula["cell_type"] != "code":
            continue
        fonte = "".join(celula["source"])
        if "RAIZ = " in fonte:
            return fonte
    raise AssertionError("o notebook nao tem mais uma celula que define RAIZ")


def caminhos_do_notebook(reduzido: bool) -> dict[str, Path]:
    """Todo `Path` que a célula de constantes define, com os valores que ela daria.

    **Executa a célula**, em vez de lê-la por AST. Os caminhos do ensaio reduzido saem
    de f-string com sufixo condicional, e um analisador estático teria que reimplementar
    a avaliação de expressão do Python para saber o valor — reimplementação que
    envelheceria em silêncio e faria o teste conferir caminho que o notebook não usa.
    A célula é código de stdlib puro, sem efeito colateral: ela calcula caminhos e
    imprime uma linha.

    É também o que prova a regra da constante única. Se uma célula adiante montar
    caminho por conta própria, o arquivo dela não aparece aqui e ninguém confere que ele
    foi gravado.
    """
    espaco: dict[str, object] = {}
    anterior = os.environ.get("ENSAIO_REDUZIDO")
    diretorio = Path.cwd()
    try:
        os.environ["ENSAIO_REDUZIDO"] = "1" if reduzido else ""
        os.chdir(RAIZ_REPO)  # fora do Colab a celula usa o diretorio de trabalho
        exec(compile(celula_das_constantes(), "<celula de constantes>", "exec"), espaco)
    finally:
        os.chdir(diretorio)
        if anterior is None:
            os.environ.pop("ENSAIO_REDUZIDO", None)
        else:
            os.environ["ENSAIO_REDUZIDO"] = anterior

    # RAIZ fica de fora: ela é o repositório, ninguém a grava, e a conferência de data
    # de modificação acusaria como "intacta" uma pasta que não tem por que mudar.
    return {
        nome: valor
        for nome, valor in espaco.items()
        if isinstance(valor, Path) and nome != "RAIZ"
    }


def test_o_notebook_deriva_todo_caminho_da_raiz():
    """Estático, roda sempre: as constantes de caminho continuam saindo de `RAIZ`."""
    caminhos = caminhos_do_notebook(reduzido=False)

    esperadas = ("MODELO", "BUSCA", "SEMENTES_JSON", "RELATORIO_ONNX", "PREVISOES", "PACOTE")
    for nome in esperadas:
        assert nome in caminhos, f"{nome} nao e mais derivado de RAIZ no notebook"
        assert RAIZ_REPO in caminhos[nome].parents, f"{nome} aponta para fora do repositorio"


def test_o_ensaio_reduzido_nao_escreve_onde_o_treino_de_verdade_escreve():
    """O teste que executa o notebook não pode custar a sessão de GPU de ninguém.

    `ml/modelos/` está fora do git: pesos sobrescritos por uma rodada de fumaça não
    voltam de lugar nenhum.
    """
    de_verdade = caminhos_do_notebook(reduzido=False)
    reduzido = caminhos_do_notebook(reduzido=True)

    assert set(de_verdade) == set(reduzido)
    colidindo = [nome for nome in de_verdade if de_verdade[nome] == reduzido[nome]]
    assert not colidindo, f"o ensaio reduzido grava por cima do treino de verdade: {colidindo}"


@pytest.mark.skipif(not EXECUTA_NOTEBOOK, reason=MOTIVO)
def test_o_notebook_roda_inteiro_e_deixa_os_artefatos_no_disco():
    """Executa todas as células e confere o que ficou no disco.

    O kernel roda com a **raiz do repositório** como diretório de trabalho, que é o que
    a primeira célula usa como `RAIZ` fora do Colab.

    A conferência é por **data de modificação**, e não só por existência: os pesos e os
    relatórios de uma execução anterior estão no disco (não são versionados, mas também
    não são apagados), e um teste que só olhasse `exists()` passaria com o resultado da
    rodada passada mesmo que esta não tivesse gravado nada. Comparar a data prova que
    foi ESTA execução que escreveu — sem mover 400 MB de pesos para um diretório
    temporário, que é a alternativa destrutiva à pergunta.
    """
    pytest.importorskip("nbclient", reason="pip install -r ml/requirements-dev.txt")
    import nbformat
    from nbclient import NotebookClient

    esperados = sorted(caminhos_do_notebook(reduzido=True).values())
    antes = {
        caminho: caminho.stat().st_mtime if caminho.exists() else None for caminho in esperados
    }

    notebook = nbformat.read(NOTEBOOK, as_version=4)
    cliente = NotebookClient(
        notebook,
        timeout=TEMPO_LIMITE_CELULA,
        kernel_name="python3",
        resources={"metadata": {"path": str(RAIZ_REPO)}},
    )
    cliente.execute(env={**os.environ, "ENSAIO_REDUZIDO": "1"})

    faltando = [caminho for caminho in esperados if not caminho.exists()]
    assert not faltando, (
        "o notebook rodou ate o fim mas nao gravou: "
        + ", ".join(str(caminho) for caminho in faltando)
    )

    velhos = [
        caminho
        for caminho in esperados
        if antes[caminho] is not None and caminho.stat().st_mtime <= antes[caminho]
    ]
    assert not velhos, (
        "arquivo intacto depois da execucao (e de uma rodada anterior, nao desta): "
        + ", ".join(str(caminho) for caminho in velhos)
    )

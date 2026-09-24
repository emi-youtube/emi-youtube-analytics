"""O ambiente que o notebook monta cobre tudo o que `ml/treino` importa?

**Por que este arquivo existe.** O teste de fumaça do treino rodou no `ml/.venv`, que
já tinha `asyncpg` instalado desde a exportação do corpus. No Colab, ambiente novo, a
célula 3 quebrou com `No module named 'asyncpg'` — e o `!pip` que falhou nem
interrompeu o notebook, então o erro apareceu três células depois da causa. Nenhum
teste que roda no ambiente de quem desenvolve pega esse tipo de coisa: o ambiente de
quem desenvolve é justamente o que já tem tudo.

São dois testes, e eles respondem a perguntas diferentes:

1. **estático, roda sempre** — o notebook instala requisitos que cobrem cada import de
   terceiros de `ml/treino`? Custa milissegundos e pega a regressão mais provável:
   alguém acrescenta `import scipy` num módulo e esquece do `requirements-treino.txt`;
2. **real, sob demanda** — cria um ambiente virtual limpo, roda exatamente os comandos
   de instalação do notebook e importa todos os módulos de `ml/treino` lá dentro. É o
   único que prova o que o Colab vai encontrar, e é o que teria pego o erro original.
   Baixa `torch` e companhia (uns 2 GB, alguns minutos), então só roda quando pedido:

       TESTE_AMBIENTE=1 ml/.venv/Scripts/python.exe -m pytest ml/tests/test_ambiente_colab.py

**Os dois leem os comandos do próprio notebook.** Copiar a lista de pacotes para cá
criaria uma segunda fonte de verdade que envelheceria em silêncio — exatamente o tipo
de divergência que o teste deveria detectar.

**O que nenhum dos dois pega, e por quê.** O teste do ambiente real importa num
processo NOVO, e num processo novo a instalação editável funciona: o `.pth` é lido na
inicialização do interpretador. O problema do `-e` é específico de um kernel que já
está rodando — o caso do Colab —, e reproduzi-lo exigiria manter um interpretador vivo
durante a instalação. Quem protege esse ponto é o teste estático
`test_o_preprocessamento_nao_entra_editavel_no_notebook`, que olha o comando em vez do
efeito.

Também não dá para testar daqui o que o Colab faz com a rede e com os pacotes que ele
já vem trazendo. Contra isso o que existe é a célula de verificação do notebook: ela
não evita a falha, mas faz o erro aparecer na célula que o causou.
"""

import ast
import json
import os
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from ml.config import RAIZ_REPO

DIRETORIO_TREINO = RAIZ_REPO / "ml" / "treino"
NOTEBOOK = DIRETORIO_TREINO / "colab_bertimbau.ipynb"

# Qual distribuição instala cada módulo importado. O mapa é explícito porque nome de
# módulo e nome de pacote não são a mesma coisa, e adivinhar seria pior que declarar.
#
# `numpy` aparece com o nome de quem o traz: ele não está em nenhum requirements do
# projeto, vem junto do `torch` e do `transformers`. É justamente o caso em que o
# teste estático não basta — quem prova que a dependência transitiva chegou é o teste
# do ambiente real, mais abaixo.
DISTRIBUICAO_DE = {
    "asyncpg": "asyncpg",
    "matplotlib": "matplotlib",
    "numpy": "torch",
    "onnx": "onnx",
    "onnxruntime": "onnxruntime",
    "openpyxl": "openpyxl",
    "preprocessamento": "preprocessamento",
    "psutil": "psutil",
    "torch": "torch",
    "transformers": "transformers",
}


def comandos_de_instalacao() -> list[list[str]]:
    """Os argumentos de cada `pip install` do notebook, na ordem em que ele os executa.

    Lidos da constante `INSTALACAO` do notebook, por AST — e não de linhas `!pip` por
    prefixo de texto. O notebook declara a instalação como DADOS justamente para que
    este teste possa reexecutá-la: uma linha de shell com um caminho interpolado na
    hora não roda fora do Colab, e um teste que lê uma célula que mudou de forma passa
    a aprovar o vazio, que é o pior resultado possível para um teste de ambiente.

    Célula com `await` de nível superior não é Python válido fora do kernel, então cada
    uma é analisada por conta própria e a que não compilar é ignorada.
    """
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for celula in notebook["cells"]:
        if celula["cell_type"] != "code":
            continue
        try:
            arvore = ast.parse("".join(celula["source"]))
        except SyntaxError:
            continue
        for no in ast.walk(arvore):
            if isinstance(no, ast.Assign) and any(
                isinstance(alvo, ast.Name) and alvo.id == "INSTALACAO" for alvo in no.targets
            ):
                return [list(argumentos) for argumentos in ast.literal_eval(no.value)]
    return []


def modulos_de_treino() -> list[str]:
    """Todo módulo de `ml/treino`, descoberto por varredura.

    Varredura e não lista fixa: módulo novo entra no teste sozinho, que é o
    comportamento certo para um teste cuja função é pegar o que foi esquecido.
    """
    return sorted(
        f"ml.treino.{caminho.stem}"
        for caminho in DIRETORIO_TREINO.glob("*.py")
        if caminho.stem != "__init__"
    )


def importes_de_terceiros() -> set[str]:
    """Os pacotes de terceiros que `ml/treino` importa, pelo AST dos arquivos.

    Ignora a stdlib e o próprio `ml`. Pega import dentro de função também — e isso
    importa: `prever_teste.py` importa `torch` e `onnxruntime` lá dentro, de
    propósito, para que quem usa só um dos dois caminhos não precise do outro.
    """
    encontrados: set[str] = set()
    for caminho in DIRETORIO_TREINO.glob("*.py"):
        arvore = ast.parse(caminho.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                encontrados.update(alias.name.split(".")[0] for alias in no.names)
            elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                encontrados.add(no.module.split(".")[0])
    return {
        nome
        for nome in encontrados
        if nome not in sys.stdlib_module_names and nome != "ml"
    }


def requisitos_declarados(caminho: Path, vistos: set[Path] | None = None) -> set[str]:
    """Distribuições de um requirements, seguindo os `-r` aninhados.

    Normaliza o nome como a PEP 503 manda (minúsculo, `_` e `.` viram `-`), senão
    `scikit_learn` e `scikit-learn` pareceriam pacotes diferentes.
    """
    vistos = vistos if vistos is not None else set()
    caminho = caminho.resolve()
    if caminho in vistos or not caminho.exists():
        return set()
    vistos.add(caminho)

    distribuicoes: set[str] = set()
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        limpa = linha.split("#")[0].strip()
        if not limpa:
            continue
        if limpa.startswith("-r "):
            distribuicoes |= requisitos_declarados(
                caminho.parent / limpa.removeprefix("-r ").strip(), vistos
            )
            continue
        if limpa.startswith("-e "):
            limpa = limpa.removeprefix("-e ").strip()
        if limpa.startswith((".", "/", "./")) or (RAIZ_REPO / limpa).exists():
            # Caminho local: a distribuição tem o nome da pasta (`./preprocessamento`).
            distribuicoes.add(Path(limpa).name.lower())
            continue
        nome = limpa.split("==")[0].split(">=")[0].split("[")[0].strip()
        distribuicoes.add(nome.lower().replace("_", "-").replace(".", "-"))
    return distribuicoes


def distribuicoes_que_o_notebook_instala() -> set[str]:
    """O que os comandos do notebook trazem: requirements mais caminhos locais."""
    distribuicoes: set[str] = set()
    for argumentos in comandos_de_instalacao():
        for posicao, parte in enumerate(argumentos):
            if parte == "-r" and posicao + 1 < len(argumentos):
                distribuicoes |= requisitos_declarados(RAIZ_REPO / argumentos[posicao + 1])
            elif parte.startswith("./"):
                distribuicoes.add(Path(parte).name.lower())
    return distribuicoes


def fonte_da_celula_de_instalacao() -> str:
    """O código da célula que declara `INSTALACAO` — a que clona e instala."""
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for celula in notebook["cells"]:
        if celula["cell_type"] == "code":
            fonte = "".join(celula["source"])
            if "INSTALACAO" in fonte and "pip" in fonte:
                return fonte
    raise AssertionError("o notebook nao tem mais uma celula que usa INSTALACAO")


# ------------------------------------------------------- estatico (roda sempre)


def test_o_notebook_tem_celula_de_instalacao():
    comandos = comandos_de_instalacao()
    assert comandos, (
        "notebook sem a constante INSTALACAO — a celula 1 sumiu, ou a instalacao "
        "voltou a ser uma linha de shell que este teste nao consegue reexecutar"
    )


def test_todo_import_de_treino_esta_coberto_pelo_que_o_notebook_instala():
    """A regressão que o erro original teria evitado, por menos de um milissegundo.

    Se alguém acrescentar `import scipy` a um módulo de `ml/treino` sem pôr `scipy` no
    `requirements-treino.txt`, este teste quebra aqui — e não no Colab, três células
    depois da causa.
    """
    instaladas = distribuicoes_que_o_notebook_instala()
    faltando: list[str] = []

    for modulo in sorted(importes_de_terceiros()):
        distribuicao = DISTRIBUICAO_DE.get(modulo)
        assert distribuicao, (
            f"'{modulo}' e importado por ml/treino e nao esta em DISTRIBUICAO_DE. "
            "Declare qual pacote o instala (e acrescente-o ao requirements se for novo)."
        )
        if distribuicao.lower() not in instaladas:
            faltando.append(f"{modulo} (vem de '{distribuicao}')")

    assert not faltando, (
        "a celula de instalacao do notebook nao cobre: "
        + ", ".join(faltando)
        + ". Acrescente ao ml/requirements-treino.txt."
    )


def test_o_preprocessamento_nao_entra_editavel_no_notebook():
    """Regressão do bug do Colab: `-e` registra um `.pth` que o kernel só lê ao
    iniciar, então a instalação editável só valeria depois de reiniciar o ambiente.

    O `ml/requirements.txt` continua instalando editável de propósito — é o que faz
    uma mudança no mapa de emoji valer nos dois ambientes locais sem reinstalar. O
    notebook desfaz isso para o Colab, e é essa linha que este teste protege.
    """
    instala_normal = [
        argumentos
        for argumentos in comandos_de_instalacao()
        if "./preprocessamento" in argumentos and "-e" not in argumentos
    ]
    assert instala_normal, (
        "o notebook precisa reinstalar ./preprocessamento SEM -e depois dos "
        "requirements: no Colab a instalacao editavel so vale apos reiniciar o kernel"
    )


def test_o_clone_do_notebook_e_idempotente():
    """Regressão do bug que custou a sessão: rodar a célula duas vezes clonava de novo.

    Com `!git clone URL` seguido de `%cd emi-youtube-analytics`, a segunda execução
    clonava *de dentro* do primeiro clone — o caminho é relativo ao diretório atual —
    e o `%cd` descia para a cópia nova. A partir daí cada célula gravava numa cópia
    diferente: o treino salvou o modelo numa, a exportação ONNX foi procurá-lo na
    outra, e a segunda nem tinha `ml/modelos/` (a pasta inteira está no `.gitignore`).

    O que este teste exige é a forma que não tem esse estado: clonar só quando ainda
    não há clone, e ir sempre para o caminho ABSOLUTO de `RAIZ` — nunca para um nome
    relativo, que depende de onde o kernel está.
    """
    fonte = fonte_da_celula_de_instalacao()

    assert '(RAIZ / ".git").exists()' in fonte, (
        "a celula de instalacao precisa checar se o clone ja existe antes de clonar: "
        "rodada duas vezes, ela criava uma copia dentro da outra"
    )
    assert "pull" in fonte, "sem 'git pull' o segundo run deixa o clone desatualizado"
    assert "os.chdir(RAIZ)" in fonte, (
        "o notebook precisa entrar na RAIZ absoluta, e nao num nome relativo: era o "
        "'%cd emi-youtube-analytics' que descia para a copia aninhada"
    )
    assert "%cd" not in fonte, "'%cd' com nome relativo e exatamente o que aninhava o clone"


def test_o_notebook_verifica_o_ambiente_antes_de_usar():
    """`!pip` que falha no Colab não interrompe o notebook. Sem uma célula que importe
    tudo logo depois da instalação, o erro reaparece adiante, disfarçado."""
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    codigo = "\n".join(
        "".join(celula["source"])
        for celula in notebook["cells"]
        if celula["cell_type"] == "code"
    )
    assert "importlib.import_module" in codigo, (
        "notebook sem celula de verificacao do ambiente depois da instalacao"
    )
    for modulo in modulos_de_treino():
        assert modulo in codigo, f"a verificacao do notebook nao importa {modulo}"


# --------------------------------------------- ambiente real (sob demanda)

EXECUTA_AMBIENTE = bool(os.environ.get("TESTE_AMBIENTE"))
MOTIVO = (
    "instala o ambiente inteiro do zero (~2 GB, alguns minutos). "
    "Rode com TESTE_AMBIENTE=1 antes de mexer no notebook ou nos requirements."
)


@pytest.mark.skipif(not EXECUTA_AMBIENTE, reason=MOTIVO)
def test_ambiente_limpo_importa_todo_o_ml_treino(tmp_path):
    """Cria um venv vazio, roda os comandos do notebook e importa `ml/treino` lá.

    É o teste que reproduz o Colab: ambiente sem nada, só o que a célula de instalação
    traz. Um import que só funcionava porque a máquina de quem desenvolve já tinha o
    pacote falha aqui — que é exatamente o que aconteceu com o `asyncpg`.
    """
    ambiente = tmp_path / "venv"
    venv.create(ambiente, with_pip=True)
    python = ambiente / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    assert python.exists()

    for argumentos in comandos_de_instalacao():
        processo = subprocess.run(
            [str(python), "-m", "pip", "install", *argumentos],
            cwd=RAIZ_REPO,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert processo.returncode == 0, (
            f"falhou: pip install {' '.join(argumentos)}\n{processo.stdout[-3000:]}\n"
            f"{processo.stderr[-3000:]}"
        )

    programa = "import importlib\n" + "".join(
        f"importlib.import_module({modulo!r})\n" for modulo in modulos_de_treino()
    )
    processo = subprocess.run(
        [str(python), "-c", programa],
        cwd=RAIZ_REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert processo.returncode == 0, (
        "o ambiente que o notebook monta nao importa ml/treino:\n"
        f"{processo.stderr[-3000:]}"
    )

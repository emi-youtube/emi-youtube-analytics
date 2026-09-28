"""O notebook roda no Colab — o Colab de HOJE, com o que ele já traz instalado?

**Por que este arquivo existe.** Em 28/09 o notebook quebrou três vezes no Colab e
nenhum teste tinha acusado nada:

1. `onnx==1.17.0` não tem roda para Python 3.13, que é o Python do Colab agora. O pip
   tentou compilar e morreu — e travou a instalação inteira, inclusive para quem nem
   ia rodar a seção do ONNX;
2. o Colab traz `torchvision 0.26` compilado contra o `torch 2.11` dele. Reinstalar
   `torch==2.5.1` por cima deixou o torchvision órfão, e o `transformers` — que importa
   o torchvision sozinho quando o encontra — quebrou ao carregar o BERT com
   `operator torchvision::nms does not exist`;
3. `No module named 'ml'` na célula seguinte à instalação.

`test_notebook.py` não pegou nenhum dos três porque roda no `ml/.venv`: Windows,
Python 3.11 (onde o onnx 1.17 tem roda), sem torchvision, e sem o ramo `NO_COLAB` —
clone e instalação nem executam. `test_ambiente_colab.py` monta um venv limpo, mas
limpo é justamente o que o Colab não é: o problema 2 nasce do que JÁ ESTAVA lá.

Este teste monta um Colab sem GPU num contêiner Linux (`ml/tests/colab/`): Python
3.13, as versões de `torch`, `torchvision`, `torchaudio`, `transformers` e companhia
que o `googlecolab/backend-info` publica (`pre_instalado.txt`), e um `google.colab`
falso, cuja presença faz o notebook tomar o caminho do Colab de ponta a ponta: clone,
`pip install` dentro do kernel já rodando, cofre de credenciais, download. Dois
cenários (ver `colab/executar.py`):

- **inteiro** — "Executar tudo" do zero, com `ENSAIO_REDUZIDO=1`;
- **reinicio** — o kernel reinicia depois da instalação e a pessoa segue de onde
  parou; depois roda tudo de novo no mesmo disco.

**Não roda por padrão.** Precisa do Docker, de rede (o `torch==2.5.1` de Linux baixa
uns 3 GB de bibliotecas CUDA, como no Colab — ficam num volume de cache na segunda vez),
do banco, de uns 30 minutos e de **~10 GB livres no disco do Docker** (imagem, cache
e a camada do contêiner com o torch de CUDA). Em 28/09 o disco encheu no meio da
instalação e o Docker Desktop caiu duas vezes — confira o espaço antes:

    TESTE_COLAB=1 ml/.venv/Scripts/python.exe -m pytest ml/tests/test_notebook_colab.py

Com `RODAR_ONNX=1` a seção 7 roda também (mais uns 10 minutos de exportação em CPU).

Quando o Colab trocar de versão, atualize `pre_instalado.txt` pelo backend-info e rode
de novo antes da próxima sessão de GPU.
"""

import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from ml.config import RAIZ_REPO, carregar_env

DIRETORIO_COLAB = RAIZ_REPO / "ml" / "tests" / "colab"
IMAGEM = "emi-colab-simulado"

EXECUTA = bool(os.environ.get("TESTE_COLAB"))
MOTIVO = (
    "simula o Colab num conteiner (Docker, rede, banco, ~30 min). "
    "Rode com TESTE_COLAB=1 depois de mexer no notebook ou nos requirements."
)

pytestmark = pytest.mark.skipif(not EXECUTA, reason=MOTIVO)


def empacotar_arvore(destino: Path) -> Path:
    """A árvore de trabalho ATUAL, com mudanças não commitadas e sem o que é ignorado.

    Do git e não do disco inteiro: `ml/.venv`, `ml/modelos/` e o `.env` ficam de fora
    pelo `.gitignore`, exatamente como ficariam fora de um clone no Colab.
    """
    listagem = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=RAIZ_REPO,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    pacote = destino / "repo.tar"
    with tarfile.open(pacote, "w") as arquivo:
        for relativo in filter(None, listagem.split("\0")):
            caminho = RAIZ_REPO / relativo
            if caminho.is_file():  # rastreado mas apagado na árvore: fica de fora
                arquivo.add(caminho, arcname=relativo)
    return pacote


@pytest.fixture(scope="module")
def imagem() -> str:
    if not shutil.which("docker"):
        pytest.skip("docker nao esta instalado")
    subprocess.run(["docker", "build", "-q", "-t", IMAGEM, str(DIRETORIO_COLAB)], check=True)
    return IMAGEM


def rodar_cenario(imagem: str, cenario: str, tmp_path: Path) -> None:
    entrada = tmp_path / "entrada"
    saida = tmp_path / "saida"
    entrada.mkdir()
    saida.mkdir()
    empacotar_arvore(entrada)

    # O segredo vai pelo ambiente do processo do docker (`-e NOME` sem valor), e não na
    # linha de comando, onde apareceria na listagem de processos.
    ambiente = {**os.environ, "DATABASE_URL": carregar_env()["DATABASE_URL"]}
    repassadas = ["DATABASE_URL", "ENSAIO_REDUZIDO"] + (
        ["RODAR_ONNX"] if os.environ.get("RODAR_ONNX") else []
    )
    ambiente["ENSAIO_REDUZIDO"] = "1"

    comando = ["docker", "run", "--rm"]
    for nome in repassadas:
        comando += ["-e", nome]
    comando += [
        "-v", f"{entrada}:/entrada:ro",
        "-v", f"{saida}:/saida",
        "-v", f"{DIRETORIO_COLAB}:/harness:ro",
        # Cache entre execuções: o que o Colab baixaria de novo a cada sessão, o teste
        # baixa uma vez. Não muda o que é instalado, só de onde vem o arquivo.
        "-v", "emi-colab-pip:/root/.cache/pip",
        "-v", "emi-colab-hf:/root/.cache/huggingface",
        imagem,
        "python", "/harness/executar.py", cenario,
    ]  # fmt: skip
    processo = subprocess.run(
        comando, env=ambiente, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    assert processo.returncode == 0, (
        f"cenario '{cenario}' falhou no Colab simulado (cadernos executados em {saida}):\n"
        f"{processo.stdout[-4000:]}\n{processo.stderr[-6000:]}"
    )


def test_reiniciar_o_kernel_depois_da_instalacao_nao_quebra_em_silencio(imagem, tmp_path):
    rodar_cenario(imagem, "reinicio", tmp_path)


def test_executar_tudo_num_colab_novo_roda_ate_o_fim(imagem, tmp_path):
    rodar_cenario(imagem, "inteiro", tmp_path)

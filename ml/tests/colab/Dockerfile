# Um Colab sem GPU: a imagem que ml/tests/test_notebook_colab.py usa para executar o
# notebook de treino como o Colab o executaria. Ver pre_instalado.txt para o que entra
# e por que.
FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pre_instalado.txt /tmp/pre_instalado.txt
RUN pip install --no-cache-dir -r /tmp/pre_instalado.txt

# O `google.colab` falso: e so a presenca dele que faz o notebook tomar o caminho do
# Colab (clonar, instalar, ler o cofre, baixar). Vai para o site-packages, como o de
# verdade, e nao para o diretorio de trabalho -- senao o `sys.path` do kernel o acharia
# por um caminho que o Colab nao tem.
COPY google_colab_falso/ /tmp/google_colab_falso/
RUN cp -r /tmp/google_colab_falso/google "$(python -c 'import site; print(site.getsitepackages()[0])')/"

RUN mkdir -p /content
WORKDIR /content

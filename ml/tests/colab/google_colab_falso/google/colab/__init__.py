"""Imitação do `google.colab` para o teste que simula o Colab.

Só o que o notebook de treino usa: `userdata.get` (o cofre de credenciais) e
`files.download`. Existir é o que importa — o notebook decide que está no Colab
por `find_spec("google.colab")`.
"""

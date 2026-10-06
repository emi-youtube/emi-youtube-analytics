"""Quem pode ALTERAR o quê dentro da empresa (ADR-013). Complementa `escopo`.

`escopo.da_empresa` responde "enxerga?" (404 para outra empresa); este módulo
responde "pode mexer?" (403 dentro da própria empresa). A ordem é sempre essa:
primeiro o escopo, depois o papel — um 403 para recurso de outra empresa confirmaria
que ele existe.

Chamado como `permissao.pode_alterar_modelo(...)`, e não importado por nome, para o
teste de mutação (`tests/test_privilegios.py`) conseguir trocá-lo por "sempre pode".
"""

from app.models.modelo_analise import ModeloAnalise
from app.models.usuario import Usuario
from app.services.auth import PAPEL_DONO

SO_AUTOR_OU_DONO = "Só o autor do modelo ou o dono da empresa pode fazer isso."


def eh_dono(usuario: Usuario) -> bool:
    return usuario.papel_empresa == PAPEL_DONO


def pode_alterar_modelo(usuario: Usuario, modelo: ModeloAnalise) -> bool:
    """Editar ou apagar: o autor, ou qualquer dono da empresa.

    Supõe que o modelo já passou pelo escopo (é da empresa de `usuario`). Executar,
    ler resultado e criar modelo continuam livres para todo membro.
    """
    return eh_dono(usuario) or modelo.id_usuario == usuario.id_usuario

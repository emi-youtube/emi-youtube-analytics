"""Importa todos os models para que `Base.metadata` fique completo (Alembic autogenerate)."""

from app.models.aceite_termos import AceiteTermos
from app.models.analise_sentimento import AnaliseSentimento
from app.models.cadastro_pendente import CadastroPendente
from app.models.comentario import Comentario
from app.models.comentario_tema import ComentarioTema
from app.models.convite import Convite
from app.models.empresa import Empresa
from app.models.execucao import Execucao
from app.models.exemplo_treinamento import ExemploTreinamento
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.tentativa_login import TentativaLogin
from app.models.token_atualizacao import TokenAtualizacao
from app.models.token_redefinicao_senha import TokenRedefinicaoSenha
from app.models.usuario import Usuario
from app.models.versao_modelo import VersaoModelo
from app.models.video import Video

__all__ = [
    "AceiteTermos",
    "AnaliseSentimento",
    "CadastroPendente",
    "Comentario",
    "ComentarioTema",
    "Convite",
    "Empresa",
    "Execucao",
    "ExemploTreinamento",
    "Job",
    "JobDlq",
    "ModeloAnalise",
    "Tema",
    "TentativaLogin",
    "TokenAtualizacao",
    "TokenRedefinicaoSenha",
    "Usuario",
    "VersaoModelo",
    "Video",
]

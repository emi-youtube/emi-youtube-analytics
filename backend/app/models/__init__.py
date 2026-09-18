"""Importa todos os models para que `Base.metadata` fique completo (Alembic autogenerate)."""

from app.models.analise_sentimento import AnaliseSentimento
from app.models.comentario import Comentario
from app.models.comentario_tema import ComentarioTema
from app.models.execucao import Execucao
from app.models.exemplo_treinamento import ExemploTreinamento
from app.models.job import Job
from app.models.job_dlq import JobDlq
from app.models.modelo_analise import ModeloAnalise
from app.models.tema import Tema
from app.models.tentativa_login import TentativaLogin
from app.models.token_atualizacao import TokenAtualizacao
from app.models.usuario import Usuario
from app.models.versao_modelo import VersaoModelo
from app.models.video import Video

__all__ = [
    "AnaliseSentimento",
    "Comentario",
    "ComentarioTema",
    "Execucao",
    "ExemploTreinamento",
    "Job",
    "JobDlq",
    "ModeloAnalise",
    "Tema",
    "TentativaLogin",
    "TokenAtualizacao",
    "Usuario",
    "VersaoModelo",
    "Video",
]

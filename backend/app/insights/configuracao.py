"""Os cortes do motor, num lugar só e configuráveis por afirmação.

**Por que configurável por afirmação, e não um número global.** As regras não
custam o mesmo se erradas. Dizer "o tema X é o mais criticado" com base em 5
comentários é uma afirmação sobre um tema, e o leitor confere olhando o tema.
Dizer "a rejeição subiu entre as coletas" com base em 5 comentários é uma
afirmação sobre a campanha inteira, e o leitor muda a campanha por causa dela.
O segundo erro é mais caro, e por isso pode exigir amostra maior que o primeiro.

**Os padrões são cortes de projeto, não constantes universais.** O escopo é de
500 a 5.000 comentários por execução (CLAUDE.md Seção 1) e os valores abaixo
foram escolhidos para essa faixa: em 500 comentários, exigir 30 por tema deixa
passar os poucos temas grandes e barra a cauda; em 5.000, não atrapalha nada.
Quem mudar o escopo mexe aqui, não no meio das regras.
"""

from __future__ import annotations

from dataclasses import dataclass

# 1,96 = 95% de confiança numa normal. É o valor que a Seção de metodologia do
# TC2 já usa para a amostragem de Cochran; repetir o mesmo nível de confiança em
# lugares diferentes do trabalho evita ter que justificar dois.
Z_95 = 1.96


@dataclass(frozen=True, slots=True)
class ConfiguracaoInsights:
    """Cortes de amostra e de efeito. Tudo que o motor decide passa por aqui.

    Imutável de propósito: a configuração é lida em vários pontos de uma mesma
    análise, e uma que mudasse no meio produziria um conjunto de fatos que não
    corresponde a configuração nenhuma.
    """

    # --- amostra mínima por afirmação ---
    #
    # Abaixo destes números a regra simplesmente não fala. Não existe "falar com
    # ressalva": um insight com ressalva na tela é lido como insight.
    minimo_tema: int = 30
    """Comentários no tema, para ele poder ser apontado como o mais criticado ou
    o mais bem recebido."""

    minimo_video: int = 30
    """Comentários no vídeo, para ele poder ser apontado como muito negativo."""

    minimo_execucao: int = 100
    """Comentários na execução inteira, para qualquer fato de execução sair.
    Uma execução de 12 comentários não tem tema mais criticado — tem 12
    comentários."""

    minimo_variacao: int = 100
    """Comentários em CADA uma das duas execuções comparadas. O corte é maior
    que o de tema porque o erro aqui se propaga para a leitura da campanha
    inteira."""

    minimo_video_entre_coletas: int = 30
    """Comentários do mesmo vídeo em CADA coleta, para comparar a evolução
    dele."""

    # --- tamanho de efeito ---

    multiplo_video_negativo: float = 2.0
    """Quantas vezes a fração negativa da execução o vídeo precisa alcançar para
    virar fato. 2,0 é o que o enunciado da regra pede: "o dobro da média"."""

    fracao_concentracao: float = 0.6
    """Que parcela das críticas os temas apontados precisam somar para que valha
    dizer que a crítica está concentrada."""

    maxima_fracao_de_temas: float = 0.5
    """E em no máximo que parcela dos temas. Sem este segundo corte, "8 de 10
    temas concentram 60% das críticas" sairia como concentração — quando é o
    contrário, é dispersão."""

    z_confianca: float = Z_95
    """Multiplicador da margem de incerteza das comparações entre execuções."""

    def __post_init__(self) -> None:
        if self.multiplo_video_negativo <= 1.0:
            raise ValueError(
                "multiplo_video_negativo <= 1 apontaria como 'muito negativo' "
                "qualquer video na media ou abaixo dela"
            )
        if not 0.0 < self.fracao_concentracao <= 1.0:
            raise ValueError("fracao_concentracao precisa estar em (0, 1]")
        if not 0.0 < self.maxima_fracao_de_temas <= 1.0:
            raise ValueError("maxima_fracao_de_temas precisa estar em (0, 1]")
        if self.z_confianca <= 0:
            raise ValueError("z_confianca precisa ser positivo")


PADRAO = ConfiguracaoInsights()
"""A configuração do projeto. Quem quiser outra passa uma instância própria —
nenhuma função do motor lê esta constante por conta própria, ela é só o valor
padrão dos argumentos."""

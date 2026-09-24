"""Testes do motor de insights — dados sintéticos, nenhum banco.

O motor é feito de funções puras justamente para que estes testes existam: cada
caso abaixo é um cenário montado à mão, incluindo os que o mundo real produz com
frequência e que são exatamente onde uma regra de insight erra — tema pequeno
demais, variação que a amostragem explica, modelo com uma coleta só.

**O que se testa aqui é o SILÊNCIO tanto quanto a fala.** Um motor que sempre
acha algo é pior que inútil: a PME age sobre o que ele diz. Metade dos testes
abaixo verifica que uma regra NÃO produziu fato.
"""

from datetime import UTC, datetime

import pytest

from app.insights import (
    AgregadosExecucao,
    Amostra,
    ConfiguracaoInsights,
    Distribuicao,
    TemaAgregado,
    TipoFato,
    VideoAgregado,
    casar_temas,
    concentracao_das_criticas,
    evolucao_dos_videos,
    fatos_da_campanha,
    fatos_da_execucao,
    jaccard,
    tema_mais_criticado,
    tema_melhor_recebido,
    variacao_de_sentimento,
    videos_muito_negativos,
)
from app.insights.estatistica import Comparacao, comparar_proporcoes
from app.insights.frases import MODELOS, numero
from app.insights.texto import normalizar_palavra_chave

# ---------------------------------------------------------------------------
# Construtores de cenário
# ---------------------------------------------------------------------------


def tema(
    id_tema: int,
    rotulo: str,
    positivo: int,
    neutro: int,
    negativo: int,
    palavras: tuple[str, ...] = (),
) -> TemaAgregado:
    return TemaAgregado(
        id_tema=id_tema,
        rotulo_tema=rotulo,
        distribuicao=Distribuicao(positivo=positivo, neutro=neutro, negativo=negativo),
        palavras_chave=palavras,
    )


def video(
    id_video: int,
    youtube_video_id: str,
    titulo: str,
    positivo: int,
    neutro: int,
    negativo: int,
) -> VideoAgregado:
    return VideoAgregado(
        id_video=id_video,
        youtube_video_id=youtube_video_id,
        titulo=titulo,
        distribuicao=Distribuicao(positivo=positivo, neutro=neutro, negativo=negativo),
    )


def execucao(
    id_execucao: int,
    positivo: int,
    neutro: int,
    negativo: int,
    *,
    id_modelo: int = 7,
    temas: tuple[TemaAgregado, ...] = (),
    videos: tuple[VideoAgregado, ...] = (),
    dia: int = 1,
) -> AgregadosExecucao:
    return AgregadosExecucao(
        id_execucao=id_execucao,
        id_modelo=id_modelo,
        distribuicao=Distribuicao(positivo=positivo, neutro=neutro, negativo=negativo),
        temas=temas,
        videos=videos,
        concluido_em=datetime(2026, 9, dia, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Distribuicao
# ---------------------------------------------------------------------------


def test_distribuicao_vazia_nao_divide_por_zero():
    """Tema sem comentário nenhum é indeterminado, não "0% negativo". Quem impede
    que vire afirmação é a amostra mínima; aqui só não pode estourar."""
    vazia = Distribuicao()

    assert vazia.total == 0
    assert vazia.fracao_negativa == 0.0
    assert vazia.fracao_positiva == 0.0


def test_contagem_negativa_e_erro():
    with pytest.raises(ValueError, match="negativa"):
        Distribuicao(positivo=-1)


def test_fracoes_somam_um():
    distribuicao = Distribuicao(positivo=50, neutro=30, negativo=20)

    soma = distribuicao.fracao_positiva + distribuicao.fracao_neutra + distribuicao.fracao_negativa
    assert soma == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Amostra
# ---------------------------------------------------------------------------


def test_amostra_sabe_se_e_suficiente():
    assert Amostra(tamanho=30, minimo_exigido=30).suficiente
    assert not Amostra(tamanho=29, minimo_exigido=30).suficiente


# ---------------------------------------------------------------------------
# Casamento de temas: por palavra-chave, NUNCA por rótulo
# ---------------------------------------------------------------------------


def test_normalizacao_ignora_caixa_e_acento():
    assert normalizar_palavra_chave("  Preço ") == "preco"
    assert normalizar_palavra_chave("ATENDIMENTO") == "atendimento"
    assert normalizar_palavra_chave("   ") == ""


def test_jaccard_de_conjunto_vazio_e_zero():
    """Não saber as palavras-chave de nenhum dos dois não é evidência de que são
    o mesmo assunto — é ausência de evidência. Um worker de tópicos que não
    gravou `palavras_chave` tem que resultar em nenhum casamento, não em todos."""
    assert jaccard(frozenset(), frozenset()) == 0.0
    assert jaccard(frozenset({"a"}), frozenset()) == 0.0


def test_temas_casam_por_palavra_chave_mesmo_com_rotulos_diferentes():
    """O caso que motiva o módulo: LDA deu nomes diferentes ao mesmo assunto."""
    antes = (tema(1, "atendimento", 10, 10, 10, ("atendimento", "suporte", "demora")),)
    depois = (tema(99, "suporte ao cliente", 10, 10, 10, ("suporte", "atendimento", "espera")),)

    pares = casar_temas(antes, depois)

    assert len(pares) == 1
    assert pares[0].antes.id_tema == 1
    assert pares[0].depois.id_tema == 99


def test_rotulo_identico_nao_casa_sem_palavra_chave_em_comum():
    """O contrapositivo, e é ele que prova que o rótulo não está sendo usado."""
    antes = (tema(1, "qualidade", 10, 10, 10, ("entrega", "prazo")),)
    depois = (tema(2, "qualidade", 10, 10, 10, ("preco", "desconto")),)

    assert casar_temas(antes, depois) == []


def test_casamento_e_um_para_um():
    """Um tema genérico não pode casar com dois específicos e aparecer duas vezes.

    Os dois candidatos passam do limiar (2 de 3 palavras em comum, Jaccard 0,67)
    e empatam; vence o de menor `id_tema`, para que a saída não dependa da ordem
    de iteração. O outro é descartado, não duplicado.
    """
    antes = (tema(1, "geral", 10, 10, 10, ("preco", "entrega")),)
    depois = (
        tema(10, "preco e entrega", 10, 10, 10, ("preco", "entrega", "valor")),
        tema(11, "entrega e preco", 10, 10, 10, ("preco", "entrega", "prazo")),
    )

    pares = casar_temas(antes, depois)

    assert len(pares) == 1
    assert pares[0].depois.id_tema == 10


def test_casamento_nao_depende_da_ordem_de_entrada():
    antes = (
        tema(1, "a", 10, 10, 10, ("preco", "valor")),
        tema(2, "b", 10, 10, 10, ("entrega", "prazo")),
    )
    depois = (
        tema(10, "x", 10, 10, 10, ("entrega", "prazo")),
        tema(11, "y", 10, 10, 10, ("preco", "valor")),
    )

    direto = [(p.antes.id_tema, p.depois.id_tema) for p in casar_temas(antes, depois)]
    invertido = [
        (p.antes.id_tema, p.depois.id_tema)
        for p in casar_temas(tuple(reversed(antes)), tuple(reversed(depois)))
    ]

    assert sorted(direto) == sorted(invertido) == [(1, 11), (2, 10)]


# ---------------------------------------------------------------------------
# Execução: tema mais criticado / melhor recebido
# ---------------------------------------------------------------------------


def test_tema_mais_criticado_usa_fracao_e_nao_contagem():
    """O tema com MAIS negativos costuma ser só o tema maior. O que interessa é
    onde a proporção destoa — aqui, um tema pequeno com 80% de rejeição perde
    para nenhum e ganha do tema grande com 100 negativos em 1.000."""
    agregados = execucao(
        1,
        500,
        200,
        300,
        temas=(
            tema(1, "grande", 800, 100, 100, ("a",)),
            tema(2, "destoa", 10, 10, 80, ("b",)),
        ),
    )

    fato = tema_mais_criticado(agregados)

    assert fato is not None
    assert fato.valores["rotulo_tema"] == "destoa"
    assert fato.valores["percentual_negativo"] == 80.0
    assert fato.origem.id_tema == 2


def test_tema_pequeno_demais_nao_vira_fato():
    """CASO-LIMITE. Um tema com 5 comentários, 4 deles negativos, é 80% de
    rejeição — e não é nada. Sem este corte ele venceria toda execução."""
    agregados = execucao(
        1,
        500,
        200,
        300,
        temas=(
            tema(1, "minusculo", 1, 0, 4, ("a",)),
            tema(2, "de verdade", 40, 10, 50, ("b",)),
        ),
    )

    fato = tema_mais_criticado(agregados)

    assert fato is not None
    assert fato.valores["rotulo_tema"] == "de verdade"


def test_sem_nenhum_tema_com_amostra_nao_ha_fato_de_tema():
    agregados = execucao(1, 500, 200, 300, temas=(tema(1, "minusculo", 1, 0, 4, ("a",)),))

    assert tema_mais_criticado(agregados) is None
    assert tema_melhor_recebido(agregados) is None


def test_amostra_minima_de_tema_e_configuravel():
    """O corte é do projeto, não do código: quem muda o escopo muda o número."""
    agregados = execucao(1, 500, 200, 300, temas=(tema(1, "pequeno", 1, 0, 4, ("a",)),))
    frouxa = ConfiguracaoInsights(minimo_tema=5, minimo_execucao=1)

    assert tema_mais_criticado(agregados) is None
    fato = tema_mais_criticado(agregados, frouxa)
    assert fato is not None
    assert fato.amostra.minimo_exigido == 5


def test_empate_de_fracao_e_desfeito_pelo_id():
    """Duas execuções com os mesmos números têm que produzir o mesmo fato — sem
    desempate a saída dependeria da ordem em que a consulta devolveu as linhas."""
    temas = (
        tema(7, "sete", 10, 10, 30, ("a",)),
        tema(3, "tres", 10, 10, 30, ("b",)),
    )
    agregados = execucao(1, 500, 200, 300, temas=temas)

    assert tema_mais_criticado(agregados).origem.id_tema == 3
    invertido = execucao(1, 500, 200, 300, temas=tuple(reversed(temas)))
    assert tema_mais_criticado(invertido).origem.id_tema == 3


def test_tema_melhor_recebido_escolhe_pela_fracao_positiva():
    agregados = execucao(
        1,
        500,
        200,
        300,
        temas=(
            tema(1, "morno", 50, 40, 10, ("a",)),
            tema(2, "querido", 90, 5, 5, ("b",)),
        ),
    )

    fato = tema_melhor_recebido(agregados)

    assert fato.valores["rotulo_tema"] == "querido"
    assert fato.tipo is TipoFato.TEMA_MELHOR_RECEBIDO


# ---------------------------------------------------------------------------
# Execução: vídeo muito negativo
# ---------------------------------------------------------------------------


def test_video_no_dobro_exato_da_media_entra():
    """O enunciado é "2x a média OU MAIS", então o dobro exato é fato."""
    agregados = execucao(
        1,
        500,
        200,
        300,  # 30% negativo na execucao
        videos=(video(1, "abc", "No dobro", 20, 20, 60),),  # 60%
    )

    fatos = videos_muito_negativos(agregados)

    assert len(fatos) == 1
    assert fatos[0].valores["multiplo_da_media"] == 2.0


def test_video_logo_abaixo_do_dobro_fica_de_fora():
    agregados = execucao(
        1,
        500,
        200,
        300,  # 30%
        videos=(video(1, "abc", "Quase", 21, 20, 59),),  # 59% < 60%
    )

    assert videos_muito_negativos(agregados) == []


def test_video_pequeno_demais_nao_vira_fato():
    """CASO-LIMITE: 100% de rejeição em 4 comentários não é sinal de nada."""
    agregados = execucao(1, 500, 200, 300, videos=(video(1, "abc", "Minusculo", 0, 0, 4),))

    assert videos_muito_negativos(agregados) == []


def test_execucao_sem_negativo_nao_produz_video_muito_negativo():
    """Com a marca em zero, um único negativo seria "infinitas vezes a média"."""
    agregados = execucao(1, 800, 200, 0, videos=(video(1, "abc", "Qualquer", 50, 10, 40),))

    assert videos_muito_negativos(agregados) == []


def test_varios_videos_destoantes_saem_todos_do_pior_para_o_melhor():
    """Três vídeos destoando é um padrão; mostrar só o pior o esconderia."""
    agregados = execucao(
        1,
        500,
        200,
        300,
        videos=(
            video(1, "aaa", "Ruim", 20, 20, 60),
            video(2, "bbb", "Pior", 10, 10, 80),
            video(3, "ccc", "Normal", 60, 20, 20),
        ),
    )

    fatos = videos_muito_negativos(agregados)

    assert [f.valores["titulo"] for f in fatos] == ["Pior", "Ruim"]


# ---------------------------------------------------------------------------
# Execução: concentração das críticas
# ---------------------------------------------------------------------------


def test_concentracao_aponta_os_poucos_temas_que_somam_a_maioria_das_criticas():
    agregados = execucao(
        1,
        500,
        200,
        300,
        temas=(
            tema(1, "entrega", 10, 10, 70, ("a",)),
            tema(2, "preco", 10, 10, 20, ("b",)),
            tema(3, "embalagem", 30, 10, 5, ("c",)),
            tema(4, "cor", 30, 10, 5, ("d",)),
        ),
    )

    fato = concentracao_das_criticas(agregados)

    assert fato is not None
    assert fato.valores["temas_apontados"] == 1
    assert fato.valores["rotulos"] == "entrega"
    assert fato.valores["percentual_das_criticas"] == 70.0


def test_critica_espalhada_nao_e_concentracao():
    """CASO-LIMITE do segundo corte: 3 de 4 temas somando 60% das críticas é
    dispersão. Sem `maxima_fracao_de_temas` isso sairia como concentração."""
    agregados = execucao(
        1,
        500,
        200,
        300,
        temas=(
            tema(1, "a", 20, 10, 25, ("a",)),
            tema(2, "b", 20, 10, 25, ("b",)),
            tema(3, "c", 20, 10, 25, ("c",)),
            tema(4, "d", 20, 10, 25, ("d",)),
        ),
    )

    assert concentracao_das_criticas(agregados) is None


def test_sem_negativo_em_tema_nenhum_nao_ha_concentracao():
    agregados = execucao(1, 900, 100, 0, temas=(tema(1, "tudo bem", 90, 10, 0, ("a",)),))

    assert concentracao_das_criticas(agregados) is None


# ---------------------------------------------------------------------------
# Execução: a lista inteira
# ---------------------------------------------------------------------------


def test_execucao_pequena_demais_nao_produz_fato_nenhum():
    """CASO-LIMITE. 12 comentários não têm "tema mais criticado" — têm 12
    comentários. O corte vale mesmo que um tema isolado passasse no corte dele."""
    agregados = execucao(
        1,
        5,
        3,
        4,
        temas=(tema(1, "grande para o tamanho", 5, 3, 4, ("a",)),),
    )

    assert fatos_da_execucao(agregados, ConfiguracaoInsights(minimo_tema=1)) == []


def test_todo_fato_sai_com_frase_amostra_e_origem():
    """O contrato do pacote: nada de `texto` vazio nem de amostra sem lastro."""
    agregados = execucao(
        1,
        500,
        200,
        300,
        temas=(tema(1, "entrega", 10, 10, 80, ("a",)), tema(2, "preco", 80, 10, 10, ("b",))),
        videos=(video(1, "abc", "Comercial", 10, 10, 80),),
    )

    fatos = fatos_da_execucao(agregados)

    assert fatos
    for fato in fatos:
        assert fato.texto.strip(), f"{fato.tipo} saiu sem frase"
        assert fato.amostra.suficiente, f"{fato.tipo} saiu com amostra insuficiente"
        assert fato.origem.id_execucoes == (1,)
        assert isinstance(fato.tipo, TipoFato)


def test_a_critica_vem_antes_do_elogio_na_ordem_da_tela():
    agregados = execucao(
        1,
        500,
        200,
        300,
        temas=(tema(1, "entrega", 10, 10, 80, ("a",)), tema(2, "preco", 80, 10, 10, ("b",))),
    )

    tipos = [fato.tipo for fato in fatos_da_execucao(agregados)]

    assert tipos.index(TipoFato.TEMA_MAIS_CRITICADO) < tipos.index(TipoFato.TEMA_MELHOR_RECEBIDO)


# ---------------------------------------------------------------------------
# Campanha: margem de incerteza
# ---------------------------------------------------------------------------


def test_diferenca_exatamente_igual_a_margem_nao_e_significativa():
    """CASO-LIMITE do critério. Estritamente maior, para o limite ter resposta."""
    comparacao = Comparacao(
        proporcao_antes=0.0,
        proporcao_depois=0.1,
        tamanho_antes=10,
        tamanho_depois=10,
        margem=0.1,
    )

    assert not comparacao.significativa


def test_margem_encolhe_quando_a_amostra_cresce():
    """É o que dá sentido ao critério: a mesma diferença vira fato com amostra
    maior. Se não encolhesse, a margem seria um corte fixo disfarçado."""
    pequena = comparar_proporcoes(30, 100, 40, 100, z=1.96)
    grande = comparar_proporcoes(300, 1000, 400, 1000, z=1.96)

    assert pequena.diferenca == pytest.approx(grande.diferenca)
    assert grande.margem < pequena.margem


def test_variacao_dentro_da_margem_nao_vira_fato():
    """CASO-LIMITE central da campanha: 30% -> 33% em 200 comentários é ruído de
    amostragem. Um motor que reportasse isso diria "subiu" e "caiu"
    alternadamente para sempre."""
    campanha = (
        execucao(1, 100, 40, 60, dia=1),  # 30% de 200
        execucao(2, 94, 40, 66, dia=2),  # 33% de 200
    )

    assert variacao_de_sentimento(campanha) == []


def test_variacao_acima_da_margem_vira_fato_com_a_direcao_certa():
    campanha = (
        execucao(1, 600, 200, 200, dia=1),  # 20% de 1000
        execucao(2, 450, 200, 350, dia=2),  # 35% de 1000
    )

    fatos = variacao_de_sentimento(campanha)

    assert len(fatos) == 1
    fato = fatos[0]
    assert fato.tipo is TipoFato.VARIACAO_DE_SENTIMENTO
    assert fato.valores["percentual_negativo_antes"] == 20.0
    assert fato.valores["percentual_negativo_depois"] == 35.0
    assert fato.valores["diferenca_em_pontos"] == 15.0
    assert "subiu" in fato.texto
    assert fato.origem.id_execucoes == (1, 2)


def test_queda_de_rejeicao_e_descrita_como_queda():
    campanha = (
        execucao(1, 450, 200, 350, dia=1),
        execucao(2, 600, 200, 200, dia=2),
    )

    fato = variacao_de_sentimento(campanha)[0]

    assert fato.valores["diferenca_em_pontos"] == -15.0
    assert "caiu" in fato.texto


def test_coleta_pequena_demais_nao_entra_na_comparacao():
    """CASO-LIMITE: comparar 1.000 comentários com 40 não é comparar campanhas."""
    campanha = (
        execucao(1, 600, 200, 200, dia=1),
        execucao(2, 10, 10, 20, dia=2),  # 40 comentarios
    )

    assert variacao_de_sentimento(campanha) == []


def test_a_amostra_do_fato_e_a_menor_das_duas_coletas():
    campanha = (
        execucao(1, 600, 200, 200, dia=1),  # 1000
        execucao(2, 180, 80, 140, dia=2),  # 400
    )

    fato = variacao_de_sentimento(campanha)[0]

    assert fato.amostra.tamanho == 400


def test_a_ordem_cronologica_define_antes_e_depois():
    """Entregue fora de ordem, o fato tem que sair igual — senão o sinal da
    diferença (subiu/caiu) se inverte conforme a consulta ordenou as linhas."""
    mais_nova = execucao(2, 450, 200, 350, dia=9)
    mais_velha = execucao(1, 600, 200, 200, dia=1)

    fora_de_ordem = variacao_de_sentimento((mais_nova, mais_velha))[0]
    em_ordem = variacao_de_sentimento((mais_velha, mais_nova))[0]

    assert fora_de_ordem.valores == em_ordem.valores
    assert fora_de_ordem.valores["diferenca_em_pontos"] == 15.0


# ---------------------------------------------------------------------------
# Campanha: evolução de um mesmo vídeo
# ---------------------------------------------------------------------------


def test_video_e_casado_entre_coletas_pelo_youtube_video_id():
    """`id_video` nasce de novo a cada coleta (VIDEOS tem `id_execucao`): casar
    por ele não casaria nada. Aqui os ids locais são diferentes de propósito."""
    campanha = (
        execucao(1, 600, 200, 200, dia=1, videos=(video(11, "abc", "Comercial", 300, 100, 100),)),
        execucao(2, 450, 200, 350, dia=2, videos=(video(99, "abc", "Comercial", 150, 100, 250),)),
    )

    fatos = evolucao_dos_videos(campanha)

    assert len(fatos) == 1
    assert fatos[0].origem.youtube_video_id == "abc"
    assert fatos[0].valores["percentual_negativo_antes"] == 20.0
    assert fatos[0].valores["percentual_negativo_depois"] == 50.0
    assert "piorou" in fatos[0].texto


def test_video_que_so_existe_numa_coleta_e_ignorado():
    campanha = (
        execucao(1, 600, 200, 200, dia=1, videos=(video(11, "abc", "Antigo", 300, 100, 100),)),
        execucao(2, 450, 200, 350, dia=2, videos=(video(99, "xyz", "Novo", 150, 100, 250),)),
    )

    assert evolucao_dos_videos(campanha) == []


def test_video_com_poucos_comentarios_numa_das_coletas_e_ignorado():
    campanha = (
        execucao(1, 600, 200, 200, dia=1, videos=(video(11, "abc", "Comercial", 2, 1, 2),)),
        execucao(2, 450, 200, 350, dia=2, videos=(video(99, "abc", "Comercial", 150, 100, 250),)),
    )

    assert evolucao_dos_videos(campanha) == []


def test_o_titulo_usado_e_o_da_coleta_mais_recente():
    """Vídeo renomeado no YouTube aparece com o nome que tem hoje."""
    campanha = (
        execucao(1, 600, 200, 200, dia=1, videos=(video(11, "abc", "Nome antigo", 300, 100, 100),)),
        execucao(2, 450, 200, 350, dia=2, videos=(video(99, "abc", "Nome novo", 150, 100, 250),)),
    )

    assert evolucao_dos_videos(campanha)[0].valores["titulo"] == "Nome novo"


# ---------------------------------------------------------------------------
# Campanha: a lista inteira
# ---------------------------------------------------------------------------


def test_modelo_com_uma_execucao_so_nao_tem_fato_de_campanha():
    """CASO-LIMITE pedido: campanha de uma coleta não tem evolução. Lista vazia,
    e não erro — é o estado normal de todo modelo recém-criado."""
    assert fatos_da_campanha((execucao(1, 600, 200, 200),)) == []


def test_campanha_sem_execucao_nenhuma_e_entrada_valida():
    assert fatos_da_campanha(()) == []


def test_misturar_modelos_diferentes_e_erro():
    """Comparar campanhas diferentes produziria uma frase correta sobre nada, e o
    erro seria invisível na tela."""
    campanha = (
        execucao(1, 600, 200, 200, id_modelo=7, dia=1),
        execucao(2, 450, 200, 350, id_modelo=8, dia=2),
    )

    with pytest.raises(ValueError, match="modelos diferentes"):
        fatos_da_campanha(campanha)


def test_fatos_da_campanha_junta_variacao_e_evolucao():
    campanha = (
        execucao(1, 600, 200, 200, dia=1, videos=(video(11, "abc", "Comercial", 300, 100, 100),)),
        execucao(2, 450, 200, 350, dia=2, videos=(video(99, "abc", "Comercial", 150, 100, 250),)),
    )

    tipos = {fato.tipo for fato in fatos_da_campanha(campanha)}

    assert tipos == {TipoFato.VARIACAO_DE_SENTIMENTO, TipoFato.EVOLUCAO_DO_VIDEO}


# ---------------------------------------------------------------------------
# Frases
# ---------------------------------------------------------------------------


def test_todo_tipo_de_fato_tem_modelo_de_frase():
    """Um `TipoFato` sem modelo viraria card em branco na tela."""
    assert set(MODELOS) == set(TipoFato)


def test_numero_sai_em_portugues():
    assert numero(12.5) == "12,5"
    assert numero(7.0) == "7"
    assert numero(0.0) == "0"


def test_a_frase_mostra_o_mesmo_numero_que_o_fato_carrega():
    """Formatar nos dois lados é como o `valores` e o `texto` divergem."""
    agregados = execucao(1, 500, 200, 300, temas=(tema(1, "entrega", 10, 10, 80, ("a",)),))

    fato = tema_mais_criticado(agregados)

    assert f"{numero(float(fato.valores['percentual_negativo']))}%" in fato.texto


def test_a_frase_nao_afirma_causa():
    """O motor mede comentário classificado; por que o comentário é negativo ele
    não sabe. "Os clientes estão insatisfeitos" seria conclusão de pesquisa."""
    agregados = execucao(
        1,
        500,
        200,
        300,
        temas=(tema(1, "entrega", 10, 10, 80, ("a",)), tema(2, "preco", 80, 10, 10, ("b",))),
        videos=(video(1, "abc", "Comercial", 10, 10, 80),),
    )

    for fato in fatos_da_execucao(agregados):
        minusculo = fato.texto.lower()
        for proibida in ("porque", "insatisfeit", "devido", "por causa"):
            assert proibida not in minusculo, f"{fato.tipo} afirma causa: {fato.texto}"

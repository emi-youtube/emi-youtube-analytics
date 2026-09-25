/**
 * Contrato de `GET /api/v1/execucoes/{id}/resultado` (tela Resultados,
 * design/Dashboard.png) e de `GET /api/v1/execucoes/resultados` (lista).
 *
 * Ver `dominio.models.ts` para as linhas de tabela reaproveitadas aqui.
 */

import {
  AnaliseSentimento,
  Comentario,
  DistribuicaoSentimento,
  Tema,
  Video,
  VersaoModelo,
} from './dominio.models';

/** Recorte de VIDEOS que o comentário carrega junto, para não repetir a linha inteira. */
export interface VideoResumido {
  id_video: number;
  youtube_video_id: string;
  titulo: string;
}

/** Um tema do comentário: TEMAS.rotulo_tema + COMENTARIO_TEMA.peso. */
export interface TemaDoComentario {
  id_tema: number;
  rotulo_tema: string;
  peso: number;
}

/**
 * Comentário com tudo que a tela precisa mostrar dele.
 *
 * Aninhado de propósito: cada parte é uma linha de tabela identificável, então
 * o backend monta isto com joins diretos e ninguém precisa adivinhar de onde
 * saiu cada campo.
 */
export interface ComentarioAnalisado {
  comentario: Comentario;
  analise: AnaliseSentimento;
  video: VideoResumido;
  /** De COMENTARIO_TEMA, do maior peso para o menor. */
  temas: TemaDoComentario[];
}

/** Linha de VIDEOS + as contagens daquele vídeo. */
export interface VideoComSentimento {
  video: Video;
  distribuicao: DistribuicaoSentimento;
}

/** Linha de TEMAS + as contagens daquele tema. */
export interface TemaComSentimento {
  tema: Tema;
  distribuicao: DistribuicaoSentimento;
  /**
   * O comentário que fala pelo tema — escolhido LOCALMENTE pelo servidor: o de
   * maior peso em `COMENTARIO_TEMA`, descartando os curtos demais (o de maior
   * peso puro costuma ser o mais curto, e "preço alto" não mostra nada).
   *
   * É extrativo: um comentário real, sem serviço externo e sem risco de
   * invenção (CLAUDE.md Seção 11, camada 2).
   *
   * `null` quando nenhum comentário passou do limiar de peso daquele tema.
   */
  comentario_representativo: ComentarioAnalisado | null;
}

/** Somas de VIDEOS da execução. */
export interface AlcanceExecucao {
  visualizacoes: number;
  curtidas: number;
  comentarios: number;
  /** comentarios / (visualizacoes / 1000). */
  comentarios_por_mil_views: number;
}

/**
 * Destaque textual do card "O que merece atenção".
 *
 * Vem pronto do servidor, e não montado na tela, porque a regra de qual tema
 * merece atenção é da análise — se mudar, muda em um lugar só.
 *
 * @deprecated SUBSTITUÍDO por `insights: FatoInsight[]`. Continua no contrato
 * só enquanto `resultado.html` e o mock não migram — ver a nota em
 * `FatoInsight`. Não use em tela nova.
 */
export interface PontoDeAtencao {
  id_tema: number;
  rotulo_tema: string;
  texto: string;
}

// ---------------------------------------------------------------------------
// Insights — fatos, não frases
// ---------------------------------------------------------------------------

/**
 * O que o motor de insights sabe afirmar (`backend/app/insights/fatos.py`).
 *
 * União de literais e não `string`: a tela decide ícone, cor e destino do link
 * a partir do tipo, e um `switch` exaustivo sobre união fecha no compilador.
 * Com `string` um tipo novo do backend passaria batido e cairia no `default`.
 */
export type TipoFato =
  | 'tema_mais_criticado'
  | 'tema_melhor_recebido'
  | 'video_muito_negativo'
  | 'concentracao_das_criticas'
  | 'variacao_de_sentimento'
  | 'evolucao_do_video';

/** Valor que cabe em `FatoInsight.valores` — o que o JSON do backend carrega. */
export type ValorFato = string | number | boolean | null;

/**
 * Quantos comentários sustentam a afirmação, e quantos eram exigidos.
 *
 * Os dois juntos porque o segundo torna o primeiro interpretável: "42
 * comentários" não diz nada, "42 de um mínimo de 30" diz que a regra foi
 * aplicada e passou. Serve de nota de rodapé no card.
 */
export interface AmostraInsight {
  tamanho: number;
  minimo_exigido: number;
}

/**
 * A que o fato se refere — é isto que a tela transforma em link.
 *
 * Todos opcionais menos `id_execucoes` porque cada tipo aponta para coisas
 * diferentes: fato de tema tem `id_tema`, de vídeo tem `id_video`, de campanha
 * não tem nenhum dos dois e tem as duas execuções comparadas.
 * `concentracao_das_criticas` fala de um CONJUNTO de temas e por isso não traz
 * `id_tema` — linkar para o primeiro apontado seria linkar para parte do que
 * o card afirma.
 */
export interface OrigemInsight {
  /** Cronológica. Um item nos fatos de execução, dois nos de campanha. */
  id_execucoes: number[];
  id_tema?: number | null;
  id_video?: number | null;
  youtube_video_id?: string | null;
}

/**
 * Um achado do motor de insights.
 *
 * **Por que o fato inteiro, e não só `texto`.** Com a frase pronta a tela não
 * consegue ordenar por relevância, filtrar por tipo, montar o link para o tema
 * que originou a afirmação, nem mostrar o lastro da amostra — teria uma string.
 * `texto` continua vindo do servidor (a frase faz parte da análise: se a regra
 * muda, a frase muda junto, num lugar só), mas agora acompanhado do que a
 * gerou.
 *
 * `valores` é um dicionário aberto de propósito: cada `tipo` tem o seu conjunto
 * de chaves, documentado no modelo de frase correspondente
 * (`backend/app/insights/frases.py`), e um tipo novo não mexe em nenhuma
 * interface existente. A tela que quiser render próprio lê as chaves do tipo
 * que ela trata; quem não trata cai no `texto`, que sempre existe.
 */
export interface FatoInsight {
  tipo: TipoFato;
  valores: Record<string, ValorFato>;
  amostra: AmostraInsight;
  origem: OrigemInsight;
  /** Frase gerada por modelo no servidor. Nunca vazia. */
  texto: string;
}

/** Resposta de `GET /api/v1/execucoes/{id}/resultado`. */
export interface ResultadoExecucao {
  id_execucao: number;
  id_modelo: number;
  /** MODELOS_ANALISE.nome — o título da tela. */
  nome_modelo_analise: string;
  concluido_em: string | null;
  distribuicao: DistribuicaoSentimento;
  alcance: AlcanceExecucao;
  videos: VideoComSentimento[];
  temas: TemaComSentimento[];
  /** Amostra escolhida pelo servidor: um positivo, um negativo, um neutro. */
  comentarios_representativos: ComentarioAnalisado[];
  /**
   * Fatos desta execução, já em ordem de relevância — crítica antes de elogio.
   * Vazio é resultado normal: execução pequena demais, ou nenhum tema com
   * amostra suficiente, não produz insight (e a tela não mostra o painel).
   */
  insights: FatoInsight[];
  /**
   * Fatos que só existem comparando esta coleta com as anteriores do MESMO
   * modelo de análise. Vazio quando é a primeira coleta do modelo, ou quando
   * nenhuma diferença excedeu a margem de incerteza — que é o caso comum.
   *
   * Vem junto do resultado da execução, e não num endpoint próprio, porque a
   * tela mostra os dois no mesmo lugar ("o que mudou desde a última coleta") e
   * uma segunda requisição só para isso deixaria o painel piscando depois do
   * resto da página.
   */
  insights_da_campanha: FatoInsight[];
  /** @deprecated Ver `PontoDeAtencao`. Migrar `resultado.html` para `insights`. */
  ponto_de_atencao: PontoDeAtencao | null;
  /**
   * Qual versão do classificador produziu estas análises — o nome vem da linha
   * de VERSOES_MODELO, nunca fixo na tela: hoje é o léxico (SentiLex), amanhã o
   * BERTimbau, e a tela não precisa saber qual.
   *
   * `null` na execução que não classificou nada (todos os vídeos com comentário
   * desabilitado) num banco onde nenhuma versão foi registrada ainda.
   */
  versao_modelo: VersaoModelo | null;
}

/** Item de `GET /api/v1/execucoes/resultados` — só o suficiente para escolher. */
export interface ResultadoDisponivel {
  id_execucao: number;
  id_modelo: number;
  nome_modelo_analise: string;
  concluido_em: string | null;
  distribuicao: DistribuicaoSentimento;
  total_videos: number;
  total_temas: number;
}

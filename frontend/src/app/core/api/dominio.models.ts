/**
 * Contrato das respostas de análise — espelha as tabelas do CLAUDE.md §4.
 *
 * Estas interfaces existem ANTES dos endpoints: as telas de Início, Resultados
 * e Comentários rodam com mock enquanto o worker de inferência não existe, e é
 * este arquivo que o backend precisa implementar para o mock ser desligado.
 * Ver `frontend/README.md` para a lista de endpoints pendentes.
 *
 * Regras que valem para tudo aqui:
 * - nome de campo = nome da coluna, em português (a banca compara com o DER);
 * - `datetime` viaja como ISO 8601 em string (o JSON não tem tipo de data);
 * - o que é AGREGAÇÃO (contagem, soma) está marcado como tal — não é coluna,
 *   é conta que o endpoint faz.
 */

/** CHECK `ck_analises_sentimento_sentimento`. */
export type Sentimento = 'positivo' | 'negativo' | 'neutro';

/** CHECK `ck_versoes_modelo_status`. */
export type StatusVersaoModelo = 'ativo' | 'arquivado';

// ---------------------------------------------------------------------------
// Linhas de tabela
// ---------------------------------------------------------------------------

/** Tabela VIDEOS. */
export interface Video {
  id_video: number;
  id_execucao: number;
  youtube_video_id: string;
  titulo: string;
  canal: string;
  publicado_em: string | null;
  visualizacoes: number;
  curtidas: number;
}

/**
 * Tabela COMENTARIOS.
 *
 * `autor_hash` é SHA-256 e NUNCA deve ser exibido — está no contrato só porque
 * é a chave que liga comentários da mesma pessoa dentro de uma execução
 * (CLAUDE.md regra 2). Nenhuma tela imprime este campo.
 */
export interface Comentario {
  id_comentario: number;
  id_video: number;
  youtube_comment_id: string;
  autor_hash: string;
  texto: string;
  publicado_em: string | null;
}

/**
 * Tabela ANALISES_SENTIMENTO.
 *
 * ATENÇÃO — `confianca` NÃO existe na tabela hoje. O design pede o selo
 * "Revisão sugerida" em classificação de baixa confiança (Comentarios.png), e
 * isso só é possível com o score do modelo persistido. Ou entra uma coluna
 * `confianca REAL` por migration, ou o campo sai do contrato e o selo some.
 * Decisão pendente — está documentada no README.
 */
export interface AnaliseSentimento {
  id_analise: number;
  id_comentario: number;
  id_versao_modelo: number;
  sentimento: Sentimento;
  /** Tema principal em texto livre, como o modelo devolveu. */
  tema: string | null;
  justificativa: string | null;
  processado_em: string;
  /** 0..1. Ver aviso acima: depende de coluna nova. */
  confianca: number | null;
}

/** Tabela TEMAS. `palavras_chave` é o JSONB. */
export interface Tema {
  id_tema: number;
  id_execucao: number;
  rotulo_tema: string;
  palavras_chave: string[] | null;
}

/** Tabela COMENTARIO_TEMA (N:N com atributo). */
export interface ComentarioTema {
  id_comentario: number;
  id_tema: number;
  peso: number;
}

/** Métricas do `metricas_avaliacao` (JSONB) de VERSOES_MODELO. */
export interface MetricasAvaliacao {
  /** Métrica que importa no projeto (CLAUDE.md regra 8), não a acurácia. */
  f1_macro: number;
  acuracia?: number;
  f1_por_classe?: Record<Sentimento, number>;
  /** Tamanho do conjunto de teste — que é só humano (CLAUDE.md regra 6). */
  exemplos_teste?: number;
}

/** Tabela VERSOES_MODELO. */
export interface VersaoModelo {
  id_versao: number;
  nome_modelo: string;
  versao: string;
  metricas_avaliacao: MetricasAvaliacao | null;
  status: StatusVersaoModelo;
  /** Não é coluna: data em que a versão passou a ser usada, para a tela. */
  em_uso_desde?: string | null;
}

// ---------------------------------------------------------------------------
// Agregações (o endpoint calcula; não são colunas)
// ---------------------------------------------------------------------------

/** Contagem de ANALISES_SENTIMENTO por valor de `sentimento`. */
export interface DistribuicaoSentimento {
  positivo: number;
  neutro: number;
  negativo: number;
  /** Soma dos três — vem pronta para a tela não somar errado. */
  total: number;
}

/** Percentual inteiro por sentimento; os três somam 100. */
export function percentuais(d: DistribuicaoSentimento): Record<Sentimento, number> {
  if (d.total <= 0) {
    return { positivo: 0, neutro: 0, negativo: 0 };
  }
  const positivo = Math.round((d.positivo / d.total) * 100);
  const neutro = Math.round((d.neutro / d.total) * 100);
  // O negativo fecha a conta: arredondar os três separados daria 99% ou 101%.
  return { positivo, neutro, negativo: 100 - positivo - neutro };
}

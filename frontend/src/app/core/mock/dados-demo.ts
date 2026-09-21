/**
 * Conjunto de demonstração das telas de análise.
 *
 * Existe porque o worker de inferência ainda não roda: sem ele não há
 * ANALISES_SENTIMENTO, TEMAS nem COMENTARIO_TEMA no banco, e as telas de
 * Início, Resultados e Comentários não teriam o que mostrar.
 *
 * Os textos imitam o que a coleta real traz — português informal, gíria,
 * ironia, erro de digitação e emoji — porque é isso que o BERTimbau vai
 * receber. Comentário limpo demais no mock esconde justamente os casos em que
 * a classificação erra.
 *
 * Nada aqui é resultado real: toda tela que consome estes dados exibe o selo
 * "Dados de demonstração" (ver `selo-demo`).
 */

import {
  AnaliseSentimento,
  Comentario,
  DistribuicaoSentimento,
  Sentimento,
  Tema,
  Video,
  VersaoModelo,
} from '../api/dominio.models';
import {
  AlcanceExecucao,
  ComentarioAnalisado,
  ResultadoExecucao,
  TemaComSentimento,
  VideoComSentimento,
} from '../api/resultados.models';

// ---------------------------------------------------------------------------
// Sementes
// ---------------------------------------------------------------------------

/** `[positivo, neutro, negativo]` — some ao total da linha. */
type Dist = readonly [number, number, number];

interface SementeVideo {
  titulo: string;
  canal: string;
  publicado_em: string;
  youtube_video_id: string;
  visualizacoes: number;
  curtidas: number;
  dist: Dist;
}

interface SementeTema {
  rotulo: string;
  palavras: string[];
  dist: Dist;
}

interface SementeComentario {
  texto: string;
  sentimento: Sentimento;
  justificativa: string;
  /** < 0.6 faz a tela sugerir revisão humana. */
  confianca: number;
  /** Índice em `videos`. */
  video: number;
  /** `[índice em temas, peso]`, do mais forte para o mais fraco. */
  temas: readonly (readonly [number, number])[];
  publicado_em: string;
  /** Índice do autor fictício — dois comentários da mesma pessoa repetem. */
  autor: number;
}

interface SementeExecucao {
  id_execucao: number;
  id_modelo: number;
  nome: string;
  concluido_em: string;
  videos: SementeVideo[];
  temas: SementeTema[];
  comentarios: SementeComentario[];
  atencao: { tema: number; texto: string };
}

// ---------------------------------------------------------------------------
// Versão do classificador
// ---------------------------------------------------------------------------

export const VERSAO_MODELO: VersaoModelo = {
  id_versao: 3,
  nome_modelo: 'BERTimbau',
  versao: 'v1.2',
  status: 'ativo',
  // Meio-dia UTC de propósito: à meia-noite UTC a data vira o dia anterior
  // no fuso de Brasília e a tela mostraria "13 set".
  em_uso_desde: '2026-09-14T12:00:00Z',
  metricas_avaliacao: {
    f1_macro: 0.79,
    acuracia: 0.83,
    f1_por_classe: { positivo: 0.87, neutro: 0.74, negativo: 0.76 },
    exemplos_teste: 600,
  },
};

// ---------------------------------------------------------------------------
// Execução 12 — Dia das Mães, joalheria (a do design/Dashboard.png)
// ---------------------------------------------------------------------------

const JOALHERIA: SementeExecucao = {
  id_execucao: 12,
  id_modelo: 2,
  nome: 'Dia das Mães — joalheria',
  concluido_em: '2026-09-17T12:15:00Z',
  videos: [
    {
      titulo: 'O presente que ela vai lembrar pra sempre',
      canal: 'Joalheria Aurora',
      publicado_em: '2026-05-08T14:00:00Z',
      youtube_video_id: 'aUr0raM4e01',
      visualizacoes: 512_000,
      curtidas: 14_820,
      dist: [830, 328, 126],
    },
    {
      titulo: 'Coleção Mãe & Filha — bastidores',
      canal: 'Joalheria Aurora',
      publicado_em: '2026-05-02T13:00:00Z',
      youtube_video_id: 'aUr0raM4e02',
      visualizacoes: 347_000,
      curtidas: 9_640,
      dist: [581, 231, 89],
    },
    {
      titulo: 'Anel solitário: vale o investimento?',
      canal: 'Joalheria Aurora',
      publicado_em: '2026-04-28T18:30:00Z',
      youtube_video_id: 'aUr0raM4e03',
      visualizacoes: 289_000,
      curtidas: 6_120,
      dist: [262, 262, 240],
    },
    {
      titulo: 'Depoimento: três gerações, um colar',
      canal: 'Joalheria Aurora',
      publicado_em: '2026-04-24T12:00:00Z',
      youtube_video_id: 'aUr0raM4e04',
      visualizacoes: 178_000,
      curtidas: 5_390,
      dist: [401, 88, 32],
    },
    {
      titulo: 'Como escolher o tamanho certo do anel',
      canal: 'Joalheria Aurora',
      publicado_em: '2026-04-19T15:00:00Z',
      youtube_video_id: 'aUr0raM4e05',
      visualizacoes: 94_000,
      curtidas: 2_180,
      dist: [148, 96, 44],
    },
    {
      titulo: 'Entrega expressa para o Dia das Mães',
      canal: 'Joalheria Aurora',
      publicado_em: '2026-05-05T09:00:00Z',
      youtube_video_id: 'aUr0raM4e06',
      visualizacoes: 62_000,
      curtidas: 750,
      dist: [35, 46, 53],
    },
  ],
  temas: [
    {
      rotulo: 'Design das peças',
      palavras: ['delicado', 'dourado', 'elegante', 'fino'],
      dist: [701, 198, 83],
    },
    { rotulo: 'Preço', palavras: ['caro', 'absurdo', 'valor', 'parcelas'], dist: [160, 198, 403] },
    {
      rotulo: 'Emoção da campanha',
      palavras: ['chorei', 'linda', 'emocionante', 'mãe'],
      dist: [592, 48, 14],
    },
    {
      rotulo: 'Entrega e prazo',
      palavras: ['chegou', 'atraso', 'frete', 'correios'],
      dist: [121, 168, 200],
    },
    {
      rotulo: 'Atendimento',
      palavras: ['loja', 'vendedora', 'troca', 'whatsapp'],
      dist: [143, 122, 112],
    },
    {
      rotulo: 'Trilha sonora',
      palavras: ['música', 'nome da música', 'trilha'],
      dist: [214, 71, 27],
    },
    {
      rotulo: 'Tamanho e medidas',
      palavras: ['tamanho', 'aro', 'medida', 'serve'],
      dist: [74, 112, 22],
    },
    {
      rotulo: 'Garantia e banho',
      palavras: ['banhado', 'descascou', 'garantia', 'oxidou'],
      dist: [41, 52, 71],
    },
    {
      rotulo: 'Comparação com concorrente',
      palavras: ['mesma coisa', 'mais barato', 'concorrente'],
      dist: [18, 29, 50],
    },
  ],
  atencao: {
    tema: 1,
    texto:
      'Preço concentra a maior parte das reclamações: 53% dos 761 comentários do tema são negativos, e a objeção mais repetida compara o valor com joias de ouro maciço. O vídeo "Anel solitário: vale o investimento?" tem o dobro da negatividade média da execução — é onde a conversa sobre preço se concentra.',
  },
  comentarios: [
    {
      texto:
        'Comprei pra minha mãe e ela chorou quando abriu. Vale cada centavo, o acabamento é impecável.',
      sentimento: 'positivo',
      justificativa: 'Relato de experiência positiva com reforço explícito de valor percebido.',
      confianca: 0.96,
      video: 0,
      temas: [
        [2, 0.72],
        [0, 0.58],
      ],
      publicado_em: '2026-05-09T10:12:00Z',
      autor: 1,
    },
    {
      texto:
        'Bonito sim, mas 2 mil reais num anel banhado? Tá de brincadeira né. Por esse valor eu compro ouro de verdade em qualquer lugar.',
      sentimento: 'negativo',
      justificativa:
        'Elogio inicial ao produto seguido de objeção forte ao preço, que domina a intenção geral do comentário.',
      confianca: 0.93,
      video: 2,
      temas: [
        [1, 0.91],
        [7, 0.44],
        [0, 0.34],
      ],
      publicado_em: '2026-05-03T21:40:00Z',
      autor: 2,
    },
    {
      texto: 'Alguém sabe se tem na cor prata? Só achei dourado no site',
      sentimento: 'neutro',
      justificativa: 'Pergunta sobre disponibilidade, sem juízo de valor sobre o produto.',
      confianca: 0.88,
      video: 0,
      temas: [
        [0, 0.66],
        [4, 0.31],
      ],
      publicado_em: '2026-05-10T08:05:00Z',
      autor: 3,
    },
    {
      texto: 'nossa que entrega RÁPIDA hein, só 3 semanas pra chegar 👏👏',
      sentimento: 'negativo',
      justificativa:
        'Possível ironia: o elogio contrasta com o prazo citado. Classificação de menor confiança.',
      confianca: 0.41,
      video: 5,
      temas: [[3, 0.95]],
      publicado_em: '2026-05-06T19:22:00Z',
      autor: 4,
    },
    {
      texto: 'Em Guarulhos tem a mesma coisa por metade do preço, procurem antes de comprar',
      sentimento: 'negativo',
      justificativa: 'Comparação desfavorável de preço com recomendação explícita de alternativa.',
      confianca: 0.89,
      video: 2,
      temas: [
        [8, 0.9],
        [1, 0.88],
      ],
      publicado_em: '2026-04-30T16:47:00Z',
      autor: 5,
    },
    {
      texto: 'Parcela em quantas vezes? No site não achei essa informação em lugar nenhum',
      sentimento: 'neutro',
      justificativa: 'Pergunta sobre condições de pagamento, sem julgamento do valor em si.',
      confianca: 0.85,
      video: 0,
      temas: [
        [1, 0.78],
        [4, 0.52],
      ],
      publicado_em: '2026-05-09T11:30:00Z',
      autor: 6,
    },
    {
      texto:
        'Achei caro no começo, mas depois que vi de perto entendi o preço. Qualidade justifica.',
      sentimento: 'positivo',
      justificativa:
        'Objeção inicial ao preço revertida no fim, com conclusão favorável ao produto.',
      confianca: 0.81,
      video: 3,
      temas: [
        [1, 0.84],
        [0, 0.41],
      ],
      publicado_em: '2026-04-26T14:03:00Z',
      autor: 7,
    },
    {
      texto:
        'chorei litros nesse comercial pqp, minha mãe faleceu ano passado e isso aqui me pegou',
      sentimento: 'positivo',
      justificativa:
        'Reação emocional intensa à campanha. O tom é de elogio, apesar do conteúdo triste.',
      confianca: 0.68,
      video: 3,
      temas: [[2, 0.94]],
      publicado_em: '2026-04-25T23:58:00Z',
      autor: 8,
    },
    {
      texto: 'qual o nome da musica????',
      sentimento: 'neutro',
      justificativa: 'Pergunta sobre a trilha, sem avaliação do produto ou da marca.',
      confianca: 0.97,
      video: 0,
      temas: [[5, 0.98]],
      publicado_em: '2026-05-08T20:14:00Z',
      autor: 9,
    },
    {
      texto: 'minha mae amou dms o colar, obrigada aurora ❤️ ja virou cliente fiel',
      sentimento: 'positivo',
      justificativa: 'Agradecimento com declaração de fidelidade à marca.',
      confianca: 0.95,
      video: 3,
      temas: [
        [2, 0.7],
        [0, 0.45],
      ],
      publicado_em: '2026-05-11T09:41:00Z',
      autor: 10,
    },
    {
      texto: 'gente o dourado descasca depois de 2 meses, cuidado. o meu já ta esverdeado',
      sentimento: 'negativo',
      justificativa: 'Relato de defeito no acabamento com alerta a outros compradores.',
      confianca: 0.92,
      video: 2,
      temas: [
        [7, 0.93],
        [0, 0.5],
      ],
      publicado_em: '2026-05-01T17:26:00Z',
      autor: 11,
    },
    {
      texto: 'Comprei dia 20 e chegou dia 22, correios voando dessa vez kkkk recomendo',
      sentimento: 'positivo',
      justificativa: 'Elogio ao prazo de entrega, confirmado por datas concretas.',
      confianca: 0.9,
      video: 5,
      temas: [[3, 0.89]],
      publicado_em: '2026-05-07T12:09:00Z',
      autor: 12,
    },
    {
      texto: 'Propaganda linda mas cadê o preço? sempre escondem, aí já sei que não é pra mim',
      sentimento: 'negativo',
      justificativa:
        'Crítica à falta de transparência de preço; o elogio inicial não muda a conclusão.',
      confianca: 0.79,
      video: 0,
      temas: [
        [1, 0.86],
        [2, 0.3],
      ],
      publicado_em: '2026-05-09T18:33:00Z',
      autor: 13,
    },
    {
      texto:
        'a vendedora da loja do shopping foi super atenciosa, me ajudou a escolher o aro certo',
      sentimento: 'positivo',
      justificativa: 'Elogio ao atendimento presencial, com menção ao auxílio recebido.',
      confianca: 0.94,
      video: 4,
      temas: [
        [4, 0.88],
        [6, 0.54],
      ],
      publicado_em: '2026-04-21T15:52:00Z',
      autor: 14,
    },
    {
      texto: 'tamanho 16 serve em quem usa 17? to na duvida e nao quero errar o presente',
      sentimento: 'neutro',
      justificativa: 'Dúvida sobre medida, sem opinião sobre a peça.',
      confianca: 0.91,
      video: 4,
      temas: [[6, 0.96]],
      publicado_em: '2026-04-20T10:18:00Z',
      autor: 15,
    },
    {
      texto: 'esse anel é o msm que vi na concorrente por 890, só que lá vem com certificado',
      sentimento: 'negativo',
      justificativa: 'Comparação direta com concorrente, desfavorável em preço e em garantia.',
      confianca: 0.87,
      video: 2,
      temas: [
        [8, 0.92],
        [1, 0.73],
        [7, 0.38],
      ],
      publicado_em: '2026-05-02T13:05:00Z',
      autor: 16,
    },
    {
      texto: 'PERFEITO demais, já é o terceiro que compro aqui. o acabamento é outro nível',
      sentimento: 'positivo',
      justificativa: 'Elogio enfático com evidência de recompra.',
      confianca: 0.97,
      video: 1,
      temas: [[0, 0.85]],
      publicado_em: '2026-05-04T08:27:00Z',
      autor: 17,
    },
    {
      texto: 'a trilha sonora me pegou desprevenido no trabalho, chorando aqui na mesa 😭',
      sentimento: 'positivo',
      justificativa: 'Reação emocional à trilha; o choro aparece como elogio à campanha.',
      confianca: 0.72,
      video: 1,
      temas: [
        [5, 0.87],
        [2, 0.66],
      ],
      publicado_em: '2026-05-03T14:44:00Z',
      autor: 18,
    },
    {
      texto: 'cade a opção de troca? comprei errado e ninguem responde o whatsapp faz 4 dias',
      sentimento: 'negativo',
      justificativa: 'Reclamação de atendimento pós-venda com ausência de resposta.',
      confianca: 0.93,
      video: 4,
      temas: [
        [4, 0.94],
        [6, 0.4],
      ],
      publicado_em: '2026-04-22T19:11:00Z',
      autor: 19,
    },
    {
      texto: 'bem bonitinho mas não é pra minha realidade não kkkkk',
      sentimento: 'neutro',
      justificativa: 'Elogio seguido de constatação de preço fora do alcance, sem crítica à marca.',
      confianca: 0.55,
      video: 2,
      temas: [
        [1, 0.8],
        [0, 0.42],
      ],
      publicado_em: '2026-04-29T22:37:00Z',
      autor: 20,
    },
    {
      texto: 'Comprei pra minha sogra e ela detestou, disse que era coisa de menina kkkk',
      sentimento: 'negativo',
      justificativa: 'Relato de rejeição do presente; o tom bem-humorado não muda o resultado.',
      confianca: 0.58,
      video: 0,
      temas: [[0, 0.76]],
      publicado_em: '2026-05-12T16:20:00Z',
      autor: 21,
    },
    {
      texto: 'que campanha linda meu deus, a Aurora sempre acerta no dia das mães',
      sentimento: 'positivo',
      justificativa: 'Elogio direto à campanha e à consistência da marca.',
      confianca: 0.96,
      video: 1,
      temas: [[2, 0.89]],
      publicado_em: '2026-05-02T18:02:00Z',
      autor: 22,
    },
    {
      texto: 'frete de 40 reais pra entregar em 15 dias úteis... tá osso hein',
      sentimento: 'negativo',
      justificativa: 'Crítica combinada ao custo do frete e ao prazo.',
      confianca: 0.9,
      video: 5,
      temas: [
        [3, 0.93],
        [1, 0.61],
      ],
      publicado_em: '2026-05-06T11:15:00Z',
      autor: 23,
    },
    {
      texto: 'chegou quebrado o fecho, mandei msg e trocaram na hora. atendimento nota 10',
      sentimento: 'positivo',
      justificativa: 'Problema no produto resolvido pelo atendimento; a conclusão é elogiosa.',
      confianca: 0.76,
      video: 5,
      temas: [
        [4, 0.86],
        [3, 0.55],
      ],
      publicado_em: '2026-05-08T13:48:00Z',
      autor: 24,
    },
    {
      texto: 'poderia ter mais opções pra quem usa aro maior, 20 pra cima nunca tem',
      sentimento: 'negativo',
      justificativa: 'Reclamação sobre ausência de tamanhos maiores no catálogo.',
      confianca: 0.83,
      video: 4,
      temas: [[6, 0.91]],
      publicado_em: '2026-04-20T20:30:00Z',
      autor: 25,
    },
    {
      texto: 'Só eu que vim aqui pelo comentário do pessoal falando da música? kkkk',
      sentimento: 'neutro',
      justificativa: 'Comentário sobre a repercussão da trilha, sem avaliar produto ou campanha.',
      confianca: 0.84,
      video: 0,
      temas: [[5, 0.9]],
      publicado_em: '2026-05-10T21:07:00Z',
      autor: 26,
    },
    {
      texto: 'to há 2 meses de olho nesse colar esperando baixar o preço e nada né',
      sentimento: 'neutro',
      justificativa: 'Manifestação de interesse condicionada a preço, sem crítica explícita.',
      confianca: 0.62,
      video: 1,
      temas: [
        [1, 0.82],
        [0, 0.39],
      ],
      publicado_em: '2026-05-05T10:55:00Z',
      autor: 27,
    },
    {
      texto: 'dei pra minha mãe e ela usa todo dia desde então, nem tira pra dormir 🥹',
      sentimento: 'positivo',
      justificativa: 'Evidência de uso contínuo como sinal de satisfação.',
      confianca: 0.95,
      video: 3,
      temas: [
        [2, 0.8],
        [0, 0.52],
      ],
      publicado_em: '2026-04-27T09:19:00Z',
      autor: 28,
    },
    {
      texto: 'Vcs entregam em Manaus? o site diz que sim mas o frete não calcula',
      sentimento: 'neutro',
      justificativa: 'Dúvida operacional sobre entrega, com relato de falha no site.',
      confianca: 0.8,
      video: 5,
      temas: [
        [3, 0.85],
        [4, 0.43],
      ],
      publicado_em: '2026-05-07T17:36:00Z',
      autor: 29,
    },
    {
      texto: 'banhado a ouro 18k é golpe, em 6 meses volta pro prata. já passei por isso',
      sentimento: 'negativo',
      justificativa: 'Acusação de baixa durabilidade do banho, com relato pessoal anterior.',
      confianca: 0.91,
      video: 2,
      temas: [
        [7, 0.95],
        [8, 0.35],
      ],
      publicado_em: '2026-04-29T12:41:00Z',
      autor: 11,
    },
    {
      texto: 'o design é muito delicado, exatamente o que eu procurava pra usar no dia a dia',
      sentimento: 'positivo',
      justificativa: 'Elogio ao design alinhado à necessidade de uso cotidiano.',
      confianca: 0.94,
      video: 1,
      temas: [[0, 0.93]],
      publicado_em: '2026-05-04T15:23:00Z',
      autor: 30,
    },
    {
      texto: 'ahhh sei, "edição limitada" que tá no site desde o ano passado 🙄',
      sentimento: 'negativo',
      justificativa: 'Ironia sobre a escassez anunciada, questionando a veracidade da comunicação.',
      confianca: 0.47,
      video: 1,
      temas: [
        [0, 0.48],
        [1, 0.35],
      ],
      publicado_em: '2026-05-05T19:50:00Z',
      autor: 31,
    },
    {
      texto: 'Meu pedido sumiu no rastreio faz 9 dias e o suporte só manda msg automática',
      sentimento: 'negativo',
      justificativa: 'Falha logística somada a atendimento sem resolução.',
      confianca: 0.95,
      video: 5,
      temas: [
        [3, 0.92],
        [4, 0.81],
      ],
      publicado_em: '2026-05-09T08:12:00Z',
      autor: 32,
    },
    {
      texto: 'alguem sabe se esse modelo tem garantia? não achei nada no site sobre isso',
      sentimento: 'neutro',
      justificativa: 'Pergunta sobre garantia, sem opinião formada.',
      confianca: 0.89,
      video: 2,
      temas: [[7, 0.88]],
      publicado_em: '2026-04-30T11:04:00Z',
      autor: 33,
    },
    {
      texto: 'video muito bem produzido, dá gosto de ver propaganda brasileira nesse nível',
      sentimento: 'positivo',
      justificativa: 'Elogio à produção do vídeo, não ao produto.',
      confianca: 0.92,
      video: 1,
      temas: [
        [2, 0.75],
        [5, 0.4],
      ],
      publicado_em: '2026-05-03T09:31:00Z',
      autor: 34,
    },
    {
      texto: 'comprei na promoção de abril e valeu muito, fora dela eu não pagaria não',
      sentimento: 'neutro',
      justificativa:
        'Avaliação condicionada ao desconto; positiva na promoção, negativa fora dela.',
      confianca: 0.51,
      video: 3,
      temas: [[1, 0.87]],
      publicado_em: '2026-04-26T20:08:00Z',
      autor: 35,
    },
    {
      texto: 'a caixinha de presente já vem pronta? queria dar sem precisar embrulhar',
      sentimento: 'neutro',
      justificativa: 'Dúvida sobre embalagem, sem avaliação do produto.',
      confianca: 0.93,
      video: 0,
      temas: [
        [4, 0.7],
        [0, 0.33],
      ],
      publicado_em: '2026-05-08T16:45:00Z',
      autor: 36,
    },
    {
      texto: 'melhor compra do ano disparado, minha mãe não parou de mostrar pras amigas',
      sentimento: 'positivo',
      justificativa: 'Elogio superlativo com evidência de satisfação de quem recebeu.',
      confianca: 0.97,
      video: 3,
      temas: [
        [2, 0.82],
        [0, 0.47],
      ],
      publicado_em: '2026-04-28T13:27:00Z',
      autor: 37,
    },
    {
      texto: 'paguei 1.890 e chegou com risco na parte de trás. pra esse preço não dá né',
      sentimento: 'negativo',
      justificativa: 'Defeito no produto agravado pela expectativa criada pelo preço pago.',
      confianca: 0.94,
      video: 2,
      temas: [
        [1, 0.89],
        [7, 0.66],
      ],
      publicado_em: '2026-05-01T10:39:00Z',
      autor: 38,
    },
    {
      texto: 'qnt tempo demora pra chegar em SP capital?',
      sentimento: 'neutro',
      justificativa: 'Pergunta objetiva sobre prazo de entrega.',
      confianca: 0.95,
      video: 5,
      temas: [[3, 0.94]],
      publicado_em: '2026-05-06T07:58:00Z',
      autor: 39,
    },
    {
      texto: 'to chorando no ônibus com esse video, que absurdo fazerem isso comigo de manhã',
      sentimento: 'positivo',
      justificativa:
        'Reclamação bem-humorada que expressa envolvimento emocional positivo com a campanha.',
      confianca: 0.44,
      video: 3,
      temas: [[2, 0.91]],
      publicado_em: '2026-04-25T08:03:00Z',
      autor: 40,
    },
    {
      texto: 'vendedora me empurrou o mais caro da loja, saí sem comprar nada',
      sentimento: 'negativo',
      justificativa: 'Crítica à abordagem comercial que resultou em desistência da compra.',
      confianca: 0.9,
      video: 4,
      temas: [
        [4, 0.9],
        [1, 0.57],
      ],
      publicado_em: '2026-04-23T18:16:00Z',
      autor: 41,
    },
    {
      texto: 'lindo mas 3x sem juros em 2 mil reais não ajuda muito né gente',
      sentimento: 'negativo',
      justificativa: 'Crítica às condições de parcelamento frente ao valor total.',
      confianca: 0.82,
      video: 2,
      temas: [[1, 0.9]],
      publicado_em: '2026-05-02T21:24:00Z',
      autor: 42,
    },
    {
      texto: 'presenteei minha avó de 89 anos e ela disse que nunca ganhou nada tão bonito 🥺',
      sentimento: 'positivo',
      justificativa: 'Relato emocional de satisfação de quem recebeu o presente.',
      confianca: 0.96,
      video: 3,
      temas: [
        [2, 0.88],
        [0, 0.5],
      ],
      publicado_em: '2026-04-27T17:12:00Z',
      autor: 43,
    },
    {
      texto: 'o anel é bonito, o problema é que some do estoque toda hora',
      sentimento: 'neutro',
      justificativa: 'Elogio ao produto com ressalva sobre disponibilidade.',
      confianca: 0.66,
      video: 2,
      temas: [
        [0, 0.72],
        [4, 0.48],
      ],
      publicado_em: '2026-04-30T14:53:00Z',
      autor: 44,
    },
    {
      texto: 'Aurora vcs vão relançar a coleção do ano passado? perdi a chance na época',
      sentimento: 'neutro',
      justificativa: 'Pergunta sobre relançamento, com interesse implícito na marca.',
      confianca: 0.87,
      video: 1,
      temas: [[0, 0.68]],
      publicado_em: '2026-05-04T19:37:00Z',
      autor: 45,
    },
  ],
};

// ---------------------------------------------------------------------------
// Execução 8 — Black Friday, eletrônicos (menor, para a lista ter dois itens)
// ---------------------------------------------------------------------------

const BLACK_FRIDAY: SementeExecucao = {
  id_execucao: 8,
  id_modelo: 4,
  nome: 'Black Friday — eletrônicos',
  concluido_em: '2026-09-12T19:44:00Z',
  videos: [
    {
      titulo: 'Black Friday: o que vale a pena em 2026',
      canal: 'TecnoLar',
      publicado_em: '2026-09-02T12:00:00Z',
      youtube_video_id: 'tEcn0L4r001',
      visualizacoes: 421_000,
      curtidas: 11_240,
      dist: [1102, 604, 388],
    },
    {
      titulo: 'Fone bluetooth de 200 reais presta?',
      canal: 'TecnoLar',
      publicado_em: '2026-08-28T17:00:00Z',
      youtube_video_id: 'tEcn0L4r002',
      visualizacoes: 268_000,
      curtidas: 7_910,
      dist: [742, 401, 318],
    },
    {
      titulo: 'Montamos um setup completo com 3 mil',
      canal: 'TecnoLar',
      publicado_em: '2026-08-21T14:30:00Z',
      youtube_video_id: 'tEcn0L4r003',
      visualizacoes: 197_000,
      curtidas: 6_380,
      dist: [688, 233, 141],
    },
    {
      titulo: 'Cuidado com esses "descontos" de Black Friday',
      canal: 'TecnoLar',
      publicado_em: '2026-09-05T20:00:00Z',
      youtube_video_id: 'tEcn0L4r004',
      visualizacoes: 152_000,
      curtidas: 9_020,
      dist: [301, 188, 260],
    },
  ],
  temas: [
    {
      rotulo: 'Desconto de verdade',
      palavras: ['metade do dobro', 'maquiado', 'histórico', 'preço'],
      dist: [412, 338, 501],
    },
    {
      rotulo: 'Qualidade do produto',
      palavras: ['durou', 'qualidade', 'vale', 'recomendo'],
      dist: [988, 241, 147],
    },
    {
      rotulo: 'Frete e prazo',
      palavras: ['frete', 'chegou', 'prazo', 'correios'],
      dist: [276, 322, 214],
    },
    {
      rotulo: 'Comparação de marcas',
      palavras: ['xiaomi', 'jbl', 'genérico', 'original'],
      dist: [503, 287, 132],
    },
    {
      rotulo: 'Indicação de cupom',
      palavras: ['cupom', 'link', 'desconto', 'código'],
      dist: [391, 154, 63],
    },
  ],
  atencao: {
    tema: 0,
    texto:
      'Desconto de verdade é o único tema com mais negativos do que positivos: 40% dos 1.251 comentários questionam se o preço subiu antes da promoção. A desconfiança se concentra no vídeo "Cuidado com esses descontos de Black Friday", que puxa a média de negatividade da execução.',
  },
  comentarios: [
    {
      texto: 'comprei o fone e já era, durou 2 semanas. dinheiro no lixo',
      sentimento: 'negativo',
      justificativa: 'Relato de falha precoce do produto com conclusão de prejuízo.',
      confianca: 0.94,
      video: 1,
      temas: [[1, 0.92]],
      publicado_em: '2026-09-04T11:22:00Z',
      autor: 51,
    },
    {
      texto: 'aquele "desconto" que sobe 30% em outubro pra cair 25% em novembro né kkkk',
      sentimento: 'negativo',
      justificativa: 'Ironia sobre desconto maquiado, com cálculo que expõe a prática.',
      confianca: 0.49,
      video: 3,
      temas: [[0, 0.96]],
      publicado_em: '2026-09-06T13:40:00Z',
      autor: 52,
    },
    {
      texto: 'usei o cupom do canal e economizei 180 reais, valeu demais irmão',
      sentimento: 'positivo',
      justificativa: 'Confirmação de economia real com o cupom indicado.',
      confianca: 0.96,
      video: 0,
      temas: [
        [4, 0.94],
        [0, 0.51],
      ],
      publicado_em: '2026-09-03T09:14:00Z',
      autor: 53,
    },
    {
      texto: 'esse setup de 3 mil tá mais pra 4500 hoje, os preços mudaram tudo',
      sentimento: 'negativo',
      justificativa: 'Contestação da viabilidade do orçamento apresentado no vídeo.',
      confianca: 0.86,
      video: 2,
      temas: [
        [0, 0.83],
        [1, 0.4],
      ],
      publicado_em: '2026-08-23T16:05:00Z',
      autor: 54,
    },
    {
      texto: 'o generico dura mais que o original nesse caso, testei os dois',
      sentimento: 'positivo',
      justificativa: 'Comparação favorável ao produto alternativo, baseada em teste próprio.',
      confianca: 0.71,
      video: 1,
      temas: [
        [3, 0.9],
        [1, 0.64],
      ],
      publicado_em: '2026-08-30T21:48:00Z',
      autor: 55,
    },
    {
      texto: 'frete de 60 conto num fone de 200, tá de sacanagem',
      sentimento: 'negativo',
      justificativa: 'Crítica ao custo do frete em relação ao valor do produto.',
      confianca: 0.93,
      video: 1,
      temas: [
        [2, 0.91],
        [0, 0.52],
      ],
      publicado_em: '2026-08-29T10:33:00Z',
      autor: 56,
    },
    {
      texto: 'video salvou minha carteira, ia comprar a tv errada. obrigado!!',
      sentimento: 'positivo',
      justificativa: 'Agradecimento por orientação que evitou compra equivocada.',
      confianca: 0.95,
      video: 0,
      temas: [
        [1, 0.79],
        [3, 0.55],
      ],
      publicado_em: '2026-09-03T18:27:00Z',
      autor: 57,
    },
    {
      texto: 'chegou em 3 dias, nem acreditei. dessa vez os correios não decepcionaram',
      sentimento: 'positivo',
      justificativa: 'Elogio ao prazo de entrega, acima da expectativa declarada.',
      confianca: 0.9,
      video: 0,
      temas: [[2, 0.93]],
      publicado_em: '2026-09-07T08:51:00Z',
      autor: 58,
    },
    {
      texto: 'alguem comparou com o da xiaomi? to na duvida entre os dois',
      sentimento: 'neutro',
      justificativa: 'Pedido de comparação entre marcas, sem opinião formada.',
      confianca: 0.92,
      video: 1,
      temas: [[3, 0.95]],
      publicado_em: '2026-08-31T14:19:00Z',
      autor: 59,
    },
    {
      texto: 'o link do cupom ta quebrado, alguem tem outro?',
      sentimento: 'neutro',
      justificativa: 'Relato de link inválido com pedido de alternativa.',
      confianca: 0.88,
      video: 0,
      temas: [[4, 0.92]],
      publicado_em: '2026-09-05T12:36:00Z',
      autor: 60,
    },
    {
      texto: 'melhor canal de tecnologia do br, sempre honesto sobre o que não presta',
      sentimento: 'positivo',
      justificativa: 'Elogio à credibilidade do canal, não a um produto específico.',
      confianca: 0.97,
      video: 3,
      temas: [[1, 0.61]],
      publicado_em: '2026-09-06T19:02:00Z',
      autor: 61,
    },
    {
      texto: 'comprei achando que era 50% off e era 12%. li errado ou eles escreveram errado?',
      sentimento: 'neutro',
      justificativa: 'Dúvida sobre o desconto anunciado, sem acusação direta.',
      confianca: 0.57,
      video: 3,
      temas: [[0, 0.89]],
      publicado_em: '2026-09-08T15:44:00Z',
      autor: 62,
    },
  ],
};

export const EXECUCOES_DEMO: readonly SementeExecucao[] = [JOALHERIA, BLACK_FRIDAY];

// ---------------------------------------------------------------------------
// Montagem: semente -> contrato
// ---------------------------------------------------------------------------

function distribuicao([positivo, neutro, negativo]: Dist): DistribuicaoSentimento {
  return { positivo, neutro, negativo, total: positivo + neutro + negativo };
}

/**
 * Hash fictício no formato de um SHA-256.
 *
 * Não é criptográfico e não precisa ser: o campo nunca é exibido, só existe
 * para o contrato ficar igual ao da tabela COMENTARIOS.
 */
function autorHash(autor: number): string {
  let h = 0x811c9dc5;
  for (const codigo of `autor-demo-${autor}`) {
    h = Math.imul(h ^ codigo.charCodeAt(0), 0x01000193) >>> 0;
  }
  return Array.from({ length: 8 }, (_, i) =>
    ((h * (i + 1)) >>> 0).toString(16).padStart(8, '0'),
  ).join('');
}

function montarVideos(semente: SementeExecucao): Video[] {
  return semente.videos.map((v, indice) => ({
    id_video: semente.id_execucao * 100 + indice + 1,
    id_execucao: semente.id_execucao,
    youtube_video_id: v.youtube_video_id,
    titulo: v.titulo,
    canal: v.canal,
    publicado_em: v.publicado_em,
    visualizacoes: v.visualizacoes,
    curtidas: v.curtidas,
  }));
}

function montarTemas(semente: SementeExecucao): Tema[] {
  return semente.temas.map((t, indice) => ({
    id_tema: semente.id_execucao * 100 + indice + 1,
    id_execucao: semente.id_execucao,
    rotulo_tema: t.rotulo,
    palavras_chave: t.palavras,
  }));
}

/** COMENTARIOS + ANALISES_SENTIMENTO + COMENTARIO_TEMA, já juntos. */
export function montarComentarios(semente: SementeExecucao): ComentarioAnalisado[] {
  const videos = montarVideos(semente);
  const temas = montarTemas(semente);

  return semente.comentarios.map((c, indice) => {
    const id = semente.id_execucao * 1000 + indice + 1;
    const video = videos[c.video];

    const comentario: Comentario = {
      id_comentario: id,
      id_video: video.id_video,
      youtube_comment_id: `Ug${autorHash(c.autor).slice(0, 20)}${indice}`,
      autor_hash: autorHash(c.autor),
      texto: c.texto,
      publicado_em: c.publicado_em,
    };

    const analise: AnaliseSentimento = {
      id_analise: id,
      id_comentario: id,
      id_versao_modelo: VERSAO_MODELO.id_versao,
      sentimento: c.sentimento,
      tema: temas[c.temas[0][0]].rotulo_tema,
      justificativa: c.justificativa,
      processado_em: semente.concluido_em,
      confianca: c.confianca,
    };

    return {
      comentario,
      analise,
      video: {
        id_video: video.id_video,
        youtube_video_id: video.youtube_video_id,
        titulo: video.titulo,
      },
      temas: c.temas.map(([indiceTema, peso]) => ({
        id_tema: temas[indiceTema].id_tema,
        rotulo_tema: temas[indiceTema].rotulo_tema,
        peso,
      })),
    };
  });
}

function montarAlcance(semente: SementeExecucao, comentarios: number): AlcanceExecucao {
  const visualizacoes = semente.videos.reduce((soma, v) => soma + v.visualizacoes, 0);
  return {
    visualizacoes,
    curtidas: semente.videos.reduce((soma, v) => soma + v.curtidas, 0),
    comentarios,
    comentarios_por_mil_views: Number((comentarios / (visualizacoes / 1000)).toFixed(1)),
  };
}

export function montarResultado(semente: SementeExecucao): ResultadoExecucao {
  const videos = montarVideos(semente);
  const temas = montarTemas(semente);

  const porVideo: VideoComSentimento[] = videos.map((video, indice) => ({
    video,
    distribuicao: distribuicao(semente.videos[indice].dist),
  }));

  const porTema: TemaComSentimento[] = temas.map((tema, indice) => ({
    tema,
    distribuicao: distribuicao(semente.temas[indice].dist),
  }));

  // O total da execução é a soma dos vídeos: um comentário pertence a um vídeo
  // só. Somar os temas daria mais, porque um comentário pode ter dois temas.
  const geral = porVideo.reduce(
    (acumulado, { distribuicao: d }) => ({
      positivo: acumulado.positivo + d.positivo,
      neutro: acumulado.neutro + d.neutro,
      negativo: acumulado.negativo + d.negativo,
      total: acumulado.total + d.total,
    }),
    { positivo: 0, neutro: 0, negativo: 0, total: 0 },
  );

  const comentarios = montarComentarios(semente);
  const representativo = (sentimento: Sentimento) =>
    comentarios.find((c) => c.analise.sentimento === sentimento);

  return {
    id_execucao: semente.id_execucao,
    id_modelo: semente.id_modelo,
    nome_modelo_analise: semente.nome,
    concluido_em: semente.concluido_em,
    distribuicao: geral,
    alcance: montarAlcance(semente, geral.total),
    videos: porVideo,
    temas: porTema,
    comentarios_representativos: [
      representativo('positivo'),
      representativo('negativo'),
      representativo('neutro'),
    ].filter((c): c is ComentarioAnalisado => c !== undefined),
    ponto_de_atencao: {
      id_tema: temas[semente.atencao.tema].id_tema,
      rotulo_tema: temas[semente.atencao.tema].rotulo_tema,
      texto: semente.atencao.texto,
    },
    versao_modelo: VERSAO_MODELO,
  };
}

/** Índice por id, para os serviços mock não varrerem a lista toda. */
export const RESULTADOS_DEMO: ReadonlyMap<number, ResultadoExecucao> = new Map(
  EXECUCOES_DEMO.map((semente) => [semente.id_execucao, montarResultado(semente)]),
);

export const COMENTARIOS_DEMO: ReadonlyMap<number, ComentarioAnalisado[]> = new Map(
  EXECUCOES_DEMO.map((semente) => [semente.id_execucao, montarComentarios(semente)]),
);

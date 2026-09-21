/**
 * Datas para leitura humana, em pt-BR (design/Execucoes.png: "hoje, 14:32",
 * "ontem, 09:15", "12 set, 16:44").
 *
 * Usa `Intl` direto em vez do `DatePipe`: o pipe exigiria registrar o locale
 * pt-BR no bootstrap e ainda assim não daria o "hoje/ontem".
 */

const HORA = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' });
const DIA_MES = new Intl.DateTimeFormat('pt-BR', { day: 'numeric', month: 'short' });
const DIA_MES_ANO = new Intl.DateTimeFormat('pt-BR', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
});

/**
 * O backend devolve UTC; `datetime` sem offset (caso do SQLite) o JavaScript
 * leria como hora local, adiantando ou atrasando o relógio da tela.
 */
function comoData(iso: string): Date {
  const temFuso = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(temFuso ? iso : `${iso}Z`);
}

function diasDeDiferenca(data: Date, agora: Date): number {
  const meiaNoite = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.round((meiaNoite(agora) - meiaNoite(data)) / 86_400_000);
}

/** `null` vira travessão: a coluna some sem quebrar o alinhamento da tabela. */
export function dataHoraLegivel(iso: string | null, agora = new Date()): string {
  if (!iso) {
    return '—';
  }

  const data = comoData(iso);
  if (Number.isNaN(data.getTime())) {
    return '—';
  }

  const hora = HORA.format(data);
  const dias = diasDeDiferenca(data, agora);

  if (dias === 0) {
    return `hoje, ${hora}`;
  }
  if (dias === 1) {
    return `ontem, ${hora}`;
  }

  const formatador = data.getFullYear() === agora.getFullYear() ? DIA_MES : DIA_MES_ANO;
  // O Intl abrevia com ponto ("12 de set."); aqui o formato do design é mais seco.
  return `${formatador.format(data).replace(/\./g, '').replace(' de ', ' ')}, ${hora}`;
}

/** Só a data, para "criado em" — hora ali não acrescenta nada. */
export function dataLegivel(iso: string | null, agora = new Date()): string {
  if (!iso) {
    return '—';
  }
  const data = comoData(iso);
  if (Number.isNaN(data.getTime())) {
    return '—';
  }
  const formatador = data.getFullYear() === agora.getFullYear() ? DIA_MES : DIA_MES_ANO;
  return formatador.format(data).replace(/\./g, '').replace(' de ', ' ');
}

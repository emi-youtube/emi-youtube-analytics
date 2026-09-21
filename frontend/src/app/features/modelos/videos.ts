/** Leitura do textarea de IDs de vídeo do formulário de modelo (UC02). */

/** IDs do YouTube têm 11 caracteres do alfabeto base64url. */
const ID_VALIDO = /^[A-Za-z0-9_-]{11}$/;

/**
 * Formas de endereço de onde dá para tirar o ID.
 *
 * A dica do campo diz "o trecho depois de watch?v=", então é esperado que
 * alguém cole a URL inteira — recusar isso seria pedir edição manual de uma
 * lista de vinte linhas.
 */
const PADROES: readonly RegExp[] = [
  /[?&]v=([A-Za-z0-9_-]{11})/, // youtube.com/watch?v=ID
  /youtu\.be\/([A-Za-z0-9_-]{11})/, // youtu.be/ID
  /\/(?:shorts|embed|live)\/([A-Za-z0-9_-]{11})/, // /shorts/ID, /embed/ID, /live/ID
];

export interface VideosLidos {
  /** IDs válidos, sem repetição, na ordem em que aparecem. */
  ids: string[];
  /** Linhas que não viraram ID — vão de volta para o usuário, literais. */
  invalidas: string[];
}

function extrair(linha: string): string | null {
  const limpa = linha.trim();
  if (!limpa) {
    return null;
  }
  if (ID_VALIDO.test(limpa)) {
    return limpa;
  }
  for (const padrao of PADROES) {
    const achado = padrao.exec(limpa);
    if (achado) {
      return achado[1];
    }
  }
  return null;
}

/** Uma linha por vídeo; aceita ID puro ou endereço completo. */
export function lerVideos(texto: string): VideosLidos {
  const ids: string[] = [];
  const invalidas: string[] = [];

  for (const linha of texto.split(/\r?\n/)) {
    if (!linha.trim()) {
      continue;
    }
    const id = extrair(linha);
    if (!id) {
      invalidas.push(linha.trim());
    } else if (!ids.includes(id)) {
      // Repetido não é erro: coletar o mesmo vídeo duas vezes é que seria.
      ids.push(id);
    }
  }

  return { ids, invalidas };
}

/** Volta os IDs para o textarea, um por linha. */
export function escreverVideos(ids: readonly string[] | undefined): string {
  return (ids ?? []).join('\n');
}

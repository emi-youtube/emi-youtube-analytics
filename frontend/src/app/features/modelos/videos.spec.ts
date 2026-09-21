import { describe, expect, it } from 'vitest';

import { escreverVideos, lerVideos } from './videos';

describe('lerVideos', () => {
  it('aceita ID puro, um por linha', () => {
    expect(lerVideos('dQw4w9WgXcQ\nkJQP7kiw5Fk')).toEqual({
      ids: ['dQw4w9WgXcQ', 'kJQP7kiw5Fk'],
      invalidas: [],
    });
  });

  it('extrai o ID de endereços colados', () => {
    const texto = [
      'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
      'https://youtu.be/kJQP7kiw5Fk',
      'https://www.youtube.com/shorts/9bZkp7q19f0',
      'https://www.youtube.com/watch?t=30&v=CevxZvSJLk8',
    ].join('\n');

    expect(lerVideos(texto).ids).toEqual([
      'dQw4w9WgXcQ',
      'kJQP7kiw5Fk',
      '9bZkp7q19f0',
      'CevxZvSJLk8',
    ]);
  });

  it('ignora linhas em branco e repetições', () => {
    expect(lerVideos('dQw4w9WgXcQ\n\n  \ndQw4w9WgXcQ\n')).toEqual({
      ids: ['dQw4w9WgXcQ'],
      invalidas: [],
    });
  });

  it('devolve as linhas que não são vídeo, sem descartar as boas', () => {
    expect(lerVideos('dQw4w9WgXcQ\nisso-nao-e-um-id\ncurto')).toEqual({
      ids: ['dQw4w9WgXcQ'],
      invalidas: ['isso-nao-e-um-id', 'curto'],
    });
  });

  it('escreve de volta um por linha', () => {
    expect(escreverVideos(['a', 'b'])).toBe('a\nb');
    expect(escreverVideos(undefined)).toBe('');
  });
});

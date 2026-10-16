import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { AVISO_ACADEMICO } from '../../layout/aviso-academico';
import { Vitrine } from './vitrine';

describe('Vitrine', () => {
  it('as telas de acesso dizem que o sistema é um protótipo acadêmico, sem fins comerciais', () => {
    const fixture = TestBed.createComponent(Vitrine);
    fixture.detectChanges();
    const tela: HTMLElement = fixture.nativeElement;

    const aviso = tela.querySelector('.vitrine__rodape [data-testid="aviso-academico"]');
    expect(aviso?.textContent?.trim()).toBe(AVISO_ACADEMICO);
    // O aviso vem junto do selo do YouTube, no mesmo rodapé.
    expect(tela.querySelector('.vitrine__rodape [data-testid="selo-youtube"]')).not.toBeNull();
  });
});

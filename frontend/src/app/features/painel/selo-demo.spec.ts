import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { provideDadosDeDemonstracao, provideDadosReais } from '../../core/mock/mock.providers';
import { SeloDemo } from './selo-demo';

/**
 * O selo é requisito, não enfeite: nenhuma captura de tela pode mostrar número
 * de demonstração sem o aviso, e nenhum dado real pode sair marcado como
 * fictício. Estes dois testes prendem as duas pontas.
 */
describe('SeloDemo', () => {
  function montar(): ComponentFixture<SeloDemo> {
    const fixture = TestBed.createComponent(SeloDemo);
    fixture.detectChanges();
    return fixture;
  }

  it('aparece quando o mock está ligado', () => {
    TestBed.configureTestingModule({ providers: [provideDadosDeDemonstracao()] });

    const texto = montar().nativeElement.textContent as string;
    expect(texto).toContain('Dados de demonstração');
  });

  it('some quando a origem é a API real', () => {
    TestBed.configureTestingModule({ providers: [provideDadosReais()] });

    expect(montar().nativeElement.textContent.trim()).toBe('');
  });

  it('some também quando ninguém declarou a origem', () => {
    // Padrão do token: sem provider, a aplicação não é demonstração.
    TestBed.configureTestingModule({ providers: [] });

    expect(montar().nativeElement.textContent.trim()).toBe('');
  });
});

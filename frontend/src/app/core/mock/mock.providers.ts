import { EnvironmentProviders, InjectionToken, makeEnvironmentProviders } from '@angular/core';

import { ComentariosHttpService, ComentariosService } from '../api/comentarios.service';
import { PainelHttpService, PainelService } from '../api/painel.service';
import { ResultadosHttpService, ResultadosService } from '../api/resultados.service';
import { ComentariosMockService } from './comentarios.mock';
import { PainelMockService } from './painel.mock';
import { ResultadosMockService } from './resultados.mock';

/**
 * Verdadeiro quando as telas de análise estão servindo dados de demonstração.
 *
 * Quem decide é o provider escolhido em `app.config.ts`, e não uma constante
 * solta: assim é impossível trocar o mock pela API e esquecer o selo aceso, ou
 * o contrário. O componente `selo-demo` lê este token.
 */
export const DADOS_DE_DEMONSTRACAO = new InjectionToken<boolean>('DADOS_DE_DEMONSTRACAO', {
  providedIn: 'root',
  // Sem provider explícito, o padrão é "não é demonstração" — o selo só
  // aparece quando alguém liga o mock de propósito.
  factory: () => false,
});

/**
 * Liga o mock dos três recursos de análise.
 *
 * Enquanto este provider estiver em `app.config.ts`, Início, Resultados e
 * Comentários mostram o conjunto de `dados-demo.ts` e exibem o selo
 * "Dados de demonstração".
 */
export function provideDadosDeDemonstracao(): EnvironmentProviders {
  return makeEnvironmentProviders([
    { provide: DADOS_DE_DEMONSTRACAO, useValue: true },
    { provide: PainelService, useClass: PainelMockService },
    { provide: ResultadosService, useClass: ResultadosMockService },
    { provide: ComentariosService, useClass: ComentariosMockService },
  ]);
}

/**
 * Liga a API real. É a troca de uma linha em `app.config.ts`.
 *
 * Os endpoints precisam existir antes — a lista está no README. Nada mais
 * muda: as telas dependem das classes abstratas, não das implementações.
 */
export function provideDadosReais(): EnvironmentProviders {
  return makeEnvironmentProviders([
    { provide: DADOS_DE_DEMONSTRACAO, useValue: false },
    { provide: PainelService, useClass: PainelHttpService },
    { provide: ResultadosService, useClass: ResultadosHttpService },
    { provide: ComentariosService, useClass: ComentariosHttpService },
  ]);
}

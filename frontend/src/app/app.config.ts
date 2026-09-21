import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideClientHydration, withEventReplay } from '@angular/platform-browser';
import { provideRouter, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';

import { authInterceptor } from './core/auth/auth.interceptor';
import { provideDadosDeDemonstracao } from './core/mock/mock.providers';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(
      routes,
      // `data` da rota chega como input do componente (ver EmBreve).
      withComponentInputBinding(),
      withInMemoryScrolling({ scrollPositionRestoration: 'enabled' }),
    ),
    // `withFetch` é o que faz o HttpClient funcionar no SSR (XHR não existe no Node).
    provideHttpClient(withFetch(), withInterceptors([authInterceptor])),
    provideClientHydration(withEventReplay()),

    // ---------------------------------------------------------------------
    // Origem dos dados de análise (Início, Resultados, Comentários).
    //
    // Hoje: mock, porque o worker de inferência ainda não existe e não há
    // ANALISES_SENTIMENTO nem TEMAS no banco. Enquanto esta linha estiver
    // aqui, as três telas exibem o selo "Dados de demonstração".
    //
    // Para ligar a API real, troque por `provideDadosReais()` — e só. Os
    // endpoints que precisam existir antes estão listados no README.
    // ---------------------------------------------------------------------
    provideDadosDeDemonstracao(),
  ],
};

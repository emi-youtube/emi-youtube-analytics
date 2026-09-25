import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideClientHydration, withEventReplay } from '@angular/platform-browser';
import { provideRouter, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';

import { authInterceptor } from './core/auth/auth.interceptor';
import { provideDadosReais } from './core/mock/mock.providers';
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
    // API REAL. O worker de inferência existe e ANALISES_SENTIMENTO é
    // populada, então as três telas leem `GET /painel`,
    // `GET /execucoes/{id}/resultado` e `GET /execucoes/{id}/comentarios`.
    // O selo "Dados de demonstração" apaga sozinho: quem o acende é o token
    // DADOS_DE_DEMONSTRACAO, que este provider define como `false`.
    //
    // TEMAS continua vazio até o worker de tópicos existir — as telas tratam
    // isso como ausência, não como erro.
    // ---------------------------------------------------------------------
    provideDadosReais(),
  ],
};

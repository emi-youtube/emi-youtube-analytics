import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';

import { SKIP_AUTH } from './auth.context';
import { AuthService } from './auth.service';

function comBearer<T>(req: HttpRequest<T>, token: string | null): HttpRequest<T> {
  if (!token) {
    return req;
  }
  return req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}

/**
 * Anexa o access token e, no 401, tenta renovar uma vez.
 *
 * O access token expira em 15 min. Sem este interceptor, o usuário seria
 * expulso no meio do trabalho toda vez que o relógio virasse; aqui o 401 vira
 * um refresh transparente e a requisição original é repetida com o token novo.
 *
 * Se o refresh também falhar, a sessão acabou de verdade: limpa o estado e
 * manda para o login guardando a rota atual em `returnUrl`. O erro repassado
 * é o 401 original — quem chamou precisa ver a falha da sua requisição, não a
 * do refresh.
 */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  if (req.context.get(SKIP_AUTH)) {
    return next(req);
  }

  const auth = inject(AuthService);
  const router = inject(Router);

  return next(comBearer(req, auth.token())).pipe(
    catchError((erro: unknown) => {
      if (!(erro instanceof HttpErrorResponse) || erro.status !== 401) {
        return throwError(() => erro);
      }

      return auth.refreshAccessToken().pipe(
        switchMap((token) => next(comBearer(req, token))),
        catchError(() => {
          auth.clearSession();
          void router.navigate(['/login'], {
            queryParams: { returnUrl: router.url },
          });
          return throwError(() => erro);
        }),
      );
    }),
  );
};

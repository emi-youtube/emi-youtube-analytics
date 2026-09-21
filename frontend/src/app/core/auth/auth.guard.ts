import { isPlatformBrowser } from '@angular/common';
import { PLATFORM_ID, inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs';

import { AuthService } from './auth.service';

/**
 * Protege as telas internas.
 *
 * No servidor (SSR) não existe `localStorage`, então não há como saber se há
 * sessão. O guard libera a renderização — o HTML do servidor é só o esqueleto,
 * sem dado nenhum do usuário — e o Angular roda o guard de novo no navegador
 * durante a hidratação, que é quando a decisão real acontece.
 *
 * No navegador, quando não há access token em memória (caso típico de F5),
 * `ensureSession()` tenta reconstruir a sessão pelo refresh token antes de
 * desistir.
 */
export const authGuard: CanActivateFn = (_route, state) => {
  const router = inject(Router);
  const auth = inject(AuthService);

  if (!isPlatformBrowser(inject(PLATFORM_ID))) {
    return true;
  }

  if (auth.isAuthenticated()) {
    return true;
  }

  return auth
    .ensureSession()
    .pipe(
      map((autenticado) =>
        autenticado
          ? true
          : router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } }),
      ),
    );
};

/**
 * Inverso do `authGuard`: quem já está logado não precisa ver o login de novo.
 */
export const guestGuard: CanActivateFn = () => {
  const router = inject(Router);
  const auth = inject(AuthService);

  if (!isPlatformBrowser(inject(PLATFORM_ID))) {
    return true;
  }

  if (auth.isAuthenticated()) {
    return router.createUrlTree(['/inicio']);
  }

  return auth
    .ensureSession()
    .pipe(map((autenticado) => (autenticado ? router.createUrlTree(['/inicio']) : true)));
};

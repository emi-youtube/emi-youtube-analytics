import { HttpContext, HttpContextToken } from '@angular/common/http';

/**
 * Marca requisições que o `authInterceptor` deve deixar passar cru: sem anexar
 * `Authorization` e sem tentar refresh no 401.
 *
 * Vale para os próprios endpoints de autenticação. Sem isso, um 401 do
 * `POST /auth/login` (senha errada) dispararia um refresh — e o 401 do
 * `POST /auth/refresh` (token revogado) dispararia outro, em laço.
 *
 * Fica em arquivo separado de propósito: `AuthService` e `authInterceptor`
 * dependem dos dois lados, e importar um do outro criaria ciclo.
 */
export const SKIP_AUTH = new HttpContextToken<boolean>(() => false);

export function skipAuth(): HttpContext {
  return new HttpContext().set(SKIP_AUTH, true);
}

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

/**
 * Anexa o access token, mas NÃO renova no 401.
 *
 * Para rotas em que o 401 quer dizer "senha errada", não "sessão vencida"
 * (`DELETE /conta`). Renovar e repetir trataria a senha errada como sessão
 * morta — e o segundo 401 levaria ao logout. Quem usa garante antes um access
 * token fresco (`AuthService.refreshAccessToken`).
 */
export const SEM_RENOVAR = new HttpContextToken<boolean>(() => false);

export function semRenovar(): HttpContext {
  return new HttpContext().set(SEM_RENOVAR, true);
}

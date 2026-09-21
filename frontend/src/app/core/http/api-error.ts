import { HttpErrorResponse } from '@angular/common/http';

interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/**
 * Converte o erro do FastAPI em uma frase para a tela.
 *
 * O backend responde em dois formatos: `{"detail": "texto"}` nos erros de
 * regra de negócio e `{"detail": [{loc, msg, type}]}` na validação (422) —
 * ver o `validation_exception_handler` em `backend/app/main.py`.
 */
export function mensagemDeErro(
  erro: unknown,
  padrao = 'Não foi possível concluir. Tente de novo.',
): string {
  if (!(erro instanceof HttpErrorResponse)) {
    return padrao;
  }

  // status 0 = requisição nem saiu (backend fora do ar, CORS, offline).
  if (erro.status === 0) {
    return 'Não foi possível falar com o servidor. Verifique sua conexão.';
  }

  const detail = (erro.error as { detail?: unknown } | null)?.detail;

  if (typeof detail === 'string') {
    return detail;
  }

  if (Array.isArray(detail)) {
    const issues = detail as ValidationIssue[];
    const primeira = issues.find((issue) => typeof issue?.msg === 'string');
    if (primeira) {
      return primeira.msg;
    }
  }

  return padrao;
}

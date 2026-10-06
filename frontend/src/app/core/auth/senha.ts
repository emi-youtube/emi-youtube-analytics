import { AbstractControl, ValidationErrors } from '@angular/forms';

/**
 * Regras de senha usadas no cadastro, na troca e na redefinição.
 *
 * Mesmo mínimo de `SENHA_MIN_CARACTERES` em `backend/app/schemas/auth.py`; o
 * servidor valida de novo, isto só antecipa o aviso na tela.
 */
export const SENHA_MINIMA = 8;

/**
 * Valida a confirmação contra a senha.
 *
 * Fica no grupo, e não no campo, porque depende de dois controles: um
 * validador de campo não enxerga o irmão. `campo` diz qual é a senha do grupo
 * (`senha` no cadastro, `nova_senha` na troca e na redefinição).
 */
export function senhasConferem(campo = 'senha') {
  return (grupo: AbstractControl): ValidationErrors | null => {
    const senha = grupo.get(campo)?.value;
    const confirmacao = grupo.get('confirmacao')?.value;

    // Com a confirmação ainda vazia o erro é "obrigatório", não "diferente" —
    // acusar divergência enquanto a pessoa digita seria só ruído.
    if (!confirmacao || senha === confirmacao) {
      return null;
    }
    return { senhasDiferentes: true };
  };
}

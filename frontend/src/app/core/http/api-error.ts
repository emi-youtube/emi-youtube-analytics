import { HttpErrorResponse } from '@angular/common/http';

interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/**
 * Rótulo em português de cada campo que o backend valida.
 *
 * Só serve para compor a frase do 422: sem o nome do campo, "Informe ao menos
 * 8 caracteres." não diz de qual dos quatro campos se trata.
 */
const ROTULOS_DE_CAMPO: Record<string, string> = {
  nome: 'Nome',
  email: 'E-mail',
  senha: 'Senha',
};

/**
 * Prefixo que o Pydantic v2 põe na frente da mensagem de um validador nosso
 * (`Value error, A senha deve ter ao menos 8 caracteres.`). O texto depois da
 * vírgula já está em português — só o prefixo precisa cair.
 */
const PREFIXO_PYDANTIC = /^(value error|assertion failed),\s*/i;

/**
 * Mensagens de validação que o Pydantic emite em inglês.
 *
 * O backend escreve as regras de negócio em português, mas as validações
 * embutidas (`EmailStr`, `min_length`, campo obrigatório) vêm da biblioteca e
 * chegariam em inglês na tela.
 */
const TRADUCOES: readonly { de: RegExp; para: string }[] = [
  { de: /^field required$/i, para: 'Campo obrigatório.' },
  { de: /^input should be a valid string$/i, para: 'Informe um texto válido.' },
  { de: /^value is not a valid email address.*$/i, para: 'Informe um e-mail válido.' },
  { de: /^string should have at least 1 character$/i, para: 'Campo obrigatório.' },
  {
    de: /^string should have at least (\d+) characters$/i,
    para: 'Informe ao menos $1 caracteres.',
  },
  {
    de: /^string should have at most (\d+) characters?$/i,
    para: 'Use no máximo $1 caracteres.',
  },
];

/** Status HTTP da resposta, ou `null` se o erro não veio do `HttpClient`. */
export function statusDoErro(erro: unknown): number | null {
  return erro instanceof HttpErrorResponse ? erro.status : null;
}

/**
 * `generica` diz se a frase veio da tabela acima.
 *
 * Mensagem nossa já nomeia o campo ("A senha deve ter ao menos 8
 * caracteres."); só a genérica precisa do rótulo na frente, senão sairia
 * "Senha: a senha deve ter...".
 */
function traduzir(msg: string): { texto: string; generica: boolean } {
  const limpa = msg.replace(PREFIXO_PYDANTIC, '');
  const traducao = TRADUCOES.find((item) => item.de.test(limpa));
  return traducao
    ? { texto: limpa.replace(traducao.de, traducao.para), generica: true }
    : { texto: limpa, generica: false };
}

/** `["body", "senha"]` -> `"Senha"`; `["body"]` ou campo desconhecido -> `null`. */
function rotuloDoCampo(loc: (string | number)[] | undefined): string | null {
  const campo = loc?.at(-1);
  return typeof campo === 'string' ? (ROTULOS_DE_CAMPO[campo] ?? null) : null;
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
    return traduzir(detail).texto;
  }

  if (Array.isArray(detail)) {
    const issues = detail as ValidationIssue[];
    const primeira = issues.find((issue) => typeof issue?.msg === 'string');
    if (primeira) {
      const { texto, generica } = traduzir(primeira.msg);
      const rotulo = generica ? rotuloDoCampo(primeira.loc) : null;
      return rotulo ? `${rotulo}: ${texto.charAt(0).toLowerCase()}${texto.slice(1)}` : texto;
    }
  }

  // 5xx sem corpo útil: a mensagem padrão da tela fala de "tente de novo", que
  // é o que cabe aqui — o usuário não tem o que corrigir.
  return padrao;
}

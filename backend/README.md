# Backend — API (FastAPI)

Todas as rotas ficam sob `/api/v1`. Autenticação por `Authorization: Bearer <access>`
(JWT próprio, 15 min); o refresh (7 dias) é rotacionado a cada uso.

**Isolamento por empresa (ADR-011, `docs/BANCO.md`).** Modelos, execuções e
resultados pertencem à EMPRESA de quem está logado. Recurso de outra empresa
responde **404**, como um id que não existe.

## Rodar e testar

```bash
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload            # API em http://localhost:8000
pytest                                    # SQLite em memória
ruff check . && ruff format --check app tests

# Só contra Postgres (pulados sem as variáveis):
EMI_TESTE_POSTGRES_URL=postgresql+asyncpg://...  pytest tests/test_rls.py     # só lê o catálogo
EMI_TESTE_MIGRACAO_URL=postgresql+asyncpg://...  pytest tests/test_migracao_0011.py  # DESTRUTIVO: banco descartável
```

## Rotas

### Autenticação — `/auth`

| Método e rota | Auth | O que faz |
|---|---|---|
| `POST /auth/registrar` | — | cria conta: com `nome_empresa`, cria a empresa e entra como **dono**; com `token_convite`, entra na empresa do convite (o e-mail tem de ser o do convite) |
| `POST /auth/convites/consultar` | — | `{token}` → e-mail, empresa e papel de um convite pendente (o cadastro trava o e-mail); 404 se inválido |
| `POST /auth/login` | — | par access + refresh; mesma resposta para e-mail inexistente e senha errada; bloqueio de 15 min após 5 falhas em 10 min |
| `POST /auth/refresh` | — | **rotação**: devolve um par novo e invalida o refresh enviado; reenviar um refresh já trocado revoga todos os do usuário (401) |
| `POST /auth/logout` | — | revoga o refresh enviado |
| `GET /auth/eu` | sim | o usuário, com `papel_empresa` e `empresa {id_empresa, nome}` |
| `POST /auth/trocar-senha` | sim | `{senha_atual, nova_senha}`; revoga todos os refresh e devolve um par novo para a sessão atual |
| `POST /auth/esqueci-senha` | — | sempre **202** e o mesmo corpo; envia o link (30 min, uso único) se a conta existir; 429 após 5 pedidos por IP em 15 min |
| `POST /auth/redefinir-senha` | — | `{token, nova_senha}`; revoga todos os refresh e zera o bloqueio por tentativas |

### Empresa — `/empresa`

| Método e rota | Quem | O que faz |
|---|---|---|
| `GET /empresa/membros` | qualquer membro | membros da empresa |
| `DELETE /empresa/membros/{id_usuario}` | dono | remove (apaga a conta; os modelos que a pessoa criou passam para quem removeu). Não remove a si mesmo nem o último dono |
| `GET /empresa/convites` | dono | convites pendentes (sem o token) |
| `POST /empresa/convites` | dono | `{email, papel_empresa}` → convite de 7 dias e uso único; o `link` volta só nesta resposta e vai por e-mail. 409 com a empresa lotada (10 membros, contando pendentes) |
| `DELETE /empresa/convites/{id_convite}` | dono | revoga um convite pendente |

Membro que chama rota de dono recebe **403** (ele está na própria empresa; não há
existência alheia a esconder).

### Modelos, execuções, resultados, painel

| Método e rota | O que faz |
|---|---|
| `GET/POST /modelos-analise`, `GET/PATCH/DELETE /modelos-analise/{id}` | modelos da empresa (UC02) |
| `POST /execucoes` | 202 e enfileira a coleta (UC03) |
| `GET /execucoes`, `GET /execucoes/{id}` | execuções da empresa (UC04) |
| `GET /execucoes/resultados` | execuções concluídas da empresa |
| `GET /execucoes/{id}/resultado` | tela Resultados e relatório exportável (UC06) |
| `GET /execucoes/{id}/comentarios` | comentários analisados, paginados e filtrados |
| `GET /painel` | resumo da tela Início |
| `GET /health` | API e banco de pé |

## Variáveis de ambiente

Ver `env.example` na raiz. As de e-mail (`EMAIL_PROVEDOR`, `RESEND_API_KEY`,
`EMAIL_REMETENTE`, `FRONTEND_URL`) e `EMPRESA_MAX_MEMBROS` estão explicadas em
`docs/DEPLOY.md`, passo B.2.

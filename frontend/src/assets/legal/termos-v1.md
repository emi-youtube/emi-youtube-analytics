# Emi YouTube Analytics — Termos de Uso e Política de Privacidade

Versão 1.0 — vigente a partir de 06/10/2026. Projeto acadêmico (TCC) da Universidade Paulista (UNIP).

O Emi é uma plataforma que coleta os comentários dos seus vídeos publicitários, veja a divisão entre positivo, negativo e neutro, e descubra os temas que mais se repetem.

## 1. Sobre o sistema

O Emi YouTube Analytics é um sistema acadêmico que coleta comentários públicos de vídeos do YouTube indicados pelo usuário, classifica cada comentário como positivo, negativo ou neutro e agrupa os comentários em temas. O resultado é mostrado em um painel e em um relatório. Ele é um protótipo de pesquisa, oferecido sem garantia de disponibilidade.

## 2. Uso permitido

- Usar o sistema para analisar vídeos públicos, de forma legal e de boa-fé.

- Manter a senha em sigilo e responder pela conta e pelos membros que convidar para a sua empresa.

- Respeitar os Termos de Serviço do YouTube e da YouTube Data API.

- Não tentar acessar dados de outras empresas, burlar limites ou sobrecarregar o sistema.

## 3. O que a análise é e não é

O sistema analisa os comentários coletados, não a opinião de todo o público do vídeo, nem a eficácia comercial da campanha. A classificação é feita por um modelo de IA (BERTimbau ajustado) que erra: no teste com rótulos humanos, a medida F1 macro foi de 0,73. Use os resultados como apoio à decisão, não como verdade absoluta. Os limites aparecem no relatório.

## 4. Dados que tratamos (LGPD — Lei 13.709/2018)

Controladores: a equipe do projeto GIOVANA FONSECA BATSCHER, GIOVANNE DA SILVA BORDOTTI, JOÃO ANTÔNIO MARQUES.S. DE SOUZA, LUAN DONATO MEDEIROS MORENO e a orientadora, no contexto do TCC. Contato do encarregado: emi.youtube.analytics@gmail.com.

| Dado | Finalidade | Base legal (art. 7º) | Observação |
|---|---|---|---|
| E-mail, senha e nome da empresa | Criar e proteger a conta, separar os dados por empresa | Execução do serviço solicitado (inc. V) | Senha guardada só como hash (bcrypt) |
| Termos aceitos (versão e data) | Comprovar o consentimento aos termos | Cumprimento de obrigação / legítimo interesse | Registrado no cadastro |
| Comentários públicos do YouTube | Classificar sentimentos e agrupar temas | Legítimo interesse acadêmico; dado tornado público (§4º) | O nome do autor não é guardado: apenas um código SHA-256 (pseudonimização) |
| Registros técnicos (logs, tentativas de login) | Segurança e prevenção de fraude | Legítimo interesse (inc. IX) | Mantidos por prazo curto |
| Respostas da validação (se participar) | Pesquisa acadêmica | Consentimento (inc. I), pelo TCLE | Tratadas em documento próprio |

Importante: o código irreversível do autor é pseudonimização, não anonimização completa; por isso tratamos esses dados com cuidado e não os exibimos nos relatórios.

## 5. Com quem os dados passam

- Supabase (banco de dados, região São Paulo, Brasil).

- Microsoft Azure (execução da API e dos processos, região México Central).

- Vercel (entrega do site; pode processar dados nos EUA).

- YouTube Data API (Google), para obter comentários públicos.

- Hugging Face (apenas para baixar o modelo; nenhum comentário é enviado).

Os comentários não são enviados a serviços de IA de terceiros na classificação: o modelo roda no nosso servidor. Os provedores acima são operadores e, portanto, também são terceiros; parte deles trata dados fora do Brasil, com salvaguardas contratuais dos próprios provedores (LGPD, art. 33).

## 6. Quanto tempo guardamos

Dados da conta: enquanto a conta existir. Comentários e resultados: até 3 meses após a execução, quando são excluídos. O expurgo automático ainda será implementado; até lá, a exclusão é feita sob pedido. Ao fim do projeto acadêmico, os dados de teste serão excluídos ou anonimizados.

Corpus de pesquisa: os textos de comentários públicos usados no treinamento e na avaliação do modelo, com o autor pseudonimizado, pertencem ao projeto acadêmico e não à empresa; por isso permanecem depois da exclusão de uma conta ou empresa e não são publicados com identificação do autor.

## 7. Seus direitos

Você pode pedir confirmação do tratamento, acesso, correção, exclusão, portabilidade, informação sobre compartilhamento e revogação do consentimento (LGPD, art. 18), escrevendo para emi.youtube.analytics@gmail.com. Responderemos em até 15 dias. Também pode reclamar à ANPD.

## 8. Segurança

Senhas com bcrypt, sessões curtas (15 minutos) com renovação, bloqueio após tentativas falhas, bancos com acesso restrito (RLS) e separação de dados entre empresas. Nenhum sistema é totalmente seguro; em caso de incidente relevante avisaremos os afetados.

## 9. Limitações de responsabilidade

Por ser um protótipo acadêmico, o sistema pode ficar indisponível ou ser desativado ao fim do projeto. Os resultados são informativos e a equipe não responde por decisões comerciais tomadas com base neles.

## 10. Alterações e contato

Mudanças nestes termos geram nova versão e novo aceite. Dúvidas: emi.youtube.analytics@gmail.com.

# Emi YouTube Analytics — Termos de Uso e Política de Privacidade

Versão 1.2 — vigente a partir de 10/10/2026. Projeto acadêmico (TCC) da Universidade Paulista (UNIP).

O Emi é uma plataforma que coleta os comentários dos seus vídeos publicitários, mostra a divisão entre positivo, negativo e neutro e descobre os temas que mais se repetem.

## 1. Sobre o sistema

O Emi YouTube Analytics é um sistema acadêmico que coleta comentários públicos de vídeos do YouTube indicados pelo usuário, classifica cada comentário como positivo, negativo ou neutro e agrupa os comentários em temas. O resultado é mostrado em um painel e em um relatório. Ele é um protótipo de pesquisa, oferecido sem garantia de disponibilidade.

O Emi usa os YouTube API Services, serviços do Google, para obter os comentários e os dados dos vídeos. **Ao usar o Emi, você concorda em seguir os [Termos de Serviço do YouTube](https://www.youtube.com/t/terms).**

## 2. Uso permitido

- Usar o sistema para analisar vídeos públicos, de forma legal e de boa-fé.

- Manter a senha em sigilo e responder pela conta e pelos membros que convidar para a sua empresa.

- Respeitar os [Termos de Serviço do YouTube](https://www.youtube.com/t/terms) e as políticas da YouTube Data API.

- Não tentar acessar dados de outras empresas, burlar limites ou sobrecarregar o sistema.

- Não usar os resultados para deduzir características pessoais de quem comentou, como idade, origem, religião, posição política, orientação sexual ou saúde.

## 3. O que a análise é e não é

O sistema analisa os comentários coletados, não a opinião de todo o público do vídeo, nem a eficácia comercial da campanha. A classificação é feita por um modelo de IA (BERTimbau ajustado) que erra: no teste com rótulos humanos, a medida F1 macro foi de 0,73. Use os resultados como apoio à decisão, não como verdade absoluta. Os limites aparecem no relatório.

Os percentuais de sentimento, os temas e os indicadores são calculados pelo Emi; não são métricas publicadas pelo YouTube. As visualizações e curtidas mostradas vêm do YouTube, como estavam no momento da coleta.

## 4. Dados que tratamos (LGPD — Lei 13.709/2018)

Controladores: a equipe do projeto GIOVANA FONSECA BATSCHER, GIOVANNE DA SILVA BORDOTTI, JOÃO ANTÔNIO MARQUES.S. DE SOUZA, LUAN DONATO MEDEIROS MORENO e a orientadora, no contexto do TCC. Contato do encarregado: emi.youtube.analytics@gmail.com.

O Emi usa os YouTube API Services. Os dados obtidos por eles também estão sujeitos à [Política de Privacidade do Google](https://www.google.com/policies/privacy).

| Dado | Finalidade | Base legal (art. 7º) | Observação |
|---|---|---|---|
| E-mail, senha e nome da empresa | Criar e proteger a conta, separar os dados por empresa, confirmar o e-mail no cadastro, enviar convites e links de redefinição de senha | Execução do serviço solicitado (inc. V) | Senha guardada só como hash (bcrypt) |
| Termos aceitos (versão e data) | Comprovar o consentimento aos termos | Cumprimento de obrigação / legítimo interesse | Registrado no cadastro |
| Comentários públicos do YouTube (texto e data) | Classificar sentimentos e agrupar temas | Legítimo interesse acadêmico; dado tornado público (§4º) | Obtidos pelos YouTube API Services. O nome do autor não é guardado: apenas um código SHA-256 (pseudonimização) |
| Dados públicos dos vídeos (título, canal, data, visualizações e curtidas) | Identificar os vídeos analisados e calcular indicadores | Legítimo interesse acadêmico; dado tornado público (§4º) | Obtidos pelos YouTube API Services |
| Resultados da análise (sentimento de cada comentário, percentuais, temas) | Mostrar o painel e o relatório | Execução do serviço solicitado (inc. V) | Calculados pelo Emi a partir dos comentários |
| Registros técnicos (logs, tentativas de login) | Segurança e prevenção de fraude | Legítimo interesse (inc. IX) | Mantidos por prazo curto |
| Respostas da validação (se participar) | Pesquisa acadêmica | Consentimento (inc. I), pelo TCLE | Tratadas em documento próprio |

Importante: o código irreversível do autor é pseudonimização, não anonimização completa; por isso tratamos esses dados com cuidado e não os exibimos nos relatórios.

No seu navegador, o Emi guarda apenas o código da sessão (armazenamento local), para manter você conectado; ele sai quando você encerra a sessão. O Emi não usa cookies de rastreamento, não exibe anúncios e não permite que terceiros sirvam conteúdo nas suas páginas.

## 5. Com quem os dados passam

- Supabase (banco de dados, região São Paulo, Brasil).

- Microsoft Azure (execução da API e dos processos, região México Central).

- Vercel (entrega do site; pode processar dados nos EUA).

- YouTube API Services (Google), para obter os comentários públicos e os dados dos vídeos. Ver a [Política de Privacidade do Google](https://www.google.com/policies/privacy).

- Hugging Face (apenas para baixar o modelo; nenhum comentário é enviado).

- Resend (envio dos e-mails de confirmação de cadastro, de convite e de redefinição de senha; recebe o endereço de quem recebe e o texto da mensagem; pode processar dados fora do Brasil).

Os comentários não são enviados a serviços de IA de terceiros na classificação: o modelo roda no nosso servidor. Os provedores acima são operadores e, portanto, também são terceiros; parte deles trata dados fora do Brasil, com salvaguardas contratuais dos próprios provedores (LGPD, art. 33).

## 6. Quanto tempo guardamos

As políticas dos YouTube API Services limitam o tempo de guarda do que vem do YouTube, e o Emi segue esses prazos automaticamente:

- **Texto dos comentários:** apagado em até 30 dias depois da coleta. A partir daí, a análise continua mostrando os percentuais, os temas e os indicadores, mas não os comentários. Para lê-los de novo, é preciso refazer a análise, o que faz uma coleta nova.

- **Título do vídeo e nome do canal:** atualizados junto ao YouTube antes de completarem 30 dias. Se o vídeo sair do ar ou a atualização não for possível, são apagados.

- **Resultados da análise, visualizações e curtidas da coleta:** até 36 meses depois da coleta.

- **Dados da conta:** enquanto a conta existir.

- **Pedido de cadastro não confirmado:** apagado depois de 24 horas.

Corpus de pesquisa: os textos de comentários públicos usados no treinamento e na avaliação do modelo, com o autor pseudonimizado, pertencem ao projeto acadêmico e não à empresa. Eles são guardados só até a conclusão do TCC, quando são excluídos, e não são publicados.

## 7. Seus direitos

Você pode pedir confirmação do tratamento, acesso, correção, exclusão, portabilidade, informação sobre compartilhamento e revogação do consentimento (LGPD, art. 18), escrevendo para emi.youtube.analytics@gmail.com. Responderemos em até 15 dias; pedidos de exclusão dos dados obtidos do YouTube são atendidos em até 7 dias. Excluir dados no Emi não apaga nada no próprio YouTube. Também pode reclamar à ANPD.

## 8. Segurança

Senhas com bcrypt, sessões curtas (15 minutos) com renovação, bloqueio após tentativas falhas, bancos com acesso restrito (RLS) e separação de dados entre empresas. Nenhum sistema é totalmente seguro; em caso de incidente relevante avisaremos os afetados.

## 9. Limitações de responsabilidade

Por ser um protótipo acadêmico, o sistema pode ficar indisponível ou ser desativado ao fim do projeto. Os resultados são informativos e a equipe não responde por decisões comerciais tomadas com base neles.

## 10. Alterações e contato

Mudanças nestes termos geram nova versão e novo aceite. Dúvidas: emi.youtube.analytics@gmail.com.

Histórico de versões: 1.0 (06/10/2026), versão inicial; 1.1 (07/10/2026), inclusão do Resend entre os operadores (seção 5), da confirmação do e-mail no cadastro e do envio de e-mails entre as finalidades (seção 4) e do prazo dos cadastros não confirmados (seção 6); 1.2 (10/10/2026), adequação às políticas dos YouTube API Services: concordância com os Termos de Serviço do YouTube (seções 1 e 2), referência à Política de Privacidade do Google, dados dos vídeos, resultados e armazenamento no navegador (seções 3 a 5), prazos de guarda de 30 dias e 36 meses com exclusão automática (seção 6), exclusão do corpus de pesquisa ao fim do TCC (seção 6) e prazo de 7 dias para pedidos de exclusão (seção 7).

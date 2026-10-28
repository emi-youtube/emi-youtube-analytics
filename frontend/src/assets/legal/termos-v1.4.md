# Emi Analytics — Termos de Uso e Política de Privacidade

Versão 1.4 — vigente a partir de 28/10/2026. Projeto acadêmico (TCC) da Universidade Paulista (UNIP).

O Emi é uma plataforma que coleta os comentários dos seus vídeos publicitários, mostra a divisão entre positivo, negativo e neutro e descobre os temas que mais se repetem.

## 1. Sobre o sistema

O Emi Analytics é um sistema acadêmico que coleta comentários públicos de vídeos do YouTube indicados pelo usuário, classifica cada comentário como positivo, negativo ou neutro e agrupa os comentários em temas. O resultado é mostrado em um painel e em um relatório. Ele é um protótipo de pesquisa, oferecido sem garantia de disponibilidade.

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

## 4. Política de Privacidade: dados que acessamos, guardamos e usamos

As seções 4 a 11 são a Política de Privacidade do Emi. Controladores: a equipe do projeto, Giovana Fonseca Batscher, Giovanne da Silva Bordotti, João Antônio Marques Santana de Souza e Luan Donato Medeiros Moreno, e a orientadora, no contexto do TCC. Contato do encarregado: emi.youtube.analytics@gmail.com.

O Emi usa os YouTube API Services. Os dados obtidos por eles também estão sujeitos à [Política de Privacidade do Google](https://www.google.com/policies/privacy).

### 4.1 Dados da sua conta

Quando você cria uma conta ou é convidado, guardamos: seu nome, seu e-mail, o nome da empresa, sua senha (só como hash bcrypt, nunca a senha em si), seu papel na empresa (dono ou membro), a data de criação da conta e a versão e a data dos termos que você aceitou. Os modelos de análise que você cria ficam registrados com você como autor.

### 4.2 Dados obtidos dos YouTube API Services

O Emi **não usa login com Google e não pede acesso à sua conta do Google ou do YouTube**. Ele usa só a chave de API do projeto e lê dados públicos dos vídeos que você indica num modelo de análise.

- **O que acessamos de cada vídeo** (método videos.list): os dados públicos que a API devolve, como título, descrição, nome e identificador do canal, data de publicação, visualizações e curtidas.
- **O que acessamos de cada comentário** (método commentThreads.list): os dados públicos que a API devolve, como texto, data de publicação, identificador do comentário, curtidas e os dados públicos do autor (nome exibido, foto e identificador do canal).
- **O que guardamos:** do vídeo, o título, o nome do canal, a data de publicação, as visualizações e as curtidas; do comentário, o texto, a data e o identificador; e, no lugar do autor, um código SHA-256 calculado a partir do identificador do canal dele (ou do nome exibido, quando a API não traz o identificador).
- **O que não guardamos:** todo o resto que a API devolve é descartado na hora. Isso inclui o nome, a foto e o identificador do canal de quem comentou, descartados assim que o código é calculado, e o identificador do canal do vídeo, usado só para conferir que todos os vídeos de uma análise são do mesmo canal. Os comentários em outra língua são descartados antes da gravação; guardamos só quantos foram.
- **O que calculamos:** o sentimento de cada comentário, os percentuais, os temas, os indicadores e os comentários representativos de cada tema.

O código do autor é pseudonimização, não anonimização completa; por isso tratamos esses dados com cuidado e não os exibimos nas telas nem nos relatórios.

### 4.3 Dados técnicos e dados no seu dispositivo

- **Registros técnicos:** registros de funcionamento (logs) das execuções e da API, e as tentativas de login, guardadas com o e-mail em hash e o horário. O endereço IP de quem pede cadastro ou nova senha é usado na memória do servidor, sem ser gravado no banco, para limitar pedidos repetidos; ele também pode constar dos registros do provedor de hospedagem.
- **No seu dispositivo:** o Emi guarda no armazenamento local do navegador apenas o código da sessão, para manter você conectado; ele sai quando você encerra a sessão. O Emi não usa cookies de rastreamento.
- **Conteúdo de terceiros:** o Emi não exibe anúncios e não permite que terceiros sirvam conteúdo ou coletem informações nas suas páginas.

| Dado | Finalidade | Base legal (LGPD, art. 7º) |
|---|---|---|
| Nome, e-mail, senha e nome da empresa | Criar e proteger a conta, separar os dados por empresa, confirmar o e-mail no cadastro, enviar convites e links de redefinição de senha | Execução do serviço solicitado (inc. V) |
| Termos aceitos (versão e data) | Comprovar o consentimento aos termos | Cumprimento de obrigação / legítimo interesse |
| Comentários públicos do YouTube (texto, data e código do autor) | Classificar sentimentos e agrupar temas | Legítimo interesse acadêmico; dado tornado público (§4º) |
| Dados públicos dos vídeos (título, canal, data, visualizações e curtidas) | Identificar os vídeos analisados e calcular indicadores | Legítimo interesse acadêmico; dado tornado público (§4º) |
| Resultados da análise | Mostrar o painel e o relatório | Execução do serviço solicitado (inc. V) |
| Registros técnicos | Segurança e prevenção de fraude | Legítimo interesse (inc. IX) |
| Respostas da validação (se participar) | Pesquisa acadêmica | Consentimento (inc. I), pelo TCLE, tratadas em documento próprio |

## 5. Como usamos e processamos os dados

- **Dados da conta:** para entrar no sistema, separar os dados de cada empresa e enviar e-mails de confirmação de cadastro, de convite e de redefinição de senha. Não enviamos e-mails de propaganda.
- **Dados do YouTube:** um modelo de IA que roda no nosso próprio servidor classifica cada comentário; depois, um método estatístico agrupa os comentários em temas, e o sistema monta o painel e o relatório. Em produção, nenhum comentário é enviado a serviço de IA de terceiros. O processamento é automático e serve para resumir a reação ao vídeo: não toma decisões sobre pessoas.
- **Registros técnicos:** para segurança, prevenção de fraude e correção de falhas.
- **Corpus de pesquisa:** os comentários públicos usados para treinar e avaliar o modelo são tratados à parte, como descrito na seção 7.

## 6. Com quem compartilhamos

**Dentro do Emi (partes internas):**

- Os membros da sua empresa no Emi veem os modelos, as execuções, os resultados e os comentários da empresa. Usuários de outras empresas não veem nada disso.
- A equipe do projeto, como administradora, vê numa tela própria o consumo da cota do YouTube por empresa (nome da empresa e unidades gastas). Ela também pode acessar o banco de dados para manutenção, suporte e atendimento dos pedidos da seção 10, com dever de sigilo.

**Fora do Emi (operadores que tratam dados em nosso nome):**

- Supabase: banco de dados, na região de São Paulo, Brasil; guarda os dados da conta, os dados do YouTube, os resultados e as tentativas de login.
- Microsoft Azure: executa a API e os processos de coleta e análise, na região México Central; processa os dados durante o uso e guarda registros técnicos.
- Vercel: entrega o site e encaminha as requisições à API; pode processar dados nos EUA.
- YouTube API Services (Google): recebe os identificadores dos vídeos indicados e devolve os dados públicos da seção 4.2. Ver a [Política de Privacidade do Google](https://www.google.com/policies/privacy).
- Resend: envia os e-mails de confirmação de cadastro, de convite e de redefinição de senha; recebe o endereço de quem recebe e o texto da mensagem; pode processar dados fora do Brasil.
- Hugging Face: só para baixar o modelo de IA; nenhum dado é enviado.

Parte desses operadores trata dados fora do Brasil, com as salvaguardas contratuais dos próprios provedores (LGPD, art. 33). **Não vendemos, não alugamos e não compartilhamos dados para publicidade.** Só entregaremos dados a autoridades quando a lei exigir.

## 7. Quanto tempo guardamos

As políticas dos YouTube API Services limitam o tempo de guarda do que vem do YouTube, e o Emi segue esses prazos automaticamente:

- **Texto dos comentários, identificador do comentário e código do autor:** apagados em até 30 dias depois da coleta. A partir daí, a análise continua mostrando os percentuais, os temas e os indicadores, mas não os comentários. Para lê-los de novo, é preciso refazer a análise, o que faz uma coleta nova.

- **Título do vídeo e nome do canal:** atualizados junto ao YouTube antes de completarem 30 dias. Se o vídeo sair do ar ou a atualização não for possível, são apagados.

- **Resultados da análise, visualizações e curtidas da coleta:** até 36 meses depois da coleta. Esse prazo é o da política complementar dos YouTube API Services para quem recebe a permissão de métricas derivadas (Seção III.L), que pedimos ao YouTube em 14/10/2026. Se a permissão for negada, esses dados passarão a ser apagados em até 30 dias depois da coleta.

- **Dados da conta:** enquanto a conta existir.

- **Pedido de cadastro não confirmado:** apagado depois de 24 horas.

- **Tentativas de login:** apagadas depois de 24 horas.

Corpus de pesquisa: os textos de comentários públicos usados no treinamento e na avaliação do modelo, com o autor pseudonimizado, pertencem ao projeto acadêmico e não à empresa. Eles são guardados só até a conclusão do TCC, quando são excluídos, e não são publicados.

## 8. Como apagar seus dados

- **No próprio Emi:** em Minha conta > Excluir minha conta, com a confirmação da sua senha. A conta é apagada na hora, desde que não haja análise em andamento. Se você for o único membro da empresa, a empresa inteira também é apagada: modelos de análise, execuções, vídeos, comentários, resultados, temas e convites pendentes. Se a empresa tiver outros membros e você for o único dono, promova outro membro a dono antes de sair.
- **Por e-mail:** para apagar outros dados, como uma análise específica, escreva para emi.youtube.analytics@gmail.com. Pedidos de exclusão dos dados obtidos do YouTube são atendidos em até 7 dias; os demais, em até 15 dias.
- **Automaticamente:** os dados do YouTube são apagados nos prazos da seção 7, sem que você precise pedir.

Excluir dados no Emi não apaga nada no próprio YouTube.

## 9. Acesso à sua conta do Google

O Emi não usa login com Google e nunca recebe autorização para acessar a sua conta do Google ou do YouTube. Por isso, não há acesso do Emi a revogar. Se você deu acesso a outros aplicativos, pode rever e revogar essas autorizações a qualquer momento na página de configurações de segurança do Google: [https://myaccount.google.com/connections?filters=3,4&hl=en](https://myaccount.google.com/connections?filters=3,4&hl=en). Para encerrar o uso do Emi e apagar seus dados, siga a seção 8.

## 10. Seus direitos e contato

Você pode pedir confirmação do tratamento, acesso, correção, exclusão, portabilidade, informação sobre compartilhamento e revogação do consentimento (LGPD, art. 18). Em Minha conta, o botão "Baixar meus dados" entrega os dados da sua conta. Para os demais pedidos, para dúvidas sobre privacidade ou para reclamações, escreva para emi.youtube.analytics@gmail.com. Responderemos em até 15 dias. Você também pode reclamar à ANPD.

## 11. Segurança

Senhas com bcrypt, sessões curtas (15 minutos) com renovação, bloqueio após tentativas falhas, bancos com acesso restrito (RLS) e separação de dados entre empresas. Nenhum sistema é totalmente seguro; em caso de incidente relevante avisaremos os afetados.

## 12. Limitações de responsabilidade

Por ser um protótipo acadêmico, o sistema pode ficar indisponível ou ser desativado ao fim do projeto. Os resultados são informativos e a equipe não responde por decisões comerciais tomadas com base neles.

## 13. Alterações e contato

Mudanças nestes termos geram nova versão e novo aceite. Dúvidas: emi.youtube.analytics@gmail.com.

Histórico de versões: 1.0 (06/10/2026), versão inicial; 1.1 (07/10/2026), inclusão do Resend entre os operadores (seção 5), da confirmação do e-mail no cadastro e do envio de e-mails entre as finalidades (seção 4) e do prazo dos cadastros não confirmados (seção 6); 1.2 (13/10/2026), adequação às políticas dos YouTube API Services: concordância com os Termos de Serviço do YouTube (seções 1 e 2), referência à Política de Privacidade do Google, dados dos vídeos, resultados e armazenamento no navegador (seções 3 a 5), prazos de guarda de 30 dias e 36 meses com exclusão automática (seção 6), exclusão do corpus de pesquisa ao fim do TCC (seção 6) e prazo de 7 dias para pedidos de exclusão (seção 7); 1.3 (14/10/2026), troca do nome exibido de "Emi YouTube Analytics" para "Emi Analytics", porque as diretrizes de marca do YouTube não permitem o nome YouTube no nome de um aplicativo (título e seção 1); 1.4 (28/10/2026), Política de Privacidade reorganizada a pedido da revisão de conformidade dos YouTube API Services (Seção III.A.2): o que acessamos, guardamos e descartamos dos dados do YouTube (seção 4.2), como usamos os dados (seção 5), compartilhamento com partes internas e externas (seção 6), como apagar os dados (seção 8) e acesso à conta do Google (seção 9); nome completo de um dos controladores; prazo de 36 meses condicionado à permissão de métricas derivadas (seção 7).

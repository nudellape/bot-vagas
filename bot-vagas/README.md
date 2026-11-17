# Bot de vagas de estágio (Nível 3)

Roda sozinho de segunda a sexta às 8h17 (Brasília) no GitHub Actions, de graça:

1. **Coleta** vagas abertas na Gupy (todas as de estágio nas cidades das prioridades 1 e 2, mais buscas nacionais só de vagas remotas) e, opcionalmente, nas páginas Workday das empresas que você cadastrar.
2. **Filtra**: só estágio, só região ou remoto, publicadas nos últimos 30 dias (vagas sem data publicada são mantidas). Remove duplicatas.
3. **Dá nota de 0 a 100** pela sua rubrica (30 atividades, 25 curso, 20 local, 15 jornada, 10 aprendizado). O que a vaga não informa vira **DESCONHECIDO** com nota intermediária e aparece escrito na coluna "Detalhe da nota".
4. **Registra** tudo na aba `Vagas` de uma planilha Google, sem apagar histórico.
5. **Avisa** por Telegram e/ou e-mail só o que é **novo** com nota ≥ 55, mais mudanças (prazo alterado, vaga que saiu do ar).

## O que o bot faz e o que não faz

| Faz | Não faz |
|---|---|
| Confirma que a vaga estava listada na fonte no dia da busca | Não se candidata a nada |
| Usa só a data de publicação informada pela própria fonte | Não usa LinkedIn nem Indeed: os termos de uso proíbem coleta automatizada e os sites bloqueiam robôs |
| Sinaliza formatura exigida antes de dez/2028, jornada acima de 30h, curso listado sem Engenharia, vaga de nível técnico, prazo vencido | Não lê CIEE, Nube, Cia de Talentos, Eureca e 99jobs, que não têm interface pública estável. Continue olhando esses sites à mão (ou cadastre a empresa, se ela usar Workday) |
| Preserva o que você escreve em **Status** e **Minhas notas** | Não garante leitura perfeita do texto: carga horária, curso e bolsa são extraídos por padrões e podem falhar. Abra a vaga antes de se candidatar |

**Status** (lista suspensa na planilha): `nova`, `analisar`, `candidatura enviada`, `entrevista`, `encerrada`, `descartada`.
Se uma vaga some da Gupy e o status era `nova` ou `analisar`, o bot muda para `encerrada`. Se era `candidatura enviada` ou `entrevista`, ele só avisa e não mexe. Se a coleta falhar, nenhuma vaga é marcada como encerrada.

---

## Configuração (cerca de 30 minutos, uma vez só)

### 1. Repositório no GitHub
1. Crie uma conta em github.com, se ainda não tiver.
2. Crie um repositório **privado** (ex.: `bot-vagas`) e envie esta pasta para ele (botão "uploading an existing file" na página do repositório, arrastando todos os arquivos, incluindo a pasta `.github`).

### 2. Planilha Google + conta de serviço
1. Acesse console.cloud.google.com, crie um projeto (ex.: `bot-vagas`).
2. Em "APIs e serviços > Biblioteca", ative **Google Sheets API**.
3. Em "APIs e serviços > Credenciais > Criar credenciais > Conta de serviço", crie uma conta. Na conta criada, aba **Chaves > Adicionar chave > JSON**. Um arquivo `.json` será baixado. Guarde-o com cuidado, ele é uma senha.
4. Crie uma planilha vazia no Google Sheets. Clique em **Compartilhar** e adicione o e-mail da conta de serviço (algo como `bot-vagas@seu-projeto.iam.gserviceaccount.com`, está dentro do JSON em `client_email`) como **Editor**.
5. O ID da planilha é o trecho entre `/d/` e `/edit` no endereço.

### 3. Telegram (recomendado: chega na hora no celular)
1. No Telegram, fale com **@BotFather**, envie `/newbot` e siga as instruções. Ele devolve um **token**.
2. Abra o seu novo bot e mande qualquer mensagem (ex.: "oi").
3. No navegador, abra `https://api.telegram.org/bot<SEU_TOKEN>/getUpdates`. Procure `"chat":{"id":` e copie o número: esse é o **chat id**.

### 4. E-mail (opcional)
Com Gmail: ative a verificação em duas etapas e crie uma **senha de app** em myaccount.google.com/apppasswords. Use `smtp.gmail.com`, porta `587`, seu e-mail como `SMTP_USER` e a senha de app como `SMTP_PASSWORD`.

### 5. Segredos no GitHub
No repositório: **Settings > Secrets and variables > Actions > New repository secret**. Crie:

| Nome | Valor |
|---|---|
| `SHEET_ID` | ID da planilha |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | conteúdo inteiro do arquivo `.json` (abra no bloco de notas, copie e cole) |
| `TELEGRAM_BOT_TOKEN` | token do BotFather |
| `TELEGRAM_CHAT_ID` | número do chat |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO` | só se quiser e-mail |

### 6. Primeira execução
Aba **Actions > Busca diária de vagas > Run workflow**. Em 2 a 10 minutos:
- a aba `Vagas` aparece na planilha;
- o log da execução mostra o **top 10** (clique no passo "Buscar, registrar e alertar");
- chega a primeira mensagem no Telegram. Na primeira vez, todas as vagas são "novas", então a mensagem é maior.

Se o log mostrar erro 403 ou 429 em todas as consultas da Gupy, o portal está bloqueando os servidores do GitHub. Nesse caso, rode no seu computador (abaixo) ou me avise para adaptarmos.

---

## Rodar no computador (teste ou alternativa)

```bash
pip install -r requirements.txt
python -m pytest -q                       # testes offline
python -m bot.main --sem-alerta --relatorio
```
Sem `SHEET_ID`, o bot grava em `dados/vagas.csv`. Para usar a planilha e os alertas localmente, defina as mesmas variáveis do `.env.exemplo` no terminal.

## Ajustes em `config.yaml`
- `limiar_alerta`: suba para 65 se vier mensagem demais; desça para 45 se vier de menos.
- `prioridade_1` / `prioridade_2`: cidades.
- `gupy_termos_remotos`: termos das buscas nacionais de vagas remotas.
- `areas`: palavras que definem cada faixa de prioridade.
- `workday`: empresas com página Workday (instruções no próprio arquivo).

## Estrutura
```
bot/main.py           orquestra a execução
bot/sources/gupy.py   coleta na Gupy
bot/sources/workday.py coleta em páginas Workday
bot/analise.py        extração (jornada, curso, bolsa, formatura) e nota
bot/registro.py       planilha Google ou CSV; regras de status
bot/alertas.py        Telegram e e-mail
tests/                testes sem internet
.github/workflows/    agendamento
```

# Oliver · Triagem de risco de fogo e alagamento

Protótipo de TCC: uma rede neural (MLP) que estima o risco de propagação de fogo e de alagamento predial, com site, login e relatório em PDF.

## Como rodar

**Windows (jeito mais fácil):** dê dois cliques em `iniciar.bat`.

**Ou pelo terminal**, dentro desta pasta:

```
python -m pip install -r requirements.txt
python app.py
```

Depois abra **http://127.0.0.1:5000** no navegador. A primeira tela é o login: crie uma conta e entre.

Para parar o servidor, aperte `Ctrl+C` no terminal.

> Abrir os arquivos `.html` direto (dois cliques ou pré-visualização) não funciona: a rede neural roda em Python e só responde pelo servidor.

## Estrutura

```
app.py              servidor web (Flask): páginas, contas e API do Oliver
oliver/neural.py    rede neural MLP, treino com dados sintéticos e pesos salvos
oliver/chat.py      conversa: extrai os dados das mensagens e chama a rede
oliver/auth.py      contas (SQLite, senhas com hash) e recuperação de senha
oliver/pesos.json   pesos já treinados (apague para treinar de novo)
static/login.html   tela de login, criar conta, recuperar e redefinir senha
static/index.html   tela do Oliver (chat, formulário, resultado, PDF)
tests/              testes automáticos (python -m unittest)
deploy/             configuração para publicar no PythonAnywhere
wsgi.py             entrada para servidores WSGI (gunicorn, etc.)
```

Criados na primeira execução: `oliver.db` (usuários) e `secret.key` (chave das sessões). Não compartilhe esses dois arquivos.

## Publicar na internet (PythonAnywhere, grátis)

O plano gratuito do PythonAnywhere roda Flask e guarda o banco SQLite entre reinícios, então as contas não se perdem.

1. Crie uma conta em https://www.pythonanywhere.com (plano *Beginner*, grátis). O seu site vai ficar em `https://SEU_USUARIO.pythonanywhere.com`.
2. Na aba **Consoles**, abra um **Bash** e rode:
   ```
   git clone https://github.com/devthiago22-sys/oliver-AI.git
   cd oliver-AI
   pip3 install --user -r requirements.txt
   python3 -m unittest
   ```
3. Na aba **Web**, clique em **Add a new web app** > **Manual configuration** > escolha o Python mais recente da lista.
4. Ainda na aba **Web**:
   - Em **Code**, abra o **WSGI configuration file**, apague tudo e cole o conteúdo de `deploy/pythonanywhere_wsgi.py`, trocando `SEU_USUARIO`.
   - Em **Security**, ligue **Force HTTPS**.
   - Clique em **Reload** no topo.
5. Abra `https://SEU_USUARIO.pythonanywhere.com`. Pronto.

**Para atualizar o site** depois de mudar o código: envie para o GitHub, depois no Bash do PythonAnywhere rode `cd ~/oliver-AI && git pull` e clique em **Reload** na aba Web.

**Atenção:** no plano grátis, o site é desativado se ficar um mês sem você entrar no painel. Na aba **Web** há um botão para estender o prazo; clique nele antes da apresentação.

Erros do servidor aparecem em **Web > Log files > Error log**.

## Recuperação de senha

Sem servidor de e-mail configurado, o link de recuperação **aparece no terminal** onde o `app.py` está rodando (no PythonAnywhere, em **Web > Log files > Server log**). Copie e abra no navegador.

Para enviar por e-mail de verdade (por exemplo, Gmail com senha de app), defina antes de rodar:

```
set OLIVER_SMTP_HOST=smtp.gmail.com
set OLIVER_SMTP_PORT=587
set OLIVER_SMTP_USER=seu-email@gmail.com
set OLIVER_SMTP_PASSWORD=sua-senha-de-app
```

(No Linux/macOS use `export` no lugar de `set`. No PythonAnywhere, descomente essas linhas no arquivo WSGI.)

## Rede neural

- Duas MLPs (fogo: 4 entradas; alagamento: 5 entradas), 10 neurônios ocultos com tanh, saída softmax com 3 classes.
- Treino com 1.400 exemplos sintéticos por módulo, 42 épocas, taxa de aprendizado 0,075.
- Acurácia num conjunto de teste separado (600 exemplos): **97,0 %** (fogo) e **96,2 %** (alagamento).
- Índice de risco: 100 × (0,5 × P(moderado) + P(alto)).

Para treinar de novo e ver a acurácia: `python -m oliver.neural`

## Relatório em PDF

Depois de uma análise, clique em **Gerar relatório em PDF** e escolha **Salvar como PDF** na janela de impressão. O relatório traz as duas análises (fogo e alagamento), probabilidades, dados informados, recomendações e a explicação do método.

## Aviso

Protótipo acadêmico treinado com dados sintéticos. Não substitui alertas da Defesa Civil, do INPE, do INMET ou do Cemaden.

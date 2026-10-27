# Oliver · Triagem de risco de fogo e alagamento

Protótipo de TCC: uma rede neural (MLP) que estima o risco de queimadas e de alagamento nos 217 municípios do Maranhão, usando dados do INPE e do INMET. Tem site, login e relatório em PDF.

## Como funciona

A pessoa só diz a cidade (e, para alagamento, responde três perguntas simples sobre o imóvel). O Oliver busca os dados mais recentes, passa pela rede neural e responde com o risco, um mapa dos focos de calor e um relatório em PDF com as fontes.

```
GitHub Actions (de hora em hora)          PythonAnywhere (site)
coletor/coletar.py                         app.py + oliver/regional.py
  INPE · focos de calor  ─┐                  lê maranhao.json do branch "dados"
  INMET · avisos         ─┼─► maranhao.json ─► rede neural ─► resposta + PDF
  Open-Meteo · clima     ─┘   (branch dados)
```

O site não acessa o INPE e o INMET diretamente porque o plano gratuito do PythonAnywhere só libera alguns endereços (o GitHub está entre eles).

### Fontes de dados

| Dado | Fonte |
|---|---|
| Focos de calor (48 h), agrupados por local | INPE · Programa Queimadas (BDQueimadas), arquivo diário |
| Avisos meteorológicos ativos | INMET (apiprevmet3) |
| Vento e umidade | Estação automática do INMET mais próxima (até 80 km) quando a API responde; senão Open-Meteo |
| Chuva últimas/próximas 24 h, chuva de 30 dias, dias sem chuva relevante | Open-Meteo |
| Municípios, códigos e coordenadas | IBGE (lista pública de municípios) |
| Declividade em torno da sede | Open-Meteo (Copernicus DEM) |
| Sinalização de 1 a 3 meses (média de focos por mês, 2015 em diante) | INPE · arquivos anuais do satélite de referência (`coletor/climatologia.py`, roda todo ano em fevereiro) |

A API de estações do INMET passou a exigir token. Se você conseguir um, cadastre em **Settings > Secrets and variables > Actions** com o nome `INMET_TOKEN` e o coletor passa a usá-lo.

Para rodar o coletor à mão: aba **Actions > Coletar dados do Maranhão > Run workflow**.

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
oliver/regional.py  conversa por município do Maranhão com os dados coletados
oliver/chat.py      entrada da API; modo "Simulação" com valores técnicos
coletor/coletar.py  coletor horário (INPE, INMET, Open-Meteo, IBGE)
.github/workflows/  agenda do coletor no GitHub Actions
oliver/auth.py      contas (SQLite, senhas com hash) e recuperação de senha
oliver/pesos.json   pesos já treinados (apague para treinar de novo)
static/login.html   tela de login, criar conta, recuperar e redefinir senha
static/index.html   tela do Oliver (chat, formulário, resultado, PDF)
tests/              testes automáticos (python -m unittest)
deploy/             configuração para publicar no PythonAnywhere
wsgi.py             entrada para servidores WSGI (gunicorn, etc.)
```

Criados na primeira execução: `oliver.db` (usuários) e `secret.key` (chave das sessões). Não compartilhe esses dois arquivos.

## Dados para SIG (QGIS, ArcGIS, Google Earth)

No site, use o quadro **Dados para SIG** (abaixo do resultado) ou peça no chat, por exemplo: "quero os dados de Caxias em shapefile para o QGIS" ou "Maranhão todo em KML".

| Formato | Arquivo | Para |
|---|---|---|
| Shapefile | `.zip` com `.shp .shx .dbf .prj .cpg` | ArcGIS, QGIS |
| GeoPackage | `.gpkg` (as duas camadas num arquivo) | QGIS, ArcGIS Pro |
| GeoJSON | `.zip` com um `.geojson` por camada | QGIS, web |
| KML | `.kml` | Google Earth |
| CSV | `.zip` com latitude, longitude e geometria WKT | planilhas, QGIS |

Camadas, sempre em WGS 84 (EPSG:4326):

- **municipios**: polígonos dos municípios (malha do IBGE, simplificada a ~150 m) com risco de fogo da rede neural, probabilidades, vento, umidade, chuva, secura, declividade, focos de 24 h, 48 h e 7 dias, avisos do INMET e a sinalização dos próximos 3 meses.
- **focos**: pontos dos focos de calor das últimas 48 horas (INPE), com data, satélites, número de detecções e intensidade (FRP).

Cada download traz um `LEIAME.txt` com a descrição de todos os campos. Os arquivos são gravados pelo próprio Oliver (`oliver/sig.py`), sem GDAL. A malha vem de `coletor/malha.py` (Actions > "Atualizar malha dos municípios").

## Publicar na internet (Render + Supabase, grátis)

O site roda no **Render** e as contas ficam num banco Postgres no **Supabase** (projeto `oliver`, São Paulo).
Cada envio ao GitHub atualiza o site sozinho.

1. Supabase: no projeto `oliver`, clique em **Connect** e copie a *connection string* do **Session pooler**
   (porta 5432). Troque `[YOUR-PASSWORD]` pela senha do banco (se não souber, defina uma nova em
   *Project Settings > Database > Reset database password*).
2. Render: entre com a conta do GitHub em https://render.com, clique em **New > Blueprint**, escolha o
   repositório `oliver-AI` e, quando pedir `DATABASE_URL`, cole a connection string do passo 1.
3. Quando o site subir, copie o endereço (algo como `https://oliver-ai.onrender.com`) e cadastre no GitHub em
   **Settings > Secrets and variables > Actions > Variables** com o nome `OLIVER_SITE_URL`. A partir daí o
   workflow "Manter o site acordado" visita o site a cada 10 minutos.

Sem `DATABASE_URL`, o Oliver usa SQLite (`oliver.db`), como no computador local e no PythonAnywhere.

## Publicar no PythonAnywhere (alternativa)

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

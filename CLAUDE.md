# pfvd-mercado-futebol

Produto de visualização da disciplina GDCOC0096 (UFPB): dashboard em Streamlit para decisão de contratação com orçamento limitado, mais a base de temporadas para novos gráficos. Responda em português.

```bash
uv sync
uv run python -m pytest                  # sem os dados do Drive, pula os testes do dashboard
uv run python -m src.prepare             # base do dashboard (exige os arquivos do Drive)
uv run streamlit run app.py              # dashboard
uv run python -m src.build_seasons       # base dos gráficos: data/processed/seasons.csv
```

## Onde estão os dados

[Pasta do Drive do projeto](https://drive.google.com/drive/folders/1XLrhqb36JVIoV7jH9huuAS4NhRbaabQG)

| Dados | Local | Vai para o Git? |
|---|---|---|
| Dataset aberto, licença CC0 (2025-2026) | `data/open/transfermarkt_datasets/` | Sim |
| API-Football (partidas, elencos, CSVs) | `data/raw/api_football/`, zip `api_football_dados.zip` no Drive | **Não** |
| FBref e Transfermarkt do dashboard (2024-25) | `data/raw/`, `data/processed/`, no Drive | **Não** |
| Bases geradas | `data/processed/` | Não: gere de novo |

O repositório é público, e os termos da API-Football não foram verificados. Antes de ampliar o que é versionado, pergunte ao responsável. O significado das colunas e o que cada recorte permite concluir estão em `docs/dados.md`.

## Como puxar mais dados

O plano Free da API-Football bloqueia temporadas a partir de 2025 e só libera partidas **de ontem a amanhã**. Por isso a coleta é diária e acumula partida por partida. **Partida fora dessa janela não pode mais ser coletada de graça.**

1. **Baixe o histórico.** Extraia `api_football_dados.zip`, do Drive, em `data/raw/api_football/`. O resultado precisa ser `data/raw/api_football/raw/fixtures/<Liga_Temporada>/<partida>.json`. Sem isso, `daily.py` para de propósito, porque recalcula os CSVs com as partidas presentes e perderia o acumulado.
2. **Confira a chave.** Cada pessoa cria a própria conta em <https://dashboard.api-football.com> e coloca a chave em `.env` (modelo em `.env.example`). Nunca mostre, registre ou versione o valor.
3. **Colete.** `uv run python collect/api_football/daily.py`
   - Consulta ontem e hoje, baixa as partidas encerradas das 12 ligas e usa a cota restante para os elencos (idade e posição).
   - Para em 90 requisições (`--max-requests`), e o que já foi baixado não gasta cota de novo.
   - `--rebuild-only` recalcula os CSVs sem usar a API.
4. **Atualize a base.** `uv run python -m src.build_seasons`
5. **Devolva ao Drive.** Compacte o conteúdo de `data/raw/api_football/` em um novo `api_football_dados.zip`, mantendo a mesma estrutura, e substitua o arquivo.

**Coordenação:**
- Combinem quem coleta em cada dia. Uma coleta perdida pode ser recuperada no dia seguinte; depois de 2 dias, as partidas se perdem.
- Se duas pessoas coletarem, copie os JSONs de uma pasta para a outra (cada partida é um arquivo único, então não há conflito) e rode `--rebuild-only`.
- Se aparecer `Nenhuma partida em ...`, baixe o histórico. Só use `--first-run` para começar um histórico novo de propósito.

**Erros comuns:**
- `requests`/cota esgotada: espere a renovação diária; o que foi baixado fica salvo.
- `Free plans do not have access to this date`: a janela mudou. Leia a data indicada na mensagem e avise o responsável, porque a coleta depende dela.
- `Free plans do not have access to this season`: esse endpoint exige plano pago.

**Outras opções:**
- Reimportar o dataset aberto: `uv run python collect/transfermarkt_datasets/import_dataset.py --download` (cerca de 240 MB; vai para `data/raw/`, que é ignorada). Esse dataset parou de ser atualizado em julho de 2026, então não adianta rodar esperando dados novos.
- Temporada completa: só com plano pago (cerca de US$ 19/mês), usando `collect/api_football/run.py --check` e depois `run.py`. **Não contrate nada sem o responsável decidir.**
- História do FBref 2020-2025: `uv run python -m src.build_seasons --fbref-dir <pasta>`, para quem tiver os arquivos `{temporada}_outfield.csv`. Essa base não é distribuída aqui.

## Regras

- Nunca versione `.env` nem dados da API. Antes de cada commit, confira `git status`.
- Não crie várias contas para escapar do limite da API, e não contorne bloqueio anti-bot (Cloudflare, `cloudscraper`, Selenium etc.). FBref, Sofascore e FotMob foram avaliados e descartados por isso.
- Métrica ausente continua vazia, nunca vira 0.
- Não compare fontes como se fossem equivalentes, e não some totais de temporadas com `is_partial=True` para tirar conclusões sobre a temporada inteira.
- Valor de mercado é estimativa, não custo de transferência.
- Testes em `tests/` para cada mudança de comportamento. Figuras novas usam `src/charts.py` e seu tema, com título que afirma o que o gráfico mostra.
- O dashboard do estudo de caso (Brentford, Premier League 2024-25) não usa `seasons.csv`. Não troque essa base sem pedido explícito.

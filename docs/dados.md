# Dados de temporadas

`uv run python -m src.build_seasons` gera `data/processed/seasons.csv`, com uma linha por jogador, clube e temporada. O arquivo traz só o que as fontes têm em comum.

## Colunas

| Coluna | Significado | Observação |
|---|---|---|
| `league` | Liga, como `Premier_League` | |
| `season` | `2025-2026` ou, em ligas de ano-calendário, `2026` | |
| `data_source` | `transfermarkt_datasets`, `api_football` ou `fbref` | Sempre filtre ou separe por fonte |
| `is_partial` | `True`: só parte da temporada | Não conclua sobre a temporada inteira |
| `player_id` | Identificador na fonte (`tm_`, `af_`) | Não vale entre fontes |
| `Player`, `Squad`, `Pos` | Jogador, clube, posição | `Pos` geral: GK, DF, MF, FW. Vazia se a fonte não informar |
| `Age` | Idade | Vazia enquanto o elenco não for coletado |
| `minutes`, `games` | Minutos e jogos | Goleiros incluídos |
| `goals`, `assists` | Gols e assistências | Sem gols contra. Vazio é ausente, não 0 |
| `cards_yellow`, `cards_red` | Cartões | |
| `value_eur_m` | Valor de mercado em milhões de euros | Só no dataset aberto; é estimativa |

Os detalhes de cada fonte, como chutes, passes, duelos e notas da API, continuam nos CSVs em `data/open/` e `data/raw/api_football/player_data/`.

## Cobertura

| Fonte | Temporadas | Ligas | Traz | Não traz |
|---|---|---|---|---|
| `transfermarkt_datasets` (CC0) | 2025-2026 | Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Primeira Liga, Bélgica | minutos, gols, assistências, cartões, posição detalhada, idade, valor | chutes, passes, desarmes, defesas, xG |
| `api_football` (Free) | 2026 e 2026-2027, desde 08/11/2026 | as 12 do projeto, conforme as partidas coletadas | também chutes, passes, desarmes, duelos, dribles, defesas e nota | partidas anteriores à coleta, valor, posição detalhada, xG |
| `fbref` (opcional) | 2020 a 2025 | as 12 do projeto | muitas métricas, incluindo xG, nos arquivos originais | temporadas posteriores |

Lacunas conhecidas:
- Liga MX não tem 2025-2026.
- Brasil, Argentina, MLS e México não têm as partidas de 2026 anteriores a 08/11.
- A Bélgica vai até 22/03/2026, aparentemente sem playoffs.
- No FBref, os arquivos de 2025 de Brasileirão A e B, LPF e MLS foram coletados no meio do campeonato (`is_partial=True`).
- Os arquivos antigos do FBref preencheram ausentes com 0, então nesses arquivos um 0 pode significar "sem dado".

## O que cada recorte permite

| Pergunta | Use | Cuidado |
|---|---|---|
| Quanto vale cada liga ou clube em 2025-2026? | `transfermarkt_datasets` | Conte cada `player_id` uma vez: quem trocou de clube tem duas linhas com o mesmo valor |
| Idade ou posição contra valor | `transfermarkt_datasets` | O valor é do momento da publicação do dataset, não do início da temporada |
| Artilheiros e assistências de 2025-2026 | `transfermarkt_datasets` | 7 ligas; Bélgica incompleta |
| Evolução entre 2020 e 2025 | `fbref` com `--fbref-dir` | Exclua as linhas com `is_partial=True` |
| O que aconteceu em uma rodada recente | `api_football` | Com poucos jogos, não sustenta ranking da temporada |
| Comparar 2024-25 com 2025-26 | só minutos, gols, assistências e cartões | Fontes diferentes podem contar assistências de formas diferentes |

## Conferências feitas

- Artilheiros de 2025-2026 conferidos em fontes externas: Haaland 27, Kane 36, Mbappé 25.
- Em 8 dos 102 times coletados na API, a soma dos gols dos jogadores fica 1 abaixo do placar. Nas 2 partidas verificadas, a diferença era gol contra; as outras 6 não foram checadas.
- Cerca de 1% das atuações na API vem com posição nula. O coletor usa a posição de outras partidas ou do elenco; sem nenhuma das duas, ela fica vazia.

## Origem

- [`transfermarkt-datasets`](https://github.com/dcaribou/transfermarkt-datasets), licença CC0 1.0 declarada pelo autor do dataset. Os dados de origem vêm do Transfermarkt, cujos termos não foram avaliados aqui.
- [API-Football](https://www.api-football.com/): termos de redistribuição não verificados. Por isso, esses dados não ficam no repositório.

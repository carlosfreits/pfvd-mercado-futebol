# Mercado com orçamento limitado

Produto de visualização para a disciplina Visualização de Dados (GDCOC0096, UFPB). Ele responde a três perguntas de um clube que precisa contratar: em que posição reforçar, quem contratar e se o preço compensa.

O caso de estudo é o Brentford na Premier League 2024-25.

## Como executar

Requer [uv](https://docs.astral.sh/uv/).

**Os dados não fazem parte deste repositório.** Os termos de uso das fontes e a autorização para redistribuir a base ainda não foram verificados. Sem os três arquivos abaixo em `data/raw/`, não é possível gerar a base nem abrir o dashboard:

- `fbref_jogadores.csv`
- `fbref_goleiros.csv`
- `transfermarkt_jogadores.csv`

Com os arquivos no lugar:

```bash
uv sync
uv run python -m src.prepare          # gera data/processed/
uv run streamlit run app.py           # abre o dashboard
uv run python -m pytest               # executa os testes
```

Sem os dados, `uv run python -m pytest` executa só os testes que não dependem da base.

Para gerar as figuras do artigo, é preciso ter o Chrome ou o Edge instalado. No Windows com Edge:

```bash
export BROWSER_PATH="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
uv run python -m src.export_figures   # gera article/figures/ e article/facts.json
```

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `src/prepare.py` | Limpeza e junção entre FBref e Transfermarkt |
| `src/rating.py` | Nota de desempenho, preço esperado e regras de indicação |
| `src/charts.py` | Gráficos usados no dashboard (tema escuro) e no artigo (tema claro) |
| `src/ui.py` | Cartões, legenda, barras de percentil e formatação de números do dashboard |
| `.streamlit/config.toml` | Tema visual do dashboard |
| `static/`, `assets/` | Fontes Barlow (licença OFL), desenho do campo e emblema próprio |
| `src/export_figures.py` | Exportação das figuras e dos números do artigo |
| `app.py` | Dashboard em Streamlit |
| `article/figures/` | Figuras geradas por `src/export_figures.py` |

## Método

1. **Nota:** padroniza métricas por 90 minutos em cada posição e aplica os pesos do projeto Esportes-2025. A escala tem 50 como média da posição, e 20 pontos equivalem a um desvio-padrão.
2. **Junção:** exige o mesmo ano de nascimento e nome parecido, com cada registro do Transfermarkt usado uma única vez.
3. **Mercado:** inclui só clubes em que pelo menos 60% dos jogadores têm valor conhecido.
4. **Preço esperado:** modelo log10(valor) = nota + idade + idade² + posição.
5. **Indicação:** exige nota acima da média do elenco na posição, valor dentro do orçamento e preço abaixo do esperado por mais do que o erro típico do modelo.

## Limitações

- Só 10 dos 20 clubes têm cobertura adequada de valores.
- O modelo explica 55% da variação do valor, e a idade sozinha explica 47%. O erro típico é de 1,68 vez.
- A nota tem relação nula ou negativa com o preço em goleiros, zagueiros e volantes, então deve ser usada com mais cautela nessas posições.
- O diagnóstico da lateral do Brentford usa dois jogadores e varia de −2,3 a −14,2 conforme quem conta como lateral.
- Valor de mercado é uma estimativa, e não o custo real da transferência.

As indicações são um ponto de partida para o scouting, e não recomendações finais.

## Fontes e créditos

- **Dados:** FBref e Transfermarkt, copiados do repositório [TailUFPB/Esportes-2025](https://github.com/TailUFPB/Esportes-2025), commit `be2711a`. Esse repositório é privado, então o link exige acesso. Os dados não são distribuídos aqui porque os termos de uso das fontes ainda precisam ser verificados.
- **Pesos e escala da nota:** classe `FootballRating` do mesmo projeto, da Diretoria de Esportes da TAIL.

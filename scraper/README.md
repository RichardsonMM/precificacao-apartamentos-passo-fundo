# Coleta de dados — Precificação de imóveis em Passo Fundo/RS

Etapa 1 do pipeline do TCC *"Precificação de Imóveis com Aprendizado de Máquina:
um estudo aplicado ao mercado de apartamentos de Passo Fundo"*.

Implementa a coleta automatizada (web scraping) de anúncios de apartamentos à
venda em um portal imobiliário regional, gerando a base bruta em CSV que alimenta
as etapas de pré-processamento e engenharia de *features*.

> **Leia antes de rodar:** `ACHADOS_INSPECAO.md` documenta a inspeção técnica do
> portal e três achados que afetam o texto da proposta — o site é uma SPA que
> exige JavaScript, os dados vêm em JSON-LD (e não do mapa embedado), e o filtro
> de cidade da URL não funciona.

## Estrutura

```
scraper/
├── config.py                # URLs, seletores CSS, política de requisição, POIs
├── run_scraper.py           # CLI da coleta (URLs → detalhes → CSV)
├── qualidade.py             # relatório de qualidade da base bruta
├── requirements.txt
├── DICIONARIO_DE_DADOS.md   # descrição das 61 colunas do CSV
├── ACHADOS_INSPECAO.md      # inspeção técnica do portal
├── src/
│   ├── http_client.py       # sessão HTTP, retry, rate limit, cache de HTML
│   ├── browser_fetch.py     # navegador headless para páginas renderizadas em JS
│   ├── jsonld.py            # extração do schema.org/RealEstateListing
│   ├── parsers.py           # parsing da listagem e da página de detalhe
│   ├── cards.py             # preço anterior e selos, que só existem no card
│   ├── geo.py               # extração de latitude/longitude (fallback do JSON-LD)
│   ├── normalize.py         # conversão de texto para tipos numéricos/booleanos
│   └── storage.py           # checkpoint JSONL e exportação CSV
└── data/                    # criada na primeira execução, não versionada
    ├── raw_html/            # HTML bruto em cache (reprodutibilidade)
    └── output/              # anuncios_brutos.jsonl, cards_listagem.json, dataset_bruto.csv
```

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r ../requirements.txt
playwright install chromium
```

O Chromium é obrigatório: o portal é uma SPA em Nuxt/Vue e `requests` sozinho
devolve apenas o esqueleto do HTML.

## Uso

**1. Execução piloto** — valida os seletores em poucos anúncios:

```bash
python run_scraper.py --fase completa --limite 20
python qualidade.py
```

**2. Coleta completa:**

```bash
python run_scraper.py --fase completa
```

**Outros comandos:**

```bash
python run_scraper.py --fase urls           # só indexa as URLs de detalhe
python run_scraper.py --fase detalhes       # só extrai os anúncios indexados
python run_scraper.py --fase exportar       # regera o CSV a partir do checkpoint
python run_scraper.py --sem-navegador       # só requests, sem Playwright
python run_scraper.py --sem-filtro-cidade   # exporta todos os municípios
```

## Decisões de projeto

**Checkpoint incremental.** Cada anúncio é gravado em `anuncios_brutos.jsonl`
assim que extraído. A coleta pode ser interrompida e retomada sem perda: URLs já
processadas são puladas automaticamente.

**Cache de HTML.** Todo HTML baixado é salvo em `data/raw_html/`. Reexecutar o
parser não gera novas requisições ao portal — importante tanto para a coleta
responsável quanto para a reprodutibilidade exigida no trabalho, já que a base
pode ser reconstruída a partir do HTML original mesmo depois de o anúncio sair
do ar. Use `--sem-cache` para forçar novas requisições.

**Coleta responsável.** Pausa de ~2–3 s entre requisições (com *jitter*), sessão
HTTP persistente, retry exponencial em 429/5xx e *User-Agent* identificável.

**Renderização híbrida.** O portal é uma SPA em Nuxt/Vue: uma requisição HTTP
simples devolve só o esqueleto da página. A coleta tenta `requests` primeiro,
verifica se o HTML tem os marcadores de conteúdo esperados e recorre ao
navegador headless (Playwright) apenas quando necessário — o que mantém a coleta
barata e reserva o navegador para as páginas que realmente exigem JavaScript.

**JSON-LD como fonte primária.** Cada anúncio publica um bloco
`schema.org/RealEstateListing` com preço, área, coordenadas, dormitórios e vagas
já tipados. É preferível a seletores CSS porque o portal usa Tailwind, cujas
classes mudam a cada build. O DOM responde pelos campos que o JSON-LD não traz:
bairro, suítes, banheiros, andar, condomínio e IPTU.

**Parsing em camadas para o que vem do DOM.** Primeiro os seletores CSS de
`config.py`; se falharem, uma heurística genérica de ficha técnica (pares
rótulo → valor em tabelas, listas de definição e itens "Rótulo: Valor") e
expressões regulares sobre contadores no corpo do anúncio ("3 dorm.", "2 vagas",
"85 m²"). A redundância evita perda de registros caso o layout mude.

**Coordenadas.** Extraídas na ordem: JSON-LD (`schema.org/GeoCoordinates`),
atributos `data-lat`/`data-lng`, `src` do iframe do Google Maps, links para o
Maps, scripts embutidos e, por último, varredura do HTML. Cada registro guarda
em `geo_origem` de onde a coordenada veio, o que permite auditar a confiabilidade.

**Filtro de município no pós-processamento.** O filtro de cidade da URL do portal
não se mostrou confiável (a listagem mistura Passo Fundo e o litoral
catarinense). A seleção é feita sobre `cidade`/`uf` do JSON-LD de cada anúncio —
mais lento, porém sem risco de perder imóveis por falha do filtro do site.

**Sem LLM na extração.** Conforme a proposta, apenas campos estruturados do HTML
são usados; as descrições textuais livres não são interpretadas.

## Saída

`data/output/dataset_bruto.csv` — uma linha por anúncio. As colunas estão
documentadas em `DICIONARIO_DE_DADOS.md`.

A coluna `registro_valido` marca com 1 os anúncios que têm preço e ao menos uma
métrica física (área ou dormitórios) — os aproveitáveis para modelagem.

A coluna `alertas_qualidade` marca inconsistências **do cadastro do portal**,
não da raspagem. Use-a como critério explícito de exclusão antes de modelar. O
alerta mais importante é `preco_a_partir_de`: cerca de 12% dos anúncios trazem
preço de tabela de lançamento em vez de preço firme, e misturá-los a negócios
fechados contamina a variável dependente.

`data/output/cards_listagem.json` — dados que existem **apenas no card da
listagem** (preço anterior riscado e selos), indexados pelo id do imóvel. São
lidos na fase `urls` e consumidos na fase `detalhes`. Rodar `--fase detalhes`
sem ter rodado `--fase urls` antes produz registros sem essas colunas, e o log
avisa quantos ficaram sem card.

## Próximas etapas do pipeline

1. Pré-processamento: deduplicação, valores ausentes (mediana/moda), *outliers*
   por IQR, normalização Min-Max, *one-hot encoding* de bairro.
2. Engenharia de *features*: distâncias de Haversine aos 10 pontos de interesse
   (`config.PONTOS_INTERESSE`), reduzidas a 3 variáveis (menor distância por
   categoria: shopping, hospital, ensino).
3. Análise exploratória, modelagem e avaliação.

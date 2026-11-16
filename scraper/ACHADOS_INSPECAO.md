# Achados da inspeção técnica do portal — 11/08/2026

Registro da etapa de reconhecimento do portal de origem dos dados, feita com inspeção direta do DOM em navegador. Três
achados têm impacto sobre o texto da proposta e estão detalhados abaixo.

---

## 1. O portal é uma SPA com renderização no cliente

**O que foi observado.** A aplicação é construída em Nuxt/Vue e servida atrás de
Cloudflare. Na página de listagem, os 20 cartões de anúncio existem no DOM
apenas como placeholders (`skeleton-shimmer`, 80 ocorrências) até que o
JavaScript execute e preencha o conteúdo. O atributo `serverRendered` do payload
do Nuxt vem como `false`.

**Consequência.** A dupla `requests` + `beautifulsoup4`, descrita na Seção 4.2.1
e na Tabela 2 da proposta, **não é suficiente para as páginas de listagem**: uma
requisição HTTP simples devolve o esqueleto, sem anúncios. É necessário um
navegador headless (Playwright ou Selenium) para essa etapa.

**Como foi tratado.** A coleta ficou híbrida (`src/browser_fetch.py`): tenta
primeiro `requests`, verifica se o HTML devolvido contém os marcadores de
conteúdo esperados e, só quando vier incompleto, recarrega a página no navegador
headless. Isso mantém `requests` e `beautifulsoup4` legitimamente no pipeline —
como está na proposta — e usa o navegador apenas onde ele é indispensável.

**Ponto em aberto para a execução piloto.** Falta confirmar se as páginas de
*detalhe* também dependem de JavaScript. Elas apresentaram JSON-LD completo e
nenhum `skeleton-shimmer` após a renderização; se esse bloco vier já no HTML
bruto, os detalhes seguem coletáveis só com `requests` e o navegador fica
restrito à listagem. A lógica atual detecta isso sozinha em tempo de execução e
registra a contagem no log (`páginas via navegador`).

**Sugestão para o texto do TCC.** Acrescentar `playwright` à Tabela 2, na
categoria "Coleta de dados", com a finalidade "renderização de páginas
dinâmicas", e registrar na Seção 4.2.1 que o portal exige execução de JavaScript
— é uma justificativa metodológica legítima e um detalhe que diferencia o
trabalho de raspagens ingênuas.

---

## 2. Cada anúncio publica dados estruturados em JSON-LD

**O que foi observado.** Toda página de detalhe traz um bloco
`<script type="application/ld+json">` do tipo `schema.org/RealEstateListing`
com os dados já tipados:

| Caminho no JSON-LD | Variável do dataset |
|---|---|
| `offers.price` | preço de venda (float, BRL) |
| `about.floorSize.value` | área privativa em m² |
| `about.geo.latitude` / `.longitude` | coordenadas geográficas |
| `about.numberOfBedrooms` | dormitórios |
| `about.numberOfParkingSpaces` | vagas de garagem |
| `about.address.addressLocality` / `.addressRegion` | cidade e UF |
| `about.amenityFeature[]` | lista de amenidades |
| `about.additionalProperty[]` | pares nome/valor (mobília, suítes) |
| `datePosted` | data de publicação do anúncio |

**Por que isso importa.** É uma fonte melhor do que seletores CSS em dois
sentidos. Primeiro, robustez: o portal usa CSS utilitário (Tailwind), cujas
classes mudam a cada build — seletores montados sobre elas quebrariam durante o
período de coleta. Segundo, tipagem: preço e área já vêm como número, o que
elimina uma classe inteira de erros de conversão.

**Consequência sobre a proposta.** A Seção 4.2.1 afirma que as coordenadas são
extraídas "da URL do mapa embedado do Google Maps". Na prática elas vêm do
JSON-LD, o que é ainda mais direto e continua dispensando serviços externos de
geocodificação — a justificativa da proposta permanece válida, só muda a fonte.
Vale corrigir a frase.

**Como foi tratado.** `src/jsonld.py` extrai o bloco e tem precedência sobre o
parsing do DOM. Os campos ausentes no JSON-LD — **bairro, suítes, banheiros,
andar, condomínio e IPTU** — continuam vindo do DOM, por ficha técnica
(rótulo → valor) e por expressões regulares sobre o corpo do anúncio.

---

## 3. O filtro de cidade da URL não estava sendo aplicado

**O que foi observado.** A URL
`/comprar-imoveis/apartamentos/passo-fundo` é normalizada pelo portal para
`?operacao=vendas&tipoId=1&ordem=1`, **sem parâmetro de cidade**. O contador
seguiu em "1.371 Imóveis para vendas" e o primeiro resultado era um apartamento
na Praia Brava, em Itajaí/SC. O grupo atende duas regiões — "Região Passo Fundo"
e "Litoral Catarinense" — e a listagem sem filtro mistura as duas.

Marcar "Passo Fundo" no filtro de cidades por script não surtiu efeito: o Vue só
reage a eventos de interação reais, então o parâmetro correspondente não pôde ser
capturado dessa forma.

**Como foi tratado.** A filtragem por município passou para o pós-processamento,
usando `cidade` e `uf` extraídos do JSON-LD de cada anúncio
(`config.CIDADE_ALVO`). É mais lento — percorre toda a base da rede — mas é
**mais confiável do que depender do filtro do portal**, e garante que nenhum
imóvel de Passo Fundo seja perdido por falha do filtro do site.

**Ponto em aberto.** O nome do parâmetro de paginação (`config.PAGINACAO_PARAM`,
hoje `"pagina"`) também não foi confirmado. A execução piloto resolve os dois:
basta aplicar o filtro manualmente no navegador, com o mouse, e copiar a URL
resultante. Se o parâmetro de cidade aparecer, dá para restringir a coleta na
origem e reduzir bastante o volume de requisições.

---

## Dados observados na listagem

- **20 anúncios por página**, 2 links por cartão.
- URL de detalhe: `/imovel/{slug}/{id}` — o `{id}` numérico é o identificador
  estável do imóvel.
- Cartão exibe: código interno (ex.: `VAP0795`), título, preço, bairro-cidade/UF,
  dormitórios, suítes, vagas e área em m².
- Container do cartão: `div.hoverCard1`.
- As imagens são servidas por `cdn.mizia.com.br` — o CRM que sustenta o portal.
- O `@id` do JSON-LD aponta para domínios de imobiliárias parceiras
  (ex.: `pauloricardoimoveis.com.br`), confirmando que a rede compartilha a mesma
  base de anúncios. **Isso reforça a necessidade da deduplicação** já prevista na
  proposta: o mesmo imóvel pode aparecer sob mais de uma imobiliária.

## Estimativa de volume

O total de 1.371 imóveis é da rede inteira, incluindo o litoral catarinense e
todos os tipos. Quantos são apartamentos à venda em Passo Fundo só a execução
piloto dirá. Caso o volume final fique abaixo de ~300 registros, vale discutir
com o orientador a inclusão de outra fonte — a literatura de referência trabalha
com bases bem maiores (Potrich, 2024, em Florianópolis; Joseph et al., 2024, com
13.320 registros).

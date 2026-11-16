# Dicionário de dados — base bruta (`dataset_bruto.csv`)

Uma linha por anúncio de apartamento à venda em Passo Fundo/RS coletado em
um portal imobiliário regional. Este documento descreve a **base bruta**, saída
da etapa de coleta; as transformações de pré-processamento e engenharia de
*features* são aplicadas nas etapas seguintes do pipeline.

> **Versão publicada.** Para não identificar o portal, as imobiliárias e os
> corretores, a base deste repositório difere da coletada em quatro pontos: a
> coluna `url` traz só o caminho da página, sem o domínio; `imobiliaria_origem`
> traz um código (`imobiliaria_01` a `imobiliaria_14`, da mais à menos
> frequente) no lugar do domínio; `corretor` e `creci` foram removidas; e, no
> título das páginas que não carregaram, o nome do portal foi trocado por
> "Portal imobiliário". Nenhuma dessas colunas é usada como preditora.

## Identificação e auditoria

| Coluna | Tipo | Descrição |
|---|---|---|
| `url` | texto | URL da página de detalhe (na versão publicada, só o caminho). Chave primária da coleta. |
| `slug` | texto | Último segmento da URL, útil como identificador curto. |
| `codigo_imovel` | texto | Código/referência do imóvel no portal. Usado na deduplicação entre imobiliárias da rede. |
| `titulo` | texto | Título do anúncio. Não entra na modelagem; serve para inspeção manual. |
| `n_caracteres_html` | inteiro | Tamanho do HTML de origem. Páginas anormalmente curtas indicam falha de carregamento. |
| `jsonld_presente` | 0/1 | 1 quando a página trouxe o bloco `schema.org/RealEstateListing`. Registros com 0 dependem só do DOM e merecem conferência. |
| `data_publicacao` | data | `datePosted` do JSON-LD. Permite estimar o tempo de anúncio. |
| `disponibilidade` | texto | `InStock` / `SoldOut`, conforme `offers.availability`. |
| `registro_valido` | 0/1 | 1 quando há preço **e** ao menos uma métrica física (área ou dormitórios). |

## Variável-alvo

| Coluna | Tipo | Unidade | Descrição |
|---|---|---|---|
| `preco` | real | R$ | Preço de venda anunciado. Nulo quando o anúncio traz "sob consulta". **Variável dependente do modelo.** |

## Características intrínsecas

| Coluna | Tipo | Unidade | Descrição |
|---|---|---|---|
| `area_util_m2` | real | m² | Área útil/privativa. Principal preditor contínuo. |
| `area_total_m2` | real | m² | Área total, quando informada. Frequentemente ausente. |
| `dormitorios` | inteiro | — | Número de dormitórios. |
| `suites` | inteiro | — | Número de suítes. Identificada como preditor relevante por Sampaio et al. (2025). |
| `banheiros` | inteiro | — | Número de banheiros. |
| `vagas_garagem` | inteiro | — | Vagas de garagem/box. |
| `andar` | inteiro | — | Andar do apartamento (0 = térreo). Preditor relevante em Jiang et al. (2025). |
| `ano_construcao` | inteiro | ano | Ano de construção, quando informado. Base para derivar a idade do imóvel. |
| `comodos` | inteiro | — | `numberOfRooms` do JSON-LD, quando presente. |
| `mobilia` | texto | — | Estado de mobília ("Sem mobilia", "Semimobiliado", "Mobiliado"). Convertido em variável ordinal ou *dummy* no pré-processamento. |

## Custos recorrentes

| Coluna | Tipo | Unidade | Descrição |
|---|---|---|---|
| `condominio` | real | R$/mês | Taxa de condomínio. *Proxy* do padrão do edifício. |
| `iptu` | real | R$ | Valor do IPTU informado no anúncio. |

## Localização

| Coluna | Tipo | Descrição |
|---|---|---|
| `bairro` | texto | Bairro do imóvel. Convertido em variáveis *dummy* por *one-hot encoding* no pré-processamento. |
| `cidade` | texto | Município, de `addressLocality` no JSON-LD. **É o filtro de escopo do trabalho** — a listagem do portal mistura Passo Fundo e o litoral catarinense, e a seleção é feita aqui, no pós-processamento. |
| `uf` | texto | Unidade federativa, de `addressRegion`. Esperado "RS". |
| `endereco` | texto | Logradouro, quando divulgado. Não usado na modelagem. |
| `latitude` | real | Latitude decimal, extraída do mapa embedado. Base para as distâncias de Haversine. |
| `longitude` | real | Longitude decimal, mesma origem. |
| `geo_origem` | texto | De onde a coordenada foi extraída (`json_ld`, `data_attr`, `iframe:*`, `script:*`, `nao_encontrado`). Permite auditar a confiabilidade da geolocalização. |

## Amenidades (variáveis binárias)

Cada coluna vale 1 quando o termo correspondente aparece na lista de
características ou no corpo do anúncio, e 0 caso contrário. O mapeamento
termo → coluna está em `config.AMENIDADES_MAP`.

| Coluna | Termos reconhecidos |
|---|---|
| `amen_piscina` | piscina |
| `amen_churrasqueira` | churrasqueira, espaço gourmet |
| `amen_salao_festas` | salão de festas |
| `amen_academia` | academia, fitness |
| `amen_elevador` | elevador |
| `amen_portaria` | portaria, porteiro, guarita |
| `amen_sacada` | sacada, varanda, terraço |
| `amen_mobiliado` | mobiliado, semimobiliado |
| `amen_playground` | playground, brinquedoteca |
| `amen_salao_jogos` | salão de jogos |
| `amen_lavanderia` | lavanderia |
| `amen_ar_condicionado` | ar condicionado, split |

| Coluna | Tipo | Descrição |
|---|---|---|
| `amenidades_texto` | texto | Lista original de características, separada por `\|`. Preservada para auditoria e para eventual ampliação do mapeamento. |
| `propriedades_extras` | texto | Pares `nome=valor` de `additionalProperty` do JSON-LD que não têm coluna própria. Fonte para descobrir atributos ainda não mapeados. |

## Convenções

- **Ausência de informação** é representada por célula vazia (`NaN` no pandas),
  nunca por 0. A exceção é a contagem explicitamente negada no anúncio
  ("sem vaga"), convertida para 0.
- **Preços** são armazenados como número, sem símbolo monetário e sem separador
  de milhar. Valores abaixo de R$ 10.000 são descartados por serem
  incompatíveis com venda de apartamento (normalmente são valores de aluguel ou
  erro de cadastro).
- **Coordenadas** fora do *bounding box* do município
  (`config.BBOX_PASSO_FUNDO`) são sinalizadas no relatório de qualidade para
  revisão manual antes do descarte.

## Variação de preço e selos da listagem

Estas colunas vêm do **card da listagem**, não da página do imóvel: o portal
não repete nenhuma delas na ficha individual. Sem elas, a única forma de
observar variação de preço seria repetir a coleta com semanas de intervalo.

| Coluna | Tipo | Unidade | Descrição |
|---|---|---|---|
| `preco_anterior` | real | R$ | Preço riscado no card, quando existe (~2% dos anúncios). É o valor pedido antes da redução. |
| `variacao_preco_pct` | real | % | `(preco − preco_anterior) / preco_anterior × 100`. Negativo em toda redução observada. |
| `teve_reducao_preco` | 0/1 | — | 1 quando há preço anterior **e** o atual é menor. Candidata a variável de controle: imóvel que já baixou tende a estar acima do preço de mercado. |
| `preco_card` | real | R$ | Preço exibido no card. Serve de conferência contra `preco` — a divergência gera o alerta `preco_card!=ficha`. |
| `badges` | texto | — | Selos padronizados do portal, separados por ` \| ` ("Baixou valor", "Novidade", "Em construcao", "Mobiliado", "Semimobiliado", "Exclusividade", "Lancamento", …). Lista fechada em `config.BADGES_CANONICOS`. |
| `destaques_texto` | texto | — | Chamadas livres digitadas pelo corretor no mesmo elemento dos selos ("3 box de garagens", "ROOFTOP COM PISCINA PRIVATIVA"). **Auditoria apenas** — cada valor é praticamente único, não serve como categoria. |

Atenção: `badges` traz `Mobiliado` como selo declarado pela imobiliária,
enquanto `amen_mobiliado` é inferido do texto do anúncio. Quando o selo
contradiz o campo `mobilia` do JSON-LD, a linha recebe o alerta
`mobilia_contraditoria`.

## Anunciante

| Coluna | Tipo | Descrição |
|---|---|---|
| `corretor` | texto | Nome do corretor responsável ("Agenciador do imóvel"). Presente em ~71% dos anúncios. **Removida da versão publicada.** |
| `creci` | texto | CRECI do corretor. Capturado ancorado no nome — a página exibe mais de um CRECI. **Removida da versão publicada.** |
| `imobiliaria_origem` | texto | Domínio da imobiliária **dona** do anúncio, do campo `url` do JSON-LD (~99% dos anúncios). O portal reúne várias imobiliárias: cada imobiliária tem política própria de preço e de preenchimento do cadastro. Candidata natural a **efeito fixo** na modelagem. |

## Qualidade do cadastro

| Coluna | Tipo | Descrição |
|---|---|---|
| `rotulo_preco` | texto | Rótulo que precede o valor na ficha: "Valor do imóvel" ou "A partir de". |
| `alertas_qualidade` | texto | Inconsistências **do cadastro do portal**, separadas por `; `. Critério explícito de exclusão na modelagem. |

Alertas possíveis:

| Alerta | Significado |
|---|---|
| `preco_a_partir_de` | Rótulo "A partir de": preço de tabela de lançamento, não preço firme de uma unidade. **12% dos anúncios.** Não misturar com preço fechado na variável dependente. |
| `area_total<privativa` | Erro de cadastro: área total menor que a privativa. 7 em 300 no cache. |
| `preco_card!=ficha` | O preço da listagem diverge do preço da ficha — cadastro em atualização. |
| `mobilia_contraditoria` | O campo `mobilia` do JSON-LD contradiz o selo da listagem. |
| `sem_preco`, `sem_geo`, `sem_ano`, `sem_banheiros`, `sem_vagas`, `sem_dormitorios`, `sem_bairro` | Campo ausente na origem. `sem_ano` atinge ~82% dos anúncios: o portal raramente publica o ano de construção. |

## Variáveis derivadas nas etapas seguintes

Não fazem parte da base bruta, mas estão previstas na metodologia:

| Coluna | Origem |
|---|---|
| `dist_shopping_km` | Menor distância de Haversine aos 2 shoppings mapeados. |
| `dist_hospital_km` | Menor distância aos 3 hospitais mapeados. |
| `dist_ensino_km` | Menor distância às 5 instituições de ensino mapeadas. |
| `preco_m2` | `preco / area_util_m2` — usado na análise exploratória e na detecção de *outliers*. |
| `idade_imovel` | Ano da coleta − `ano_construcao`. |

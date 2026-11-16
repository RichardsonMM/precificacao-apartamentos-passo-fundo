"""
Configuracao central da coleta de dados.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_HTML_DIR = DATA_DIR / "raw_html"          # HTML bruto (reprodutibilidade)
OUTPUT_DIR = DATA_DIR / "output"              # CSV / JSONL finais
LOG_DIR = BASE_DIR / "logs"

RAW_RECORDS_JSONL = OUTPUT_DIR / "anuncios_brutos.jsonl"   # checkpoint incremental
DATASET_CSV = OUTPUT_DIR / "dataset_bruto.csv"             # base bruta consolidada
URLS_FILE = OUTPUT_DIR / "urls_coletadas.txt"              # indice de URLs de detalhe
CARDS_FILE = OUTPUT_DIR / "cards_listagem.json"             # dados que so existem no card

for _d in (RAW_HTML_DIR, OUTPUT_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Fonte de dados
# ---------------------------------------------------------------------------
# O endereco do portal nao e versionado: defina a variavel de ambiente
# PORTAL_URL antes de rodar a coleta ou a conferencia dos anuncios.
BASE_URL = os.environ.get("PORTAL_URL", "").rstrip("/")

# Template da pagina de listagem. {page} e substituido pelo numero da pagina.
#
# Confirmado na inspecao (11/08/2026): o portal normaliza a URL para
#   /comprar-imoveis/apartamentos/passo-fundo?operacao=vendas&tipoId=1&ordem=1
# onde tipoId=1 corresponde a apartamentos e operacao=vendas ao segmento de
# venda. O parametro de paginacao foi confirmado pelo diagnostico (16/08/2026)
# - ver PAGINACAO_PARAM abaixo.
#
# FILTRO DE CIDADE (revisto em 16/08/2026): o segmento "/passo-fundo" da URL de
# fato nao filtra nada - foi o que a inspeccao de 11/08 observou. Mas o
# parametro de query "cidade=Passo+Fundo" FUNCIONA: testado em 20 paginas
# consecutivas (800 anuncios, sem repeticao) e confirmado abrindo os anuncios,
# cuja cidade no JSON-LD veio integralmente como Passo Fundo/RS.
#
# Filtrar na origem evita percorrer os anuncios do litoral catarinense, que
# respondem pela maior parte do acervo da rede.
LISTING_URL_TEMPLATE = (
    BASE_URL + "/comprar-imoveis/apartamentos/passo-fundo"
    "?operacao=vendas&tipoId=1&cidade=Passo+Fundo&ordem=1&{pagina_param}={page}"
)
# Confirmado por diagnostico.py em 16/08/2026: dos candidatos testados
# (pagina, page, p, pag, offset, start), apenas "page" trouxe anuncios novos na
# pagina 2; os demais devolveram a mesma primeira pagina.
PAGINACAO_PARAM = "page"

# Filtro de municipio no pos-processamento. Com o filtro da URL funcionando ele
# passa a ser redundante, mas fica como rede de seguranca: se o portal mudar o
# comportamento do parametro, anuncios de outra cidade nao entram na base sem
# que ninguem perceba.
CIDADE_ALVO = "passo fundo"
UF_ALVO = "RS"

# Semente unica do projeto. A coleta a usa para sortear amostras parciais; as
# etapas seguintes (divisao treino/teste, validacao cruzada, modelos) devem
# reutilizar a mesma, para que todo o pipeline seja reproduzivel de ponta a ponta.
SEMENTE = 42

# Numero maximo de paginas percorridas (protecao contra loop infinito).
MAX_PAGES = 200
ITENS_POR_PAGINA = 40        # medido no diagnostico (16/08/2026)

# ---------------------------------------------------------------------------
# Renderizacao
# ---------------------------------------------------------------------------
# O portal e uma SPA em Nuxt/Vue com renderizacao no cliente: as paginas de
# listagem chegam como esqueletos e so recebem conteudo apos a execucao do
# JavaScript. A coleta tenta primeiro requests (barato) e recorre ao navegador
# headless apenas quando o HTML vem incompleto.
USAR_NAVEGADOR = True         # False = somente requests (mais rapido, menos robusto)
NAVEGADOR_HEADLESS = True

# ---------------------------------------------------------------------------
# Politica de requisicao (coleta responsavel)
# ---------------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 30          # segundos
DELAY_BETWEEN_REQUESTS = 2.0  # segundos (pausa fixa entre requisicoes)
DELAY_JITTER = 1.0            # segundos (variacao aleatoria adicional)
MAX_RETRIES = 4
BACKOFF_FACTOR = 2.0          # espera = BACKOFF_FACTOR ** tentativa

# ---------------------------------------------------------------------------
# Seletores CSS
# ---------------------------------------------------------------------------
# Cada campo aceita uma LISTA de seletores, avaliados em ordem ate o primeiro
# que retornar valor. Isso da tolerancia a variacoes de layout entre anuncios.
#
# OBSERVACAO METODOLOGICA: o portal usa CSS utilitario (Tailwind), cujas classes
# mudam a cada build. Por isso a extracao se apoia prioritariamente no JSON-LD
# (schema.org/RealEstateListing), que e tipado e estavel; os seletores abaixo
# cobrem apenas os campos ausentes naquele bloco.

SELECTORS_LISTAGEM = {
    # Elemento que envolve cada anuncio na pagina de resultados
    "card": ["div.hoverCard1"],
    # Link (<a href>) para a pagina de detalhe do imovel: /imovel/{slug}/{id}
    "link_detalhe": ['a[href*="/imovel/"]'],
    # Indicador de "proxima pagina" (usado para saber quando parar)
    "proxima_pagina": ['a[rel="next"]', "button.proximaPagina"],
}

# Cards da listagem (src/cards.py). Classes semanticas do portal, estaveis entre
# builds - ao contrario das utilitarias do Tailwind. Verificado em 16/08/2026:
# cardsValor em 40/40 cards da pagina 1, cardsValorDe em 4/40 (preco riscado).
SELECTORS_CARD = {
    "card": "div.hoverCard1",
    "link_detalhe": 'a[href*="/imovel/"]',
    "preco": ".cardsValor",
    "preco_anterior": ".cardsValorDe",
    "badge": ".cardItemDestaques",
    "letra_codigo": ".letraImovelCodigo",
}

# O portal usa o MESMO elemento (.cardItemDestaques) para duas coisas muito
# diferentes: selos padronizados, escolhidos numa lista fechada pelo sistema, e
# chamadas livres digitadas pelo corretor ("3 box de garagens", "ROOFTOP COM
# PISCINA PRIVATIVA", o proprio nome do edificio). Medido nas paginas 1 a 3
# (120 cards): 95 selos padronizados e 43 chamadas livres.
#
# Misturar os dois numa unica variavel produziria uma categoria com dezenas de
# niveis de contagem 1 - inutil para modelagem. A lista abaixo mapeia o texto
# do selo (sem acento, minusculo) para o rotulo canonico; o que nao casar vai
# para a coluna de auditoria `destaques_texto`.
#
# Atencao a ordem de teste em cards.py: "semimobiliado" precisa ser avaliado
# antes de "mobiliado", que e substring dele.
BADGES_CANONICOS = {
    "semimobiliado": "Semimobiliado",
    "semi mobiliado": "Semimobiliado",
    "semi-mobiliado": "Semimobiliado",
    "mobiliado": "Mobiliado",
    "mobiliada": "Mobiliado",
    "baixou valor": "Baixou valor",
    "baixou valor!": "Baixou valor",
    "novidade": "Novidade",
    "video": "Video",
    "tour virtual": "Tour virtual",
    "exclusividade": "Exclusividade",
    "em construcao": "Em construcao",
    "lancamento": "Lancamento",
    "pronto para morar": "Pronto para morar",
    "pronto para morar!": "Pronto para morar",
    "ultima unidade": "Ultima unidade",
    "ultima unidade!": "Ultima unidade",
    "oportunidade": "Oportunidade",
    "revenda": "Revenda",
    "desocupado": "Desocupado",
    "temporada": "Temporada",
}

# Blocos da pagina de detalhe que NAO pertencem ao imovel anunciado e por isso
# sao removidos do DOM antes do parsing (ver parsers.isolar_anuncio).
#
# A pagina termina com uma vitrine de imoveis relacionados, cada um num card
# identico ao da listagem ("hoverCard1"). Como parte da extracao varre texto
# livre - amenidades, contadores "N banheiros", maior valor em R$ -, esses cards
# contaminavam o registro do imovel lido. Medido em 20 anuncios (16/08/2026):
# amenidades saindo em 100% e banheiros=1 num apartamento de 3 suites.
SELECTORS_FORA_DO_ANUNCIO = [
    ".hoverCard1",       # cards de imoveis relacionados
    '[id^="logos"]',     # rodape com os logotipos das imobiliarias da rede
]

SELECTORS_DETALHE = {
    "titulo": [],
    "preco": [],
    "area_util": [],
    "dormitorios": [],
    "suites": [],
    "banheiros": [],
    "garagem": [],
    "andar": [],
    "bairro": [],
    "cidade": [],
    "endereco": [],
    "codigo_imovel": [],
    "condominio": [],
    "iptu": [],
    # Bloco de caracteristicas/amenidades (lista de <li> ou similar)
    "amenidades": [],
    # Tabela generica rotulo -> valor, quando o portal usa esse padrao
    "ficha_tecnica_linha": [],
    "ficha_tecnica_rotulo": [],
    "ficha_tecnica_valor": [],
}

# ---------------------------------------------------------------------------
# Amenidades: mapeamento de termos do anuncio -> coluna booleana do dataset
# ---------------------------------------------------------------------------
AMENIDADES_MAP = {
    "amen_piscina": ["piscina"],
    "amen_churrasqueira": ["churrasqueira", "espaco gourmet", "espaço gourmet"],
    "amen_salao_festas": ["salao de festas", "salão de festas", "salao festas"],
    "amen_academia": ["academia", "fitness", "espaco fitness", "espaço fitness"],
    "amen_elevador": ["elevador"],
    "amen_portaria": ["portaria", "porteiro", "guarita"],
    "amen_sacada": ["sacada", "varanda", "terraco", "terraço"],
    "amen_mobiliado": ["mobiliado", "semimobiliado", "semi-mobiliado"],
    "amen_playground": ["playground", "brinquedoteca"],
    "amen_salao_jogos": ["salao de jogos", "salão de jogos"],
    "amen_lavanderia": ["lavanderia"],
    "amen_ar_condicionado": ["ar condicionado", "ar-condicionado", "split"],
    "amen_aceita_pet": ["aceita pet", "pet friendly", "pet-friendly"],
}

# ---------------------------------------------------------------------------
# Pontos de interesse de Passo Fundo (Tabela/Figura 2 da proposta)
# Coordenadas (lat, lon) obtidas do OpenStreetMap em 05/10/2026, via Nominatim
# (busca por nome) e Overpass (amenity=hospital no municipio), e conferidas
# contra a Figura 2 da proposta. O Hospital Municipal consta no OSM pelo nome
# oficial, Hospital Beneficente Dr. Cesar Santos.
# ---------------------------------------------------------------------------
PONTOS_INTERESSE = {
    "shopping": {
        "Passo Fundo Shopping": (-28.271000, -52.385462),   # Av. Presidente Vargas, 1610
        "Bella Citta": (-28.262744, -52.409594),            # R. Coronel Chicuta, 355
    },
    "hospital": {
        "Sao Vicente de Paulo": (-28.262317, -52.417013),   # R. Uruguai, 2050
        "Hospital de Clinicas": (-28.256247, -52.403069),   # R. Tiradentes, 295
        "Hospital Municipal": (-28.258489, -52.393858),     # Hosp. Benef. Dr. Cesar Santos
    },
    "ensino": {
        "UPF": (-28.234533, -52.378616),                    # Campus I, Bairro Sao Jose
        "Atitus Educacao": (-28.265197, -52.397109),        # R. Gen. Prestes Guimaraes
        "Anhanguera": (-28.260201, -52.408324),             # R. Paissandu
        "Colegio Notre Dame": (-28.264629, -52.412975),     # Av. Brasil Oeste
        "Colegio Marista": (-28.258119, -52.406104),        # Marista Conceicao, R. Paissandu
    },
}

# ---------------------------------------------------------------------------
# Validacao geografica: bounding box aproximado do municipio de Passo Fundo/RS
# Usado para descartar coordenadas claramente erradas.
# ---------------------------------------------------------------------------
BBOX_PASSO_FUNDO = {
    "lat_min": -28.45,
    "lat_max": -28.05,
    "lon_min": -52.60,
    "lon_max": -52.25,
}

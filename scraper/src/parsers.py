"""
Parsing das paginas de listagem e de detalhe do portal.

Estrategia em duas camadas:
  1. Seletores CSS explicitos definidos em config.SELECTORS_* (preenchidos
     apos a inspecao do portal).
  2. Heuristica generica de "ficha tecnica" (pares rotulo -> valor), que cobre
     variacoes de layout e serve de fallback quando o seletor especifico falha.

Essa redundancia reduz a perda de registros quando o portal altera o layout
durante o periodo de coleta.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

import config
from src import geo, jsonld, normalize
from src.normalize import extrair_area, extrair_inteiro, extrair_preco, limpar_texto, sem_acento

logger = logging.getLogger(__name__)


def fazer_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def isolar_anuncio(soup: BeautifulSoup) -> int:
    """
    Remove do DOM os blocos que nao pertencem ao imovel anunciado.

    Motivacao: parte da extracao trabalha sobre texto livre da pagina inteira
    (amenidades, contadores "N banheiros", maior valor em R$). A pagina de
    detalhe termina com uma vitrine de imoveis relacionados, e o texto deles
    entrava no registro do imovel lido - um card vizinho intitulado
    "... MOBILIADO" ligava o amen_mobiliado, e a primeira ocorrencia de
    "N banheiros" podia vir do card errado.

    Altera a soup no lugar e devolve quantos blocos removeu. Zero remocoes
    significa que o layout mudou: o parsing continua funcionando, porem sem
    protecao contra a contaminacao, e por isso o caso e registrado em log.

    Deve ser chamada DEPOIS da leitura do JSON-LD, que vive no <head>.
    """
    removidos = 0
    for seletor in config.SELECTORS_FORA_DO_ANUNCIO:
        for elemento in soup.select(seletor):
            elemento.decompose()
            removidos += 1
    if not removidos:
        logger.warning("nenhum bloco externo removido - conferir SELECTORS_FORA_DO_ANUNCIO")
    return removidos


# ---------------------------------------------------------------------------
# Utilitarios de selecao
# ---------------------------------------------------------------------------
def _primeiro_texto(soup: BeautifulSoup, seletores: list[str]) -> str:
    """Retorna o texto do primeiro seletor da lista que casar com algo."""
    for sel in seletores or []:
        try:
            el = soup.select_one(sel)
        except Exception:  # seletor invalido
            logger.debug("seletor invalido ignorado: %s", sel)
            continue
        if el:
            texto = limpar_texto(el.get_text(" "))
            if texto:
                return texto
    return ""


def _todos_textos(soup: BeautifulSoup, seletores: list[str]) -> list[str]:
    for sel in seletores or []:
        try:
            els = soup.select(sel)
        except Exception:
            continue
        if els:
            return [t for t in (limpar_texto(e.get_text(" ")) for e in els) if t]
    return []


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
def extrair_links_listagem(html: str, base_url: str = config.BASE_URL) -> list[str]:
    """Retorna as URLs absolutas das paginas de detalhe presentes na listagem."""
    soup = fazer_soup(html)
    urls: list[str] = []

    # Camada 1: seletores configurados
    for sel in config.SELECTORS_LISTAGEM.get("link_detalhe") or []:
        try:
            for a in soup.select(sel):
                href = a.get("href")
                if href:
                    urls.append(urljoin(base_url, href))
        except Exception:
            continue
        if urls:
            break

    # Camada 2 (fallback): heuristica sobre o padrao de URL de imovel
    if not urls:
        padrao = re.compile(r"/(imovel|imoveis|apartamento|detalhe|ref|codigo)[/-]", re.I)
        vistos = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if padrao.search(href) and href not in vistos:
                vistos.add(href)
                urls.append(urljoin(base_url, href))
        if urls:
            logger.debug("links obtidos por heuristica de URL (%d)", len(urls))

    # Deduplica preservando a ordem e descartando ancoras/query irrelevantes
    unicas, vistos = [], set()
    for u in urls:
        limpa = u.split("#")[0]
        if limpa not in vistos:
            vistos.add(limpa)
            unicas.append(limpa)
    return unicas


def tem_proxima_pagina(html: str) -> bool:
    soup = fazer_soup(html)
    for sel in config.SELECTORS_LISTAGEM.get("proxima_pagina") or []:
        try:
            if soup.select_one(sel):
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Ficha tecnica generica (rotulo -> valor)
# ---------------------------------------------------------------------------
_ROTULOS = {
    "preco": ["preco", "preco de venda", "valor", "valor de venda", "valor do imovel", "venda"],
    "area_util": ["area util", "area privativa", "area interna", "metragem", "area construida", "area"],
    "area_total": ["area total", "area do terreno"],
    "dormitorios": ["dormitorio", "dormitorios", "quarto", "quartos"],
    "suites": ["suite", "suites"],
    "banheiros": ["banheiro", "banheiros", "wc", "lavabo"],
    "garagem": ["garagem", "vaga", "vagas", "box", "estacionamento"],
    "andar": ["andar", "pavimento", "piso"],
    "bairro": ["bairro"],
    "cidade": ["cidade", "municipio"],
    "condominio": ["condominio", "valor do condominio", "taxa de condominio"],
    "iptu": ["iptu"],
    "codigo_imovel": ["codigo", "referencia", "ref", "cod"],
    "tipo_imovel": ["tipo", "tipo de imovel", "categoria"],
    "ano_construcao": ["ano de construcao", "ano construcao", "idade"],
}


def _construir_ficha(soup: BeautifulSoup) -> dict[str, str]:
    """
    Varre a pagina em busca de pares rotulo/valor, cobrindo os padroes mais
    comuns: <table><tr><th|td>, <dl><dt><dd>, e <li>Rotulo: Valor</li>.
    """
    ficha: dict[str, str] = {}

    def registrar(rotulo: str, valor: str) -> None:
        chave = sem_acento(rotulo).rstrip(":").strip()
        valor = limpar_texto(valor)
        if chave and valor and chave not in ficha:
            ficha[chave] = valor

    # tabelas
    for tr in soup.find_all("tr"):
        celulas = tr.find_all(["th", "td"])
        if len(celulas) >= 2:
            registrar(celulas[0].get_text(" "), celulas[1].get_text(" "))

    # listas de definicao
    for dl in soup.find_all("dl"):
        dts, dds = dl.find_all("dt"), dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            registrar(dt.get_text(" "), dd.get_text(" "))

    # itens "Rotulo: Valor"
    for el in soup.find_all(["li", "p", "span", "div"]):
        if el.find(["li", "p", "div", "table"]):  # so folhas, evita duplicar
            continue
        texto = limpar_texto(el.get_text(" "))
        if ":" in texto and len(texto) < 120:
            rotulo, _, valor = texto.partition(":")
            registrar(rotulo, valor)

    return ficha


def _da_ficha(ficha: dict[str, str], campo: str) -> str:
    """Busca o valor de um campo canonico entre os rotulos conhecidos."""
    for termo in _ROTULOS.get(campo, []):
        if termo in ficha:
            return ficha[termo]
    # correspondencia parcial
    for termo in _ROTULOS.get(campo, []):
        for chave, valor in ficha.items():
            if termo in chave:
                return valor
    return ""


# ---------------------------------------------------------------------------
# Contadores no corpo do anuncio ("3 dorm.", "2 vagas", "85 m2")
# ---------------------------------------------------------------------------
_CONTADORES = [
    ("dormitorios", r"(\d+)\s*(?:dorm(?:it[oó]rio)?s?|quartos?)\b"),
    ("suites", r"(\d+)\s*su[ií]tes?\b"),
    ("banheiros", r"(\d+)\s*(?:banheiros?|wc)\b"),
    ("garagem", r"(\d+)\s*(?:vagas?|garagens?|box(?:es)?)\b"),
    ("area_util", r"([\d.,]+)\s*m[²2]\b"),
]


# ---------------------------------------------------------------------------
# Bloco de estatisticas do anuncio
# ---------------------------------------------------------------------------
# Estrutura observada no portal (16/08/2026), sempre no formato VALOR + ROTULO:
#
#   2 Dormitorios ( sendo 1 suite )  2 Banheiros  1 Lavabo  2 Vagas
#   Areas 147,87 m2 Area Total   Areas 111,92 m2 Area Privativa
#   Julho 2027 Previsao   Frente Posicao   Norte Posicao Solar   2 ou + Elevadores
#
# O valor PRECEDE o rotulo, ao contrario de uma ficha tecnica convencional. Por
# isso os padroes abaixo ancoram no rotulo e capturam para tras.
_POSICOES = ("frente", "fundos", "lateral esquerda", "lateral direita", "lateral")
_ORIENTACOES = ("nordeste", "noroeste", "sudeste", "sudoeste", "norte", "sul", "leste", "oeste")

_ESTATISTICAS = [
    ("area_total_m2", r"([\d.,]+)\s*m2\s*area total"),
    ("area_privativa_m2", r"([\d.,]+)\s*m2\s*area privativa"),
    ("lavabos", r"(\d+)\s*lavabos?\b"),
    # "sendo 1 suite" aparece entre parenteses logo apos os dormitorios
    ("suites", r"sendo\s*(\d+)\s*suites?\b"),
    # "2 ou + Elevadores" e um piso, nao a contagem exata - ver observacao no
    # DICIONARIO_DE_DADOS. "1 Elevador" e exato.
    # Atencao ao plural: "elevadores?" casaria com "elevadore"+"s", nunca com o
    # singular "1 Elevador" - que e o caso mais comum no portal.
    ("elevadores", r"(\d+)\s*(?:ou\s*\+\s*)?elevador(?:es)?\b"),
    ("posicao_solar", rf"({'|'.join(_ORIENTACOES)})\s*posicao solar"),
    # A negativa evita que "Posicao Solar" seja capturado como "Posicao"
    ("posicao", rf"({'|'.join(_POSICOES)})\s*posicao(?!\s*solar)"),
    ("previsao_entrega", r"([a-z]+\s*/?\s*\d{4})\s*previsao"),
]


def _do_bloco_estatisticas(texto_pagina: str) -> dict[str, str]:
    """Le o bloco de cards do topo do anuncio (ver comentario acima)."""
    alvo = sem_acento(texto_pagina).lower()
    achados: dict[str, str] = {}
    for campo, padrao in _ESTATISTICAS:
        m = re.search(padrao, alvo)
        if m:
            achados[campo] = m.group(1).strip()

    # "Area util" do dataset e a area privativa (mesma grandeza do floorSize do
    # JSON-LD). Sem esse apelido, o fallback por contador pegaria a primeira
    # medida em m2 da pagina, que e a area TOTAL - superestimando o imovel.
    if "area_privativa_m2" in achados:
        achados["area_util"] = achados["area_privativa_m2"]
    return achados


def _bairro_do_endereco(texto_pagina: str) -> str:
    """
    Extrai o bairro da linha de endereco do DOM.

    O JSON-LD traz apenas logradouro e numero ("Morom, 1624"), mas o cabecalho
    do anuncio exibe o endereco completo no formato

        Major Joao Schell, no 600, Vergueiro - Passo Fundo - RS

    ou seja, o bairro e o trecho entre a ultima virgula e o nome da cidade.
    Medido em 300 anuncios do cache: presente em praticamente todos.
    """
    # A busca roda sobre o texto ORIGINAL, e nao sobre a versao sem acentos,
    # para que o bairro entre na base como "Sao Cristovao" e nao perca a grafia
    # correta ("Sao Cristovao" -> "Sao Cristovao" fica ilegivel nas tabelas do
    # trabalho). O nome do municipio nao tem acentos, entao re.I basta aqui.
    m = re.search(
        rf",\s*([^,|]{{2,40}}?)\s*-\s*{config.CIDADE_ALVO}\s*-\s*{config.UF_ALVO}\b",
        texto_pagina,
        re.I,
    )
    return limpar_texto(m.group(1)) if m else ""


# O bloco do agenciador aparece como "Agenciador do imovel <nome> CRECI <numero>".
# A pagina traz mais de um CRECI - o do corretor e o da propria rede, no rodape
# ("<nome do portal> CRECI 0") -, entao o numero e capturado ANCORADO no
# nome do corretor, nunca por uma busca solta por "CRECI".
_PADRAO_AGENCIADOR = re.compile(
    r"Agenciador do im[oó]vel\s+(.{3,60}?)\s+CRECI\s*[:\-]?\s*([\d][\d./A-Z-]*)", re.I
)

# Rotulo que precede o valor na ficha. "A partir de" indica preco de tabela de
# lancamento, e nao preco firme de uma unidade especifica - ver avaliar_qualidade.
_PADRAO_ROTULO_PRECO = re.compile(
    r"(A partir de|Valor do im[oó]vel|Valor da loca[cç][aã]o)", re.I
)


def _do_agenciador(texto_pagina: str) -> dict[str, str]:
    """Nome e CRECI do corretor responsavel pelo anuncio."""
    m = _PADRAO_AGENCIADOR.search(texto_pagina)
    if not m:
        return {}
    return {"corretor": limpar_texto(m.group(1)), "creci": limpar_texto(m.group(2))}


def _dos_contadores(texto_pagina: str) -> dict[str, str]:
    achados: dict[str, str] = {}
    alvo = sem_acento(texto_pagina)
    for campo, padrao in _CONTADORES:
        m = re.search(padrao, alvo, re.I)
        if m:
            achados[campo] = m.group(1)
    return achados


# ---------------------------------------------------------------------------
# Qualidade do registro
# ---------------------------------------------------------------------------
def avaliar_qualidade(registro: dict) -> str:
    """
    Marca inconsistencias do CADASTRO DO PORTAL - nao da raspagem.

    A coluna resultante serve de criterio explicito de exclusao na etapa de
    modelagem: em vez de descartar linhas por inspecao visual, o trabalho pode
    declarar "foram removidos os registros com alerta X" e justificar.

    O alerta mais importante e `preco_a_partir_de`: o valor anunciado nesses
    casos e preco de tabela de lancamento, nao o preco firme de uma unidade
    especifica. Medido no cache: 40 dos 362 anuncios (11%). Misturados a
    negocios fechados, contaminam a variavel dependente.
    """
    alertas: list[str] = []

    total, privativa = registro.get("area_total_m2"), registro.get("area_util_m2")
    if total is not None and privativa is not None and total < privativa:
        alertas.append("area_total<privativa")

    if registro.get("rotulo_preco", "").lower().startswith("a partir de"):
        alertas.append("preco_a_partir_de")

    for campo, alerta in (
        ("preco", "sem_preco"),
        ("latitude", "sem_geo"),
        ("ano_construcao", "sem_ano"),
        ("banheiros", "sem_banheiros"),
        ("vagas_garagem", "sem_vagas"),
        ("dormitorios", "sem_dormitorios"),
        ("bairro", "sem_bairro"),
    ):
        if registro.get(campo) in (None, ""):
            alertas.append(alerta)

    # O preco do card e o da ficha vem de fontes diferentes (HTML da listagem x
    # JSON-LD do anuncio). Divergencia significa cadastro em atualizacao.
    card, ficha = registro.get("preco_card"), registro.get("preco")
    if card and ficha and abs(card - ficha) > 0.01:
        alertas.append("preco_card!=ficha")

    # O campo Mobilia do JSON-LD contradiz o selo da listagem. Visto no portal:
    # "Sem mobilia" em anuncio cujo selo e "Mobiliado".
    mobilia = sem_acento(str(registro.get("mobilia") or "")).lower()
    if "Mobiliado" in (registro.get("badges") or "") and "sem mobilia" in mobilia:
        alertas.append("mobilia_contraditoria")

    return "; ".join(alertas)


# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------
def parse_detalhe(html: str, url: str, card: dict | None = None) -> dict:
    """
    Extrai o registro completo de um anuncio. Sempre retorna um dict.

    `card` traz os campos que existem apenas na listagem (preco anterior e
    selos) - ver src/cards.py. E opcional: uma ficha reprocessada sem a
    listagem correspondente continua sendo extraida normalmente, apenas sem
    essas colunas.
    """
    soup = fazer_soup(html)

    # Lidos ANTES do recorte: o JSON-LD fica no <head>, fora da area do anuncio.
    dados_ld = jsonld.extrair(soup)
    coords = geo.extrair_de_jsonld(soup)

    isolar_anuncio(soup)

    texto_pagina = limpar_texto(soup.get_text(" "))
    ficha = _construir_ficha(soup)
    estatisticas = _do_bloco_estatisticas(texto_pagina)
    contadores = _dos_contadores(texto_pagina)

    def valor(campo: str) -> str:
        """
        Precedencia: seletor explicito > bloco de estatisticas > ficha tecnica >
        contadores no texto.

        O bloco de estatisticas vem antes da ficha e dos contadores porque esta
        ancorado em rotulos ("2 Banheiros", "1 Lavabo"), enquanto os contadores
        sao regex sobre texto livre e pegam a primeira ocorrencia que aparecer -
        inclusive a da descricao redigida pelo corretor.
        """
        v = _primeiro_texto(soup, config.SELECTORS_DETALHE.get(campo, []))
        if v:
            return v
        v = estatisticas.get(campo, "")
        if v:
            return v
        v = _da_ficha(ficha, campo)
        if v:
            return v
        return contadores.get(campo, "")

    # --- identificacao ---
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    titulo = valor("titulo") or limpar_texto(soup.title.get_text() if soup.title else "")

    # --- preco de venda ---
    # Precedencia: seletor explicito (confiavel, definido apos a inspecao) >
    # maior valor em R$ da pagina (o preco de venda supera condominio e IPTU) >
    # rotulo da ficha tecnica.
    preco = extrair_preco(_primeiro_texto(soup, config.SELECTORS_DETALHE.get("preco", [])))
    if preco is None:
        candidatos = [
            normalize.maior_valor_em_reais(texto_pagina),
            extrair_preco(_da_ficha(ficha, "preco")),
        ]
        candidatos = [c for c in candidatos if c is not None]
        preco = max(candidatos) if candidatos else None

    # --- amenidades ---
    itens_amenidades = _todos_textos(soup, config.SELECTORS_DETALHE.get("amenidades", []))
    flags = normalize.mapear_amenidades(itens_amenidades, texto_extra=texto_pagina)

    # --- anunciante e rotulo do preco ---
    agenciador = _do_agenciador(texto_pagina)
    m_rotulo = _PADRAO_ROTULO_PRECO.search(texto_pagina)
    rotulo_preco = limpar_texto(m_rotulo.group(1)) if m_rotulo else ""

    # --- coordenadas ---
    # A varredura de fallback recebe o HTML ja recortado: coordenadas de um
    # imovel relacionado tambem caem dentro do bbox de Passo Fundo e passariam
    # despercebidas na validacao, deslocando as distancias aos pontos de
    # interesse. O custo de serializar a soup so ocorre quando o JSON-LD nao
    # trouxe as coordenadas.
    coords = coords or geo.extrair_coordenadas(soup, str(soup))

    registro = {
        # identificacao
        "url": url,
        "slug": slug,
        # O codigo exibido no anuncio ("V 63178") e a letra da operacao seguida
        # do id que ja vem na URL (/imovel/{slug}/63178). Derivar da URL e mais
        # seguro que ler do DOM, porque a pagina repete a classe do codigo nos
        # cards de imoveis relacionados. A letra e fixa porque a coleta e
        # restrita a vendas (config.LISTING_URL_TEMPLATE).
        "codigo_imovel": f"V{slug}" if slug.isdigit() else valor("codigo_imovel"),
        "titulo": titulo,
        # alvo
        "preco": preco,
        # intrinsecas
        "area_util_m2": extrair_area(valor("area_util")),
        "area_total_m2": extrair_area(estatisticas.get("area_total_m2", "")),
        "dormitorios": extrair_inteiro(valor("dormitorios")),
        "suites": extrair_inteiro(valor("suites")),
        "banheiros": extrair_inteiro(valor("banheiros")),
        "lavabos": extrair_inteiro(valor("lavabos")),
        "vagas_garagem": extrair_inteiro(valor("garagem")),
        "elevadores": extrair_inteiro(valor("elevadores")),
        "posicao": valor("posicao"),
        "posicao_solar": valor("posicao_solar"),
        "previsao_entrega": valor("previsao_entrega"),
        "andar": normalize.extrair_andar(valor("andar")),
        "ano_construcao": extrair_inteiro(_da_ficha(ficha, "ano_construcao")),
        # custos recorrentes
        "condominio": normalize.extrair_valor_monetario(valor("condominio")),
        "iptu": normalize.extrair_valor_monetario(valor("iptu")),
        # localizacao
        "bairro": valor("bairro") or _bairro_do_endereco(texto_pagina),
        "cidade": valor("cidade") or "Passo Fundo",
        "endereco": valor("endereco"),
        "latitude": coords.get("latitude"),
        "longitude": coords.get("longitude"),
        "geo_origem": coords.get("geo_origem"),
        # anunciante
        "corretor": agenciador.get("corretor", ""),
        "creci": agenciador.get("creci", ""),
        # auditoria
        "rotulo_preco": rotulo_preco,
        "amenidades_texto": " | ".join(itens_amenidades) if itens_amenidades else "",
        "n_caracteres_html": len(html),
    }
    registro.update(flags)

    # ------------------------------------------------------------------
    # Sobreposicao do JSON-LD (schema.org/RealEstateListing)
    # ------------------------------------------------------------------
    # Fonte tipada e estavel: tem precedencia sobre o parsing do DOM para os
    # campos que fornece. O DOM continua respondendo pelos campos ausentes no
    # JSON-LD (bairro, suites, banheiros, andar, condominio, IPTU).
    registro["jsonld_presente"] = 0
    if dados_ld:
        amen_ld = dados_ld.pop("amenidades_jsonld", None)
        extras_ld = dados_ld.pop("propriedades_extras", None)

        for campo, valor_ld in dados_ld.items():
            if valor_ld not in (None, "", []):
                registro[campo] = valor_ld

        if amen_ld:
            registro.update(normalize.mapear_amenidades(amen_ld, texto_extra=texto_pagina))
            anteriores = registro.get("amenidades_texto") or ""
            registro["amenidades_texto"] = " | ".join(
                dict.fromkeys([*amen_ld, *(anteriores.split(" | ") if anteriores else [])])
            )
        if extras_ld:
            registro["propriedades_extras"] = "; ".join(f"{k}={v}" for k, v in extras_ld.items())

    registro.setdefault("uf", "")
    registro.setdefault("propriedades_extras", "")
    registro.setdefault("imobiliaria_origem", "")
    registro.setdefault("ano_construcao", None)

    # Area nao privativa = area comum + area global das vagas. O portal so
    # publica essa decomposicao dentro do dropdown "Areas", que e renderizado
    # por clique e portanto nao existe no HTML salvo. A soma das duas, porem,
    # e a diferenca entre total e privativa - conferido no anuncio V62369:
    # 222,18 = 105,90 privativa + 83,28 comum + 33,00 vagas.
    # Calculada apos a sobreposicao do JSON-LD, que e quem define area_util_m2.
    # Resultado negativo significa anuncio incoerente (area total menor que a
    # privativa): 7 dos 300 do cache. Vira None em vez de propagar um numero
    # sem sentido para a modelagem.
    total, privativa = registro.get("area_total_m2"), registro.get("area_util_m2")
    diferenca = round(total - privativa, 2) if total is not None and privativa is not None else None
    registro["area_nao_privativa_m2"] = diferenca if diferenca is not None and diferenca >= 0 else None

    # ------------------------------------------------------------------
    # Dados que so existem no card da listagem (src/cards.py)
    # ------------------------------------------------------------------
    # O preco anterior riscado e a unica variacao de preco observavel numa
    # coleta unica: o portal nao publica historico, e a alternativa seria
    # repetir a coleta com semanas de intervalo.
    registro["preco_anterior"] = (card or {}).get("preco_anterior")
    registro["preco_card"] = (card or {}).get("preco_card")
    registro["badges"] = " | ".join((card or {}).get("badges") or [])
    registro["destaques_texto"] = " | ".join((card or {}).get("destaques_texto") or [])

    anterior, atual = registro["preco_anterior"], registro.get("preco")
    registro["teve_reducao_preco"] = int(bool(anterior and atual and atual < anterior))
    registro["variacao_preco_pct"] = (
        round((atual - anterior) / anterior * 100, 2) if anterior and atual else None
    )

    # marcador de qualidade: registro util exige preco e ao menos uma metrica fisica
    registro["registro_valido"] = int(
        registro.get("preco") is not None
        and any(registro.get(c) is not None for c in ("area_util_m2", "dormitorios"))
    )
    registro["alertas_qualidade"] = avaliar_qualidade(registro)
    return registro


# Ordem canonica das colunas do CSV de saida
COLUNAS = [
    "url", "slug", "codigo_imovel", "titulo",
    "preco", "preco_anterior", "variacao_preco_pct", "teve_reducao_preco",
    # area_util_m2 e a AREA PRIVATIVA (schema.org floorSize); area_nao_privativa
    # e a soma de area comum e area de vagas - ver DICIONARIO_DE_DADOS.
    "area_util_m2", "area_total_m2", "area_nao_privativa_m2",
    "dormitorios", "suites", "banheiros", "lavabos",
    "vagas_garagem", "elevadores", "andar", "ano_construcao", "comodos", "mobilia",
    "posicao", "posicao_solar", "previsao_entrega",
    "condominio", "iptu", "disponibilidade", "data_publicacao",
    "bairro", "cidade", "uf", "endereco", "latitude", "longitude", "geo_origem",
    *config.AMENIDADES_MAP.keys(),
    "badges", "destaques_texto",
    "corretor", "creci", "imobiliaria_origem",
    "amenidades_texto", "propriedades_extras",
    "rotulo_preco", "preco_card", "alertas_qualidade",
    "jsonld_presente", "n_caracteres_html", "registro_valido",
]

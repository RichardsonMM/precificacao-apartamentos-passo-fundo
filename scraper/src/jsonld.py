"""
Extracao de dados estruturados schema.org (JSON-LD) das paginas de detalhe.

Achado da etapa de reconhecimento: cada pagina de imovel do portal publica um
bloco <script type="application/ld+json"> do tipo RealEstateListing contendo,
de forma estruturada e tipada:

    offers.price ................. preco de venda (numerico, BRL)
    about.floorSize.value ........ area privativa em m2
    about.geo.latitude/longitude . coordenadas geograficas
    about.numberOfBedrooms ....... dormitorios
    about.numberOfParkingSpaces .. vagas de garagem
    about.address ................ cidade e UF
    about.amenityFeature[] ....... caracteristicas do imovel
    about.additionalProperty[] ... pares nome/valor adicionais (ex.: Mobilia)

Essa fonte e preferivel a seletores CSS porque e tipada, estavel entre layouts
e independente das classes utilitarias (Tailwind) usadas no portal, que mudam a
cada build. Campos ausentes no JSON-LD (bairro, suites, banheiros, andar,
condominio, IPTU) sao complementados pelo parsing do DOM em parsers.py.
"""

from __future__ import annotations

import json

import config
import logging
from urllib.parse import urlparse

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_LAT_MIN, _LAT_MAX = -34.0, -22.0
_LON_MIN, _LON_MAX = -58.0, -48.0


def _blocos(soup: BeautifulSoup) -> list[dict]:
    """Todos os objetos JSON-LD da pagina, achatando listas e @graph."""
    encontrados: list[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        pilha = dados if isinstance(dados, list) else [dados]
        while pilha:
            item = pilha.pop()
            if not isinstance(item, dict):
                continue
            encontrados.append(item)
            grafo = item.get("@graph")
            if isinstance(grafo, list):
                pilha.extend(grafo)
    return encontrados


def encontrar_listing(soup: BeautifulSoup) -> dict | None:
    """Retorna o bloco RealEstateListing (ou equivalente), se existir."""
    tipos_aceitos = {"RealEstateListing", "Residence", "Apartment", "SingleFamilyResidence", "Product"}
    for bloco in _blocos(soup):
        tipo = bloco.get("@type")
        tipos = {tipo} if isinstance(tipo, str) else set(tipo or [])
        if tipos & tipos_aceitos:
            return bloco
    return None


def _num(valor) -> float | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _int(valor) -> int | None:
    n = _num(valor)
    return int(n) if n is not None else None


def extrair(soup: BeautifulSoup) -> dict:
    """
    Retorna um dicionario com os campos disponiveis no JSON-LD.
    Chaves ausentes simplesmente nao aparecem, para nao sobrescrever valores
    obtidos por outras vias em parsers.py.
    """
    listing = encontrar_listing(soup)
    if not listing:
        return {}

    # O bloco de imovel pode estar em 'about' ou ser o proprio listing
    about = listing.get("about")
    if not isinstance(about, dict):
        about = listing

    out: dict = {"jsonld_presente": 1}

    # --- preco ---
    offers = listing.get("offers") or about.get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    if isinstance(offers, dict):
        preco = _num(offers.get("price") or (offers.get("priceSpecification") or {}).get("price"))
        if preco:
            out["preco"] = preco
        if offers.get("availability"):
            out["disponibilidade"] = str(offers["availability"]).rsplit("/", 1)[-1]

    # --- area ---
    floor = about.get("floorSize")
    if isinstance(floor, dict):
        area = _num(floor.get("value"))
        if area:
            out["area_util_m2"] = area
    elif floor is not None:
        area = _num(floor)
        if area:
            out["area_util_m2"] = area

    # --- contagens ---
    for chave_json, chave_saida in (
        ("numberOfBedrooms", "dormitorios"),
        ("numberOfParkingSpaces", "vagas_garagem"),
        ("numberOfBathroomsTotal", "banheiros"),
        ("numberOfRooms", "comodos"),
    ):
        v = _int(about.get(chave_json))
        if v is not None:
            out[chave_saida] = v

    # --- coordenadas ---
    geo = about.get("geo")
    if isinstance(geo, dict):
        lat, lon = _num(geo.get("latitude")), _num(geo.get("longitude"))
        if lat is not None and lon is not None and _LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX:
            out["latitude"], out["longitude"] = lat, lon
            out["geo_origem"] = "json_ld"

    # --- endereco ---
    end = about.get("address")
    if isinstance(end, dict):
        if end.get("addressLocality"):
            out["cidade"] = str(end["addressLocality"]).strip()
        if end.get("addressRegion"):
            out["uf"] = str(end["addressRegion"]).strip()
        # alguns portais usam addressSubLocality ou streetAddress para o bairro
        bairro = end.get("addressSubLocality") or end.get("neighborhood")
        if bairro:
            out["bairro"] = str(bairro).strip()
        if end.get("streetAddress"):
            out["endereco"] = str(end["streetAddress"]).strip()

    # --- caracteristicas ---
    amenidades = []
    for item in about.get("amenityFeature") or []:
        if isinstance(item, dict) and item.get("value") is not False and item.get("name"):
            amenidades.append(str(item["name"]).strip())
    if amenidades:
        out["amenidades_jsonld"] = amenidades

    extras = {}
    for item in about.get("additionalProperty") or []:
        if isinstance(item, dict) and item.get("name"):
            extras[str(item["name"]).strip()] = str(item.get("value", "")).strip()
    if extras:
        out["propriedades_extras"] = extras
        for rotulo, destino in (("mobilia", "mobilia"), ("suíte", "suites"), ("suite", "suites")):
            for nome, valor in extras.items():
                if rotulo in nome.lower():
                    out[destino] = valor if destino == "mobilia" else _int(valor)

    # --- ano de construcao ---
    # Unica fonte do campo no portal: a ficha tecnica em HTML nao o publica, e
    # por isso ele saia vazio em 100% dos registros ate 16/08/2026. Presente em
    # cerca de 1 a cada 5 anuncios (13 de 60 conferidos no cache).
    ano = _int(about.get("yearBuilt"))
    if ano:
        out["ano_construcao"] = ano

    # --- metadados ---
    if listing.get("name"):
        out["titulo"] = str(listing["name"]).strip()
    if listing.get("datePosted"):
        out["data_publicacao"] = str(listing["datePosted"])

    # --- imobiliaria dona do anuncio ---
    # O portal reune varias imobiliarias: o campo `url` do JSON-LD aponta para o site da
    # imobiliaria que cadastrou o imovel, e nao para o portal. Serve como efeito
    # fixo na modelagem - cada imobiliaria tem sua propria politica de preco e de
    # preenchimento do cadastro. Presente em 60 de 60 anuncios conferidos.
    if listing.get("url"):
        host = urlparse(str(listing["url"])).netloc.lower()
        portal = urlparse(config.BASE_URL).netloc.lower().removeprefix("www.")
        if host and not (portal and portal in host):
            out["imobiliaria_origem"] = host

    return out

"""
Extracao de coordenadas geograficas (latitude/longitude) da pagina de detalhe.

Conforme a metodologia da proposta, as coordenadas sao obtidas diretamente do
mapa embedado do Google Maps presente na pagina, dispensando servicos externos
de geocodificacao.

Sao testados varios padroes, em ordem de confiabilidade, porque portais
imobiliarios embedam mapas de formas diferentes.
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Faixa plausivel para o sul do Brasil - filtro grosseiro contra falsos positivos
_LAT_MIN, _LAT_MAX = -34.0, -22.0
_LON_MIN, _LON_MAX = -58.0, -48.0

_NUM = r"(-?\d{1,3}\.\d{3,})"

_PADROES = [
    # 1) URL de embed do Google Maps: ...!3d-28.2628!4d-52.4066
    (re.compile(rf"!3d{_NUM}!4d{_NUM}"), "embed_pb"),
    # 2) Parametro q= / query= : ?q=-28.2628,-52.4066
    (re.compile(rf"[?&](?:q|query|center|ll)={_NUM}\s*,\s*{_NUM}"), "query_param"),
    # 3) Formato de link do Maps: /@-28.2628,-52.4066,15z
    (re.compile(rf"@{_NUM},{_NUM}"), "at_marker"),
    # 4) Chaves JSON: "lat":-28.2628 ... "lng":-52.4066
    (re.compile(rf'"lat(?:itude)?"\s*:\s*"?{_NUM}"?.{{0,120}}?"l(?:ng|on|ongitude)"\s*:\s*"?{_NUM}"?', re.S), "json_keys"),
    # 5) Variaveis JS: var lat = -28.2628; var lng = -52.4066;
    (re.compile(rf"lat(?:itude)?\s*[:=]\s*{_NUM}.{{0,120}}?l(?:ng|on|ongitude)\s*[:=]\s*{_NUM}", re.S | re.I), "js_vars"),
]


def _plausivel(lat: float, lon: float) -> bool:
    return _LAT_MIN <= lat <= _LAT_MAX and _LON_MIN <= lon <= _LON_MAX


def _de_texto(texto: str) -> tuple[float, float, str] | None:
    for padrao, origem in _PADROES:
        for m in padrao.finditer(texto):
            try:
                lat, lon = float(m.group(1)), float(m.group(2))
            except (TypeError, ValueError):
                continue
            if _plausivel(lat, lon):
                return lat, lon, origem
            # alguns portais invertem a ordem
            if _plausivel(lon, lat):
                return lon, lat, f"{origem}_invertido"
    return None


def extrair_coordenadas(soup: BeautifulSoup, html: str) -> dict:
    """
    Retorna {'latitude': float|None, 'longitude': float|None, 'geo_origem': str}.

    Ordem de busca:
      1. Atributos data-lat / data-lng em qualquer elemento
      2. src de <iframe> de mapa
      3. href de links para o Google Maps
      4. conteudo de <script> (JSON/JS embutido)
      5. varredura do HTML completo (ultimo recurso)
    """
    vazio = {"latitude": None, "longitude": None, "geo_origem": "nao_encontrado"}

    # 1) atributos data-*
    for el in soup.find_all(attrs={"data-lat": True}):
        lat_raw = el.get("data-lat")
        lon_raw = el.get("data-lng") or el.get("data-lon") or el.get("data-long")
        try:
            lat, lon = float(lat_raw), float(lon_raw)
        except (TypeError, ValueError):
            continue
        if _plausivel(lat, lon):
            return {"latitude": lat, "longitude": lon, "geo_origem": "data_attr"}

    # 2) iframes de mapa
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if "map" in src.lower() or "google" in src.lower():
            achado = _de_texto(src)
            if achado:
                lat, lon, origem = achado
                return {"latitude": lat, "longitude": lon, "geo_origem": f"iframe:{origem}"}

    # 3) links para o Google Maps
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "google" in href.lower() and "map" in href.lower():
            achado = _de_texto(href)
            if achado:
                lat, lon, origem = achado
                return {"latitude": lat, "longitude": lon, "geo_origem": f"link:{origem}"}

    # 4) scripts embutidos
    for script in soup.find_all("script"):
        conteudo = script.string or script.get_text() or ""
        if not conteudo or "lat" not in conteudo.lower():
            continue
        achado = _de_texto(conteudo)
        if achado:
            lat, lon, origem = achado
            return {"latitude": lat, "longitude": lon, "geo_origem": f"script:{origem}"}

    # 5) varredura geral
    achado = _de_texto(html)
    if achado:
        lat, lon, origem = achado
        return {"latitude": lat, "longitude": lon, "geo_origem": f"html:{origem}"}

    return vazio


def extrair_de_jsonld(soup: BeautifulSoup) -> dict | None:
    """
    Muitos portais publicam schema.org/Place com GeoCoordinates em
    <script type="application/ld+json">. Quando presente, e a fonte mais confiavel.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            dados = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for bloco in dados if isinstance(dados, list) else [dados]:
            if not isinstance(bloco, dict):
                continue
            geo = bloco.get("geo") or (bloco.get("address") or {}).get("geo")
            if isinstance(geo, dict):
                try:
                    lat = float(geo.get("latitude"))
                    lon = float(geo.get("longitude"))
                except (TypeError, ValueError):
                    continue
                if _plausivel(lat, lon):
                    return {"latitude": lat, "longitude": lon, "geo_origem": "json_ld"}
    return None

"""
Leitura dos cards da pagina de listagem.

Motivacao: preco anterior e selos promocionais ("Baixou valor!", "Novidade",
"Em Construcao") existem SOMENTE no card da listagem - a pagina de detalhe do
imovel nao os exibe. Sem esta etapa, a unica variacao de preco observavel seria
a diferenca entre coletas separadas por semanas.

O portal usa classes utilitarias (Tailwind) que mudam a cada build, mas os
cards carregam classes semanticas estaveis, que sao as usadas aqui:

    div.hoverCard1        ..... o card inteiro
    span.cardsValor       ..... preco vigente (presente em 40/40 dos cards)
    span.cardsValorDe     ..... preco anterior, riscado (4/40 na pagina 1)
    span.cardItemDestaques .... cada selo promocional
    span.letraImovelCodigo .... a letra da operacao (V/L) que precede o codigo

Ler `cardsValorDe` por CLASSE, e nao pelo estilo riscado computado, permite
extrair os cards do HTML ja em cache, sem navegador - o mesmo HTML serve para
reprocessamento futuro.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

import config
from src.normalize import extrair_valor_monetario, limpar_texto, sem_acento

logger = logging.getLogger(__name__)

# /imovel/{slug}/{id} -> o id numerico e a chave de ligacao com a pagina de detalhe
_PADRAO_ID = re.compile(r"/imovel/[^/]+/(\d+)")


def _id_do_href(href: str) -> str:
    m = _PADRAO_ID.search(urlparse(href).path)
    return m.group(1) if m else ""


def _classificar_destaques(textos: list[str]) -> tuple[list[str], list[str]]:
    """
    Separa os selos padronizados das chamadas livres do corretor.

    Devolve (selos canonicos, textos livres). Ver config.BADGES_CANONICOS para
    a motivacao. A comparacao e feita sem acento e em minusculas porque o mesmo
    selo aparece em grafias diferentes conforme a imobiliaria que cadastrou
    ("Mobiliado", "MOBILIADO", "MOBILIADA").
    """
    selos: list[str] = []
    livres: list[str] = []
    for texto in textos:
        chave = sem_acento(texto).lower().strip()
        canonico = config.BADGES_CANONICOS.get(chave)
        if canonico:
            if canonico not in selos:
                selos.append(canonico)
        elif texto not in livres:
            livres.append(texto)
    return selos, livres


def extrair_cards(html: str) -> dict[str, dict]:
    """
    Devolve {id_do_imovel: {preco_card, preco_anterior, badges, href}}.

    A chave e o id numerico da URL, o mesmo que parsers.parse_detalhe usa como
    `slug`, o que permite casar card e ficha sem depender do codigo exibido.
    """
    soup = BeautifulSoup(html, "html.parser")
    sel = config.SELECTORS_CARD
    achados: dict[str, dict] = {}

    cards = soup.select(sel["card"])
    if not cards:
        logger.warning("nenhum card encontrado - conferir SELECTORS_CARD['card']")
        return achados

    for card in cards:
        link = card.select_one(sel["link_detalhe"])
        if not link or not link.get("href"):
            continue
        id_imovel = _id_do_href(link["href"])
        if not id_imovel or id_imovel in achados:
            continue

        vigente = card.select_one(sel["preco"])
        anterior = card.select_one(sel["preco_anterior"])
        destaques = [limpar_texto(s.get_text(" ")) for s in card.select(sel["badge"])]
        selos, livres = _classificar_destaques([d for d in destaques if d])
        letra = card.select_one(sel["letra_codigo"])

        achados[id_imovel] = {
            "href": link["href"],
            "codigo_card": f"{limpar_texto(letra.get_text()) if letra else ''}{id_imovel}",
            "preco_card": extrair_valor_monetario(vigente.get_text(" ")) if vigente else None,
            "preco_anterior": extrair_valor_monetario(anterior.get_text(" ")) if anterior else None,
            "badges": selos,
            "destaques_texto": livres,
        }

    return achados

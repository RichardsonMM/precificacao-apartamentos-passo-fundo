"""
Persistencia incremental dos registros coletados.

O JSONL funciona como checkpoint: cada anuncio e gravado assim que extraido,
permitindo interromper e retomar a coleta sem perda e sem refazer requisicoes.
O CSV final e gerado a partir do JSONL consolidado.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def urls_ja_coletadas(caminho: Path = config.RAW_RECORDS_JSONL) -> set[str]:
    """URLs presentes no checkpoint, para pular na retomada."""
    if not caminho.exists():
        return set()
    urls = set()
    with caminho.open("r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            try:
                urls.add(json.loads(linha)["url"])
            except (json.JSONDecodeError, KeyError):
                continue
    return urls


def anexar_registro(registro: dict, caminho: Path = config.RAW_RECORDS_JSONL) -> None:
    with caminho.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def carregar_registros(caminho: Path = config.RAW_RECORDS_JSONL) -> list[dict]:
    if not caminho.exists():
        return []
    registros = []
    with caminho.open("r", encoding="utf-8") as f:
        for n, linha in enumerate(f, 1):
            linha = linha.strip()
            if not linha:
                continue
            try:
                registros.append(json.loads(linha))
            except json.JSONDecodeError:
                logger.warning("linha %d invalida no checkpoint, ignorada", n)
    return registros


def exportar_csv(
    registros: list[dict],
    colunas: list[str],
    caminho: Path = config.DATASET_CSV,
) -> Path:
    """Grava o CSV na ordem canonica de colunas, com UTF-8 BOM (compat. Excel)."""
    with caminho.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=colunas, extrasaction="ignore")
        writer.writeheader()
        for r in registros:
            writer.writerow({c: r.get(c) for c in colunas})
    logger.info("CSV gravado: %s (%d linhas)", caminho, len(registros))
    return caminho


def salvar_cards(cards: dict[str, dict], caminho: Path = config.CARDS_FILE) -> None:
    """
    Grava os dados de card indexados por id do imovel.

    Sao regravados por inteiro a cada varredura da listagem: preco anterior e
    selos mudam com o tempo, e a versao mais recente e a que vale. O historico
    fica no HTML bruto em cache, que nao e sobrescrito.
    """
    caminho.write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")


def carregar_cards(caminho: Path = config.CARDS_FILE) -> dict[str, dict]:
    if not caminho.exists():
        return {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("arquivo de cards ilegivel, ignorado: %s", caminho)
        return {}


def salvar_urls(urls: list[str], caminho: Path = config.URLS_FILE) -> None:
    caminho.write_text("\n".join(urls), encoding="utf-8")


def carregar_urls(caminho: Path = config.URLS_FILE) -> list[str]:
    if not caminho.exists():
        return []
    return [u.strip() for u in caminho.read_text(encoding="utf-8").splitlines() if u.strip()]

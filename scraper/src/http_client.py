"""
Cliente HTTP com sessao persistente, retry exponencial e rate limiting.

Mantem a coleta responsavel: pausa entre requisicoes, respeito a codigos 429/5xx
e cache local do HTML bruto para evitar refazer requisicoes ja realizadas.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)


class HttpClient:
    """Wrapper de requests.Session com politica de coleta responsavel."""

    def __init__(self, use_cache: bool = True):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
            }
        )
        self.use_cache = use_cache
        self._last_request_at = 0.0
        self.n_requests = 0
        self.n_cache_hits = 0

    # ------------------------------------------------------------------
    # Cache em disco
    # ------------------------------------------------------------------
    @staticmethod
    def _cache_path(url: str) -> Path:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        return config.RAW_HTML_DIR / f"{digest}.html"

    def _read_cache(self, url: str) -> str | None:
        path = self._cache_path(url)
        if self.use_cache and path.exists() and path.stat().st_size > 0:
            return path.read_text(encoding="utf-8", errors="replace")
        return None

    def _write_cache(self, url: str, html: str) -> None:
        self._cache_path(url).write_text(html, encoding="utf-8", errors="replace")

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    def _wait(self) -> None:
        delay = config.DELAY_BETWEEN_REQUESTS + random.uniform(0, config.DELAY_JITTER)
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < delay:
            time.sleep(delay - elapsed)

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    def get_html(self, url: str) -> str | None:
        """Retorna o HTML da URL, ou None em caso de falha definitiva."""
        cached = self._read_cache(url)
        if cached is not None:
            self.n_cache_hits += 1
            logger.debug("cache hit: %s", url)
            return cached

        for attempt in range(1, config.MAX_RETRIES + 1):
            self._wait()
            try:
                resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
                self._last_request_at = time.monotonic()
                self.n_requests += 1

                if resp.status_code == 200:
                    resp.encoding = resp.apparent_encoding or "utf-8"
                    html = resp.text
                    self._write_cache(url, html)
                    return html

                if resp.status_code == 404:
                    logger.warning("404 (nao existe, sem retry): %s", url)
                    return None

                if resp.status_code in (429, 500, 502, 503, 504):
                    espera = config.BACKOFF_FACTOR**attempt
                    logger.warning(
                        "HTTP %s em %s - tentativa %d/%d, aguardando %.0fs",
                        resp.status_code, url, attempt, config.MAX_RETRIES, espera,
                    )
                    time.sleep(espera)
                    continue

                logger.warning("HTTP %s inesperado em %s", resp.status_code, url)
                return None

            except requests.RequestException as exc:
                espera = config.BACKOFF_FACTOR**attempt
                logger.warning(
                    "Erro de rede em %s (%s) - tentativa %d/%d, aguardando %.0fs",
                    url, exc.__class__.__name__, attempt, config.MAX_RETRIES, espera,
                )
                time.sleep(espera)

        logger.error("Falha definitiva apos %d tentativas: %s", config.MAX_RETRIES, url)
        return None

    def stats(self) -> dict:
        return {"requisicoes": self.n_requests, "cache_hits": self.n_cache_hits}

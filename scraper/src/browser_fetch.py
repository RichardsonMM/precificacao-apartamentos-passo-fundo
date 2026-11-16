"""
Obtencao de HTML com navegador headless (Playwright).

Motivacao (achado da etapa de reconhecimento): o portal e uma aplicacao de
pagina unica em Nuxt/Vue com renderizacao no cliente e protecao Cloudflare. As
paginas de listagem chegam ao navegador como esqueletos (placeholders
'skeleton-shimmer') e so recebem conteudo apos a execucao do JavaScript, o que
torna a dupla requests + BeautifulSoup insuficiente para essa etapa.

A estrategia adotada e hibrida e economica:
  1. Tenta a requisicao simples com requests (barata e rapida).
  2. Se o HTML retornado nao contiver o marcador de conteudo esperado, refaz a
     obtencao com o navegador headless.

Assim o navegador so e acionado quando realmente necessario.

A hipotese de que as paginas de detalhe seriam renderizadas no servidor foi
DESCARTADA pelo diagnostico de 16/08/2026: a requisicao simples devolve o mesmo
shell da SPA para qualquer rota (~10,8 mil caracteres), sem o bloco do anuncio.
O navegador e, portanto, obrigatorio tambem no detalhe.

Instalacao:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import logging
import random
import time

import config

logger = logging.getLogger(__name__)

# Marcadores usados para decidir se o HTML "chegou pronto".
#
# O marcador do detalhe NAO pode ser 'application/ld+json': o shell da SPA ja
# traz dois blocos JSON-LD institucionais (Organization/WebSite) em toda rota,
# o que fazia o HTML vazio ser aprovado como completo e o navegador nunca ser
# acionado. O sinal decisivo e o @type do anuncio em si.
MARCADOR_CONTEUDO_DETALHE = 'RealEstateListing'
MARCADOR_CONTEUDO_LISTAGEM = '/imovel/'
MARCADOR_ESQUELETO = 'skeleton-shimmer'


def html_esta_completo(html: str | None, tipo: str = "detalhe") -> bool:
    """Heuristica: o HTML ja contem os dados, ou e so o esqueleto da SPA?"""
    if not html or len(html) < 5_000:
        return False
    if tipo == "detalhe":
        return MARCADOR_CONTEUDO_DETALHE in html and MARCADOR_ESQUELETO not in html
    return html.count(MARCADOR_CONTEUDO_LISTAGEM) >= 5


class BrowserFetcher:
    """Contexto de navegador reutilizado entre requisicoes."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "BrowserFetcher":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright nao instalado. Execute:\n"
                "    pip install playwright\n"
                "    playwright install chromium"
            ) from exc

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            user_agent=config.USER_AGENT,
            locale="pt-BR",
            viewport={"width": 1366, "height": 900},
        )
        # Bloqueia recursos irrelevantes: reduz banda e acelera a coleta
        self._context.route(
            "**/*.{png,jpg,jpeg,webp,gif,svg,woff,woff2,ttf,mp4}",
            lambda rota: rota.abort(),
        )
        return self

    def __exit__(self, *_exc) -> None:
        for recurso in (self._context, self._browser):
            try:
                recurso and recurso.close()
            except Exception:
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------
    def get_html(self, url: str, esperar_por: str | None = None, timeout_ms: int = 30_000) -> str | None:
        """Carrega a URL, aguarda a renderizacao e devolve o HTML final."""
        if self._context is None:
            raise RuntimeError("Use o BrowserFetcher como gerenciador de contexto (with ...)")

        pagina = self._context.new_page()
        try:
            pagina.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            if esperar_por:
                try:
                    # state="attached": o seletor do detalhe aponta para uma tag
                    # <script>, que nunca fica "visible" (padrao do Playwright) e
                    # estouraria o timeout em toda pagina de anuncio.
                    pagina.wait_for_selector(esperar_por, state="attached", timeout=timeout_ms)
                except Exception:
                    logger.debug("seletor de espera nao apareceu em %s: %s", url, esperar_por)

            # aguarda o fim das requisicoes de dados da SPA
            try:
                pagina.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass

            # rolagem: dispara carregamento preguicoso de cards
            pagina.mouse.wheel(0, 4000)
            pagina.wait_for_timeout(1200)

            html = pagina.content()

            # pausa entre navegacoes, mesma politica do cliente HTTP
            time.sleep(config.DELAY_BETWEEN_REQUESTS + random.uniform(0, config.DELAY_JITTER))
            return html

        except Exception as exc:
            logger.warning("Falha ao carregar %s no navegador: %s", url, exc)
            return None
        finally:
            pagina.close()

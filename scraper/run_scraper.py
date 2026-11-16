#!/usr/bin/env python3
"""
Coleta de anuncios de apartamentos a venda em Passo Fundo/RS.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Etapa 1 do pipeline: coleta de dados.

Uso:
    python run_scraper.py --fase urls          # so descobre as URLs de detalhe
    python run_scraper.py --fase detalhes      # so extrai os anuncios ja indexados
    python run_scraper.py --fase completa      # as duas etapas em sequencia
    python run_scraper.py --fase completa --limite 300  # amostra sorteada (semente fixa)
    python run_scraper.py --fase exportar      # regera o CSV a partir do checkpoint

Retomada: registros ja coletados sao pulados automaticamente; o HTML fica em
cache no disco, entao reexecutar nao gera novas requisicoes ao portal.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import datetime

import config
from src import browser_fetch, cards, parsers, storage
from src.http_client import HttpClient


def url_listagem(pagina: int) -> str:
    if not config.BASE_URL:
        raise SystemExit("Defina a variavel de ambiente PORTAL_URL com o endereco do portal.")
    return config.LISTING_URL_TEMPLATE.format(page=pagina, pagina_param=config.PAGINACAO_PARAM)


class Coletor:
    """
    Obtencao de HTML em duas camadas: requests primeiro, navegador headless
    apenas quando o HTML retornado vier incompleto (esqueleto da SPA).
    """

    def __init__(self, http: HttpClient, usar_navegador: bool = config.USAR_NAVEGADOR):
        self.http = http
        self.usar_navegador = usar_navegador
        self._browser = None
        self.n_via_navegador = 0

    def __enter__(self) -> "Coletor":
        if self.usar_navegador:
            try:
                self._browser = browser_fetch.BrowserFetcher(config.NAVEGADOR_HEADLESS).__enter__()
            except RuntimeError as exc:
                logging.getLogger("coleta").error("%s", exc)
                logging.getLogger("coleta").warning("Prosseguindo somente com requests.")
                self.usar_navegador = False
        return self

    def __exit__(self, *exc) -> None:
        if self._browser:
            self._browser.__exit__(*exc)

    def get_html(self, url: str, tipo: str = "detalhe") -> str | None:
        """
        Ordem de obtencao: cache de disco, depois navegador.

        O diagnostico de 16/08/2026 mostrou que tanto a listagem quanto o
        detalhe exigem JavaScript - a requisicao simples devolve o mesmo shell
        da SPA (~10,8 mil caracteres) para qualquer rota. Tentar requests antes
        do navegador seria uma requisicao inutil por pagina (~1.371 na coleta
        completa) alem do delay da politica de coleta, entao o navegador e
        acionado direto. O requests permanece como unico recurso quando o
        navegador nao esta disponivel (--sem-navegador ou falha do Playwright).
        """
        log_ = logging.getLogger("coleta")

        # O cache tem precedencia: reexecutar a coleta nao repete requisicao ao
        # portal. HTML antigo que nao passe na verificacao e reobtido.
        cache = self.http._read_cache(url)
        if cache is not None:
            if browser_fetch.html_esta_completo(cache, tipo):
                self.http.n_cache_hits += 1
                return cache
            log_.debug("cache incompleto, descartado: %s", url)

        if not self._browser:
            return self.http.get_html(url)  # sem navegador: resta tentar requests

        seletor = 'a[href*="/imovel/"]' if tipo == "listagem" else 'script[type="application/ld+json"]'
        html_nav = self._browser.get_html(url, esperar_por=seletor)
        if html_nav:
            self.n_via_navegador += 1
            self.http._write_cache(url, html_nav)  # o cache guarda a versao renderizada
            return html_nav
        return None


def configurar_log(verboso: bool = False) -> None:
    arquivo = config.LOG_DIR / f"coleta_{datetime.now():%Y%m%d_%H%M%S}.log"
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.FileHandler(arquivo, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.info("Log desta execucao: %s", arquivo)


log = logging.getLogger("coleta")


# ---------------------------------------------------------------------------
# Fase 1 - descoberta das URLs de detalhe
# ---------------------------------------------------------------------------
def coletar_urls(coletor: Coletor, max_paginas: int = config.MAX_PAGES) -> list[str]:
    todas: list[str] = []
    vistas: set[str] = set()
    # Preco anterior e selos so existem no card da listagem: sao lidos aqui,
    # enquanto a pagina esta na mao, e guardados para a fase de detalhes.
    todos_cards: dict[str, dict] = {}
    paginas_vazias = 0

    for pagina in range(1, max_paginas + 1):
        url = url_listagem(pagina)
        log.info("Listagem - pagina %d", pagina)

        html = coletor.get_html(url, tipo="listagem")
        if html is None:
            log.warning("Pagina %d inacessivel, encerrando a varredura", pagina)
            break

        links = parsers.extrair_links_listagem(html)
        novos = [u for u in links if u not in vistas]
        vistas.update(novos)
        todas.extend(novos)

        da_pagina = cards.extrair_cards(html)
        todos_cards.update(da_pagina)
        com_preco_anterior = sum(1 for c in da_pagina.values() if c.get("preco_anterior"))

        log.info(
            "  %d links na pagina | %d novos | %d no total | %d cards (%d com preco anterior)",
            len(links), len(novos), len(todas), len(da_pagina), com_preco_anterior,
        )

        if not novos:
            paginas_vazias += 1
            # duas paginas seguidas sem nada novo = fim dos resultados
            if paginas_vazias >= 2:
                log.info("Sem resultados novos, fim da paginacao na pagina %d", pagina)
                break
        else:
            paginas_vazias = 0

    storage.salvar_urls(todas)
    storage.salvar_cards(todos_cards)
    log.info(
        "Fase de URLs concluida: %d anuncios indexados | %d cards lidos (%d com preco anterior)",
        len(todas), len(todos_cards),
        sum(1 for c in todos_cards.values() if c.get("preco_anterior")),
    )
    return todas


# ---------------------------------------------------------------------------
# Fase 2 - extracao dos anuncios
# ---------------------------------------------------------------------------
def selecionar_amostra(urls: list[str], limite: int, semente: int = config.SEMENTE) -> list[str]:
    """
    Sorteia 'limite' URLs entre todas as indexadas, com semente fixa.

    A listagem vem ordenada por preco decrescente, entao cortar as primeiras N
    daria uma amostra so do topo do mercado - inutil para avaliar a coleta e
    enviesada para a modelagem. O sorteio cobre toda a faixa de preco.

    O sorteio e feito sobre a lista COMPLETA e so depois as URLs ja coletadas
    sao descontadas (em coletar_detalhes). Fazer o contrario mudaria o conjunto
    alvo a cada retomada, e uma coleta interrompida deixaria de ser reproduzivel.
    """
    sorteadas = list(urls)
    random.Random(semente).shuffle(sorteadas)
    return sorteadas[:limite]


def coletar_detalhes(
    coletor: Coletor, urls: list[str], limite: int | None = None, semente: int = config.SEMENTE
) -> int:
    alvo = selecionar_amostra(urls, limite, semente) if limite else list(urls)
    if limite:
        log.info("Amostra de %d URLs sorteada entre %d indexadas (semente %d)", len(alvo), len(urls), semente)

    ja_feitas = storage.urls_ja_coletadas()
    pendentes = [u for u in alvo if u not in ja_feitas]

    # Indexados pelo id numerico da URL - a mesma chave que parsers usa em `slug`.
    cards_listagem = storage.carregar_cards()
    log.info(
        "Detalhes: %d pendentes (%d ja no checkpoint) | %d cards disponiveis",
        len(pendentes), len(ja_feitas), len(cards_listagem),
    )
    ok = falhas = sem_card = 0

    for i, url in enumerate(pendentes, 1):
        html = coletor.get_html(url, tipo="detalhe")
        if html is None:
            falhas += 1
            continue
        card = cards_listagem.get(url.rstrip("/").rsplit("/", 1)[-1])
        if card is None:
            sem_card += 1
        try:
            registro = parsers.parse_detalhe(html, url, card)
        except Exception as exc:
            log.exception("Erro ao parsear %s: %s", url, exc)
            falhas += 1
            continue

        storage.anexar_registro(registro)
        ok += 1
        if i % 25 == 0 or i == len(pendentes):
            log.info("  progresso %d/%d | validos ate aqui: %d | falhas: %d", i, len(pendentes), ok, falhas)

    log.info("Fase de detalhes concluida: %d coletados, %d falhas", ok, falhas)
    if sem_card:
        # Acontece quando a fase de detalhes roda sobre um indice de URLs mais
        # antigo que o arquivo de cards, ou quando o anuncio saiu da listagem
        # entre uma fase e outra. O registro e valido, so nao tera preco
        # anterior nem selos.
        log.warning("%d anuncios sem card correspondente (sem preco anterior/selos)", sem_card)
    return ok


# ---------------------------------------------------------------------------
# Fase 3 - exportacao
# ---------------------------------------------------------------------------
def _e_do_municipio_alvo(registro: dict) -> bool:
    """
    Filtro de escopo aplicado no pos-processamento: o portal atende toda a rede
    (inclusive o litoral catarinense) e o filtro de cidade da URL nao se mostrou
    confiavel na inspecao. A cidade/UF vem do JSON-LD de cada anuncio.
    """
    from src.normalize import sem_acento

    cidade = sem_acento(str(registro.get("cidade") or ""))
    uf = str(registro.get("uf") or "").strip().upper()
    if cidade:
        return config.CIDADE_ALVO in cidade
    return uf == config.UF_ALVO  # sem cidade: aceita pelo estado, revisar depois


def exportar(filtrar_municipio: bool = True) -> None:
    registros = storage.carregar_registros()
    if not registros:
        log.warning("Nenhum registro no checkpoint - nada a exportar")
        return

    total_bruto = len(registros)
    if filtrar_municipio:
        registros = [r for r in registros if _e_do_municipio_alvo(r)]
        log.info(
            "Filtro de municipio (%s): %d de %d registros mantidos",
            config.CIDADE_ALVO.title(), len(registros), total_bruto,
        )
    if not registros:
        log.warning("Nenhum registro do municipio alvo. Verifique os campos cidade/uf.")
        return

    storage.exportar_csv(registros, parsers.COLUNAS)
    n = len(registros)
    validos = sum(r.get("registro_valido", 0) for r in registros)
    com_geo = sum(1 for r in registros if r.get("latitude") is not None)
    com_ld = sum(r.get("jsonld_presente", 0) for r in registros)
    log.info(
        "Resumo | total: %d | validos: %d (%.1f%%) | com coordenadas: %d (%.1f%%) | com JSON-LD: %d (%.1f%%)",
        n, validos, 100 * validos / n, com_geo, 100 * com_geo / n, com_ld, 100 * com_ld / n,
    )


# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Coleta de anuncios de apartamentos - Passo Fundo/RS")
    ap.add_argument("--fase", choices=["urls", "detalhes", "completa", "exportar"], default="completa")
    ap.add_argument(
        "--limite",
        type=int,
        default=None,
        help="tamanho da amostra sorteada entre as URLs indexadas (execucao piloto)",
    )
    ap.add_argument(
        "--semente", type=int, default=config.SEMENTE, help=f"semente do sorteio (padrao {config.SEMENTE})"
    )
    ap.add_argument("--max-paginas", type=int, default=config.MAX_PAGES)
    ap.add_argument("--sem-cache", action="store_true", help="ignora o HTML em cache e refaz as requisicoes")
    ap.add_argument("--sem-navegador", action="store_true", help="usa apenas requests, sem Playwright")
    ap.add_argument("--sem-filtro-cidade", action="store_true", help="exporta todos os municipios coletados")
    ap.add_argument("-v", "--verboso", action="store_true")
    args = ap.parse_args()

    configurar_log(args.verboso)

    if args.fase == "exportar":
        exportar(filtrar_municipio=not args.sem_filtro_cidade)
        return

    client = HttpClient(use_cache=not args.sem_cache)
    with Coletor(client, usar_navegador=not args.sem_navegador) as coletor:
        urls: list[str] = []
        if args.fase in ("urls", "completa"):
            urls = coletar_urls(coletor, args.max_paginas)
        if args.fase in ("detalhes", "completa"):
            urls = urls or storage.carregar_urls()
            if not urls:
                log.error("Nenhuma URL indexada. Rode antes: python run_scraper.py --fase urls")
                return
            coletar_detalhes(coletor, urls, args.limite, args.semente)
            exportar(filtrar_municipio=not args.sem_filtro_cidade)

        log.info("Estatisticas HTTP: %s | paginas via navegador: %d", client.stats(), coletor.n_via_navegador)


if __name__ == "__main__":
    main()

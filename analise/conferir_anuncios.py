"""
Baixa novamente as paginas dos anuncios marcados para conferencia individual e
guarda o texto de cada uma como evidencia da revisao manual.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Usa o mesmo navegador headless e a mesma politica de pausas da coleta
(scraper/src/browser_fetch.py). E retomavel: paginas ja salvas sao puladas.

Uso:
    python analise/conferir_anuncios.py
Saida:
    dados/revisao/paginas/{id}.txt   texto do anuncio (sem cards relacionados e rodape)
    dados/revisao/paginas/indice.csv id, url, data da conferencia, status
"""

import re
import sys
from urllib.parse import urljoin
from datetime import date
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scraper"))
sys.path.insert(0, str(RAIZ / "analise"))

from gerar_planilha_revisao import ENTRADA, marcar, sugerir_bairros  # noqa: E402
from src.browser_fetch import BrowserFetcher  # noqa: E402
import config  # noqa: E402

DESTINO = RAIZ / "dados" / "revisao" / "paginas"
INDICE = DESTINO / "indice.csv"

# Suspeitas que so se resolvem abrindo o anuncio. As demais (preco "a partir
# de", condominio de preenchimento, grafia de bairro) sao decididas por regra.
SUSPEITAS_A_CONFERIR = [
    "falha_carga", "nao_apartamento", "sem_preco",
    "area_suspeita", "preco_m2_suspeito", "duplicata",
]

# O texto util do anuncio fica entre o breadcrumb e a vitrine de similares
INICIO_ANUNCIO = "Imóvel\n"
FIM_ANUNCIO = "Imóveis similares"


def texto_do_anuncio(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for sel in [".hoverCard1", '[id^="logos"]', "script", "style", "noscript"]:
        for tag in soup.select(sel):
            tag.decompose()
    texto = soup.get_text("\n")
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n", texto)
    ini = texto.find(INICIO_ANUNCIO)
    fim = texto.find(FIM_ANUNCIO)
    if ini >= 0 and fim > ini:
        texto = texto[ini + len(INICIO_ANUNCIO):fim]
    return texto.strip()


def main():
    if not config.BASE_URL:
        raise SystemExit("Defina a variavel de ambiente PORTAL_URL com o endereco do portal.")
    df = marcar(pd.read_csv(ENTRADA, encoding="utf-8-sig"),
                sugerir_bairros(pd.read_csv(ENTRADA, encoding="utf-8-sig")))
    alvo = df[df[["_" + s for s in SUSPEITAS_A_CONFERIR]].any(axis=1)]
    DESTINO.mkdir(parents=True, exist_ok=True)

    feitos = pd.read_csv(INDICE) if INDICE.exists() else pd.DataFrame(columns=["id"])
    pendentes = alvo[~alvo["id"].isin(feitos["id"])]
    print(f"{len(alvo)} anuncios a conferir, {len(pendentes)} pendentes")

    novos = []
    with BrowserFetcher() as navegador:
        for n, (_, reg) in enumerate(pendentes.iterrows(), 1):
            html = navegador.get_html(urljoin(config.BASE_URL + "/", reg["url"]), esperar_por='script[type="application/ld+json"]')
            if not html:
                status = "erro_carga"
            elif "RealEstateListing" not in html:
                status = "anuncio_indisponivel"
            else:
                status = "ok"
            if html:
                (DESTINO / f"{reg['id']}.txt").write_text(texto_do_anuncio(html), encoding="utf-8")
            novos.append({"id": reg["id"], "url": reg["url"],
                          "data_conferencia": date.today().isoformat(), "status": status})
            print(f"[{n}/{len(pendentes)}] id {reg['id']}: {status}", flush=True)
            if n % 10 == 0:   # checkpoint
                pd.concat([feitos, pd.DataFrame(novos)]).to_csv(INDICE, index=False)

    pd.concat([feitos, pd.DataFrame(novos)]).to_csv(INDICE, index=False)
    print("concluido")


if __name__ == "__main__":
    main()

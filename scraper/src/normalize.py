"""
Normalizacao de valores extraidos do HTML para tipos numericos e booleanos.

Isola toda a heuristica de limpeza textual em um unico modulo, o que facilita
o teste unitario e a documentacao das regras no capitulo de metodologia.
"""

from __future__ import annotations

import re
import unicodedata

import config


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------
def limpar_texto(valor: str | None) -> str:
    """Colapsa espacos, remove quebras de linha e nbsp."""
    if not valor:
        return ""
    valor = valor.replace("\xa0", " ")
    return re.sub(r"\s+", " ", valor).strip()


def sem_acento(valor: str | None) -> str:
    """Minusculas sem acentuacao, para comparacao robusta de rotulos."""
    texto = limpar_texto(valor).lower()
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# ---------------------------------------------------------------------------
# Numeros
# ---------------------------------------------------------------------------
_PADRAO_NUMERO = re.compile(r"\d[\d.,]*")


def _para_float_brasileiro(bruto: str) -> float | None:
    """Converte '1.250.000,50' -> 1250000.50 ; '85,5' -> 85.5 ; '120' -> 120.0"""
    bruto = bruto.strip()
    if not bruto:
        return None
    if "," in bruto:
        # virgula e o separador decimal; ponto e separador de milhar
        bruto = bruto.replace(".", "").replace(",", ".")
    else:
        # sem virgula: ponto pode ser milhar (1.250.000) ou decimal (85.5)
        partes = bruto.split(".")
        if len(partes) > 1 and all(len(p) == 3 for p in partes[1:]):
            bruto = "".join(partes)  # era separador de milhar
    try:
        return float(bruto)
    except ValueError:
        return None


# Piso de plausibilidade do preco de VENDA de um apartamento. Valores abaixo
# disso costumam ser aluguel, condominio ou erro de cadastro.
PRECO_VENDA_MINIMO = 10_000.0
PRECO_VENDA_MAXIMO = 50_000_000.0


def extrair_valor_monetario(valor: str | None) -> float | None:
    """
    'R$ 780,00' -> 780.0. Sem piso de plausibilidade: usar para condominio,
    IPTU e demais valores que legitimamente sao baixos.
    """
    texto = limpar_texto(valor)
    if not texto:
        return None
    if any(t in sem_acento(texto) for t in ("consulta", "combinar", "isento", "nao informado")):
        return None
    m = _PADRAO_NUMERO.search(texto)
    if not m:
        return None
    return _para_float_brasileiro(m.group())


def extrair_preco(valor: str | None) -> float | None:
    """
    'R$ 450.000,00' -> 450000.0.
    Retorna None para 'Sob consulta' e para valores fora da faixa plausivel
    de venda de apartamento.
    """
    preco = extrair_valor_monetario(valor)
    if preco is None or not (PRECO_VENDA_MINIMO <= preco <= PRECO_VENDA_MAXIMO):
        return None
    return preco


_PADRAO_REAIS = re.compile(r"R\$\s*([\d.,]+)")


def maior_valor_em_reais(texto: str | None) -> float | None:
    """
    Fallback para o preco de venda: varre todos os valores em R$ da pagina e
    retorna o maior dentro da faixa plausivel. Baseia-se em que o preco de
    venda e sempre superior a condominio, IPTU e demais valores do anuncio.
    """
    if not texto:
        return None
    candidatos = []
    for m in _PADRAO_REAIS.finditer(texto):
        v = _para_float_brasileiro(m.group(1))
        if v is not None and PRECO_VENDA_MINIMO <= v <= PRECO_VENDA_MAXIMO:
            candidatos.append(v)
    return max(candidatos) if candidatos else None


def extrair_area(valor: str | None) -> float | None:
    """'85,50 m2' -> 85.5"""
    texto = limpar_texto(valor)
    if not texto:
        return None
    m = _PADRAO_NUMERO.search(texto)
    if not m:
        return None
    area = _para_float_brasileiro(m.group())
    if area is None or area <= 0:
        return None
    return area


def extrair_inteiro(valor: str | None) -> int | None:
    """'3 dormitorios' -> 3 ; 'sem vaga' -> 0 ; '' -> None"""
    texto = sem_acento(valor)
    if not texto:
        return None
    if any(t in texto for t in ("sem ", "nao possui", "nenhum")):
        return 0
    m = re.search(r"\d+", texto)
    return int(m.group()) if m else None


def extrair_andar(valor: str | None) -> int | None:
    """'5o andar' -> 5 ; 'terreo' -> 0 ; 'cobertura' -> None (tratar a parte)"""
    texto = sem_acento(valor)
    if not texto:
        return None
    if "terreo" in texto:
        return 0
    m = re.search(r"\d+", texto)
    return int(m.group()) if m else None


# ---------------------------------------------------------------------------
# Amenidades
# ---------------------------------------------------------------------------
def mapear_amenidades(itens: list[str] | None, texto_extra: str = "") -> dict[str, int]:
    """
    Converte a lista de caracteristicas do anuncio em colunas booleanas (0/1),
    conforme config.AMENIDADES_MAP.
    """
    corpus = sem_acento(" | ".join(itens or []) + " | " + texto_extra)
    return {
        coluna: int(any(sem_acento(termo) in corpus for termo in termos))
        for coluna, termos in config.AMENIDADES_MAP.items()
    }


# ---------------------------------------------------------------------------
# Coordenadas
# ---------------------------------------------------------------------------
def coordenada_valida(lat: float | None, lon: float | None) -> bool:
    """Verifica se o par esta dentro do bounding box de Passo Fundo/RS."""
    if lat is None or lon is None:
        return False
    b = config.BBOX_PASSO_FUNDO
    return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]

"""
Engenharia de features: distancias aos pontos de interesse.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Para cada anuncio, calcula a distancia de Haversine ate cada um dos 10 pontos
de interesse (config.PONTOS_INTERESSE) e guarda a MENOR distancia por
categoria, resultando em tres features: shopping, hospital e ensino
(Secao 4.2.2 da proposta).

Uso:
    python analise/features.py
Entrada:
    dados/dataset_limpo.csv
Saida:
    dados/dataset_modelagem.csv
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scraper"))
import config  # noqa: E402

ENTRADA = RAIZ / "dados" / "dataset_limpo.csv"
SAIDA = RAIZ / "dados" / "dataset_modelagem.csv"

RAIO_TERRA_KM = 6371.0088   # raio medio (IUGG)


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia ao longo da superficie da Terra, considerada esferica."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 2 * RAIO_TERRA_KM * np.arcsin(np.sqrt(a))


def main():
    df = pd.read_csv(ENTRADA, encoding="utf-8-sig")
    for categoria, pontos in config.PONTOS_INTERESSE.items():
        distancias = np.column_stack([
            haversine_km(df["latitude"], df["longitude"], lat, lon) for lat, lon in pontos.values()
        ])
        df[f"dist_{categoria}_km"] = np.round(distancias.min(axis=1), 3)   # NaN onde nao ha coordenada

    df.to_csv(SAIDA, index=False, encoding="utf-8-sig")
    cols = [f"dist_{c}_km" for c in config.PONTOS_INTERESSE]
    print(f"{len(df)} registros -> {SAIDA.relative_to(RAIZ)}")
    print(df[cols].describe().round(2).to_string())
    print("\nCorrelação de Spearman com o preço:")
    print(df[cols + ["preco"]].corr(method="spearman")["preco"].drop("preco").round(3).to_string())


if __name__ == "__main__":
    main()

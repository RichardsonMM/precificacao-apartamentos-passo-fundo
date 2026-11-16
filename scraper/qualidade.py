#!/usr/bin/env python3
"""
Relatorio de qualidade da base bruta coletada.

Gera as estatisticas que sustentam a secao de coleta/pre-processamento do TCC:
cobertura por variavel, duplicatas, validade geografica e sanidade dos valores.

Uso:
    python qualidade.py
"""

from __future__ import annotations

import pandas as pd

import config
from src.normalize import coordenada_valida


def main() -> None:
    if not config.DATASET_CSV.exists():
        print(f"Arquivo nao encontrado: {config.DATASET_CSV}")
        print("Rode antes: python run_scraper.py --fase exportar")
        return

    df = pd.read_csv(config.DATASET_CSV)
    n = len(df)
    print("=" * 68)
    print(f"RELATORIO DE QUALIDADE DA BASE BRUTA  |  {n} registros")
    print("=" * 68)

    # ---- cobertura por variavel -------------------------------------------
    print("\n[1] COBERTURA POR VARIAVEL (% preenchido)")
    cobertura = (df.notna().mean() * 100).sort_values()
    for col, pct in cobertura.items():
        marca = "!!" if pct < 50 else ("! " if pct < 80 else "  ")
        print(f"  {marca} {col:<24} {pct:6.1f}%")

    # ---- duplicatas -------------------------------------------------------
    print("\n[2] DUPLICATAS")
    print(f"  URLs repetidas ................. {df['url'].duplicated().sum()}")
    if "codigo_imovel" in df:
        cods = df["codigo_imovel"].dropna()
        print(f"  Codigos de imovel repetidos .... {cods.duplicated().sum()}")
    chave = [c for c in ("preco", "area_util_m2", "dormitorios", "bairro") if c in df]
    print(f"  Anuncios identicos por {'+'.join(chave)}: {df.duplicated(subset=chave).sum()}")

    # ---- geolocalizacao ---------------------------------------------------
    print("\n[3] GEOLOCALIZACAO")
    com_coord = df[["latitude", "longitude"]].notna().all(axis=1)
    print(f"  Com coordenadas ................ {com_coord.sum()} ({100*com_coord.mean():.1f}%)")
    dentro = df[com_coord].apply(lambda r: coordenada_valida(r["latitude"], r["longitude"]), axis=1)
    fora = int((~dentro).sum()) if len(dentro) else 0
    print(f"  Dentro do bbox de Passo Fundo .. {int(dentro.sum()) if len(dentro) else 0}")
    print(f"  Fora do bbox (revisar) ......... {fora}")
    if "geo_origem" in df:
        print("  Origem da coordenada:")
        for origem, qtd in df["geo_origem"].value_counts().items():
            print(f"     {origem:<28} {qtd}")

    # ---- sanidade numerica ------------------------------------------------
    print("\n[4] DISTRIBUICAO DAS VARIAVEIS NUMERICAS")
    numericas = [c for c in ("preco", "area_util_m2", "dormitorios", "suites",
                             "banheiros", "vagas_garagem", "andar", "condominio")
                 if c in df]
    desc = df[numericas].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95]).T
    print(desc.to_string(float_format=lambda v: f"{v:,.1f}"))

    if "preco" in df and "area_util_m2" in df:
        valido = df["preco"].notna() & df["area_util_m2"].gt(0)
        if valido.any():
            m2 = (df.loc[valido, "preco"] / df.loc[valido, "area_util_m2"])
            print(f"\n  Preco por m2 - mediana: R$ {m2.median():,.0f} | "
                  f"P05: R$ {m2.quantile(0.05):,.0f} | P95: R$ {m2.quantile(0.95):,.0f}")
            suspeitos = int(((m2 < 1_000) | (m2 > 25_000)).sum())
            print(f"  Registros com preco/m2 implausivel: {suspeitos}")

    # ---- bairros ----------------------------------------------------------
    if "bairro" in df:
        print("\n[5] BAIRROS")
        vc = df["bairro"].fillna("(vazio)").value_counts()
        print(f"  Bairros distintos: {df['bairro'].nunique()}")
        for b, q in vc.head(15).items():
            print(f"     {str(b)[:32]:<34} {q}")

    # ---- amenidades -------------------------------------------------------
    amen = [c for c in df.columns if c.startswith("amen_")]
    if amen:
        print("\n[6] AMENIDADES (% dos anuncios)")
        for c in amen:
            print(f"     {c:<26} {100*df[c].fillna(0).mean():5.1f}%")

    # ---- veredito ---------------------------------------------------------
    print("\n" + "=" * 68)
    if "registro_valido" in df:
        v = int(df["registro_valido"].sum())
        print(f"REGISTROS APROVEITAVEIS PARA MODELAGEM: {v} de {n} ({100*v/n:.1f}%)")
    print("=" * 68)


if __name__ == "__main__":
    main()

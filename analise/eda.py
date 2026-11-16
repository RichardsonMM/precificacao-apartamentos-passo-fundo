"""
Analise exploratoria da base de modelagem.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Gera as figuras (PDF para o artigo, PNG para apresentacoes) e as tabelas em
LaTeX usadas na secao de resultados do pre-processamento e da EDA.

Uso:
    python analise/eda.py
Entrada:
    dados/dataset_modelagem.csv, dados/funil_preprocessamento.csv
Saidas:
    saidas/figuras/*.pdf|png
    saidas/tabelas/*.tex
    dados/eda_resumo.json
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scraper"))
import config  # noqa: E402

BASE = RAIZ / "dados" / "dataset_modelagem.csv"
FUNIL = RAIZ / "dados" / "funil_preprocessamento.csv"
FIG = RAIZ / "saidas" / "figuras"
TAB = RAIZ / "saidas" / "tabelas"
RESUMO = RAIZ / "dados" / "eda_resumo.json"

# Paleta (tema claro, impressao): azul como serie principal, laranja como segunda
AZUL, LARANJA = "#2a78d6", "#eb6834"
TINTA, TINTA_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRADE, EIXO = "#e1e0d9", "#c3c2b7"
RAMPA_AZUL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIVERGENTE = LinearSegmentedColormap.from_list("div", ["#e34948", "#f0efec", "#2a78d6"])

LARGURA_COLUNA = 3.35   # polegadas, uma coluna do template
LARGURA_PAGINA = 6.9

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 7, "axes.titlesize": 7.5,
    "axes.labelsize": 7, "xtick.labelsize": 6.5, "ytick.labelsize": 6.5, "legend.fontsize": 6.5,
    "axes.edgecolor": EIXO, "axes.labelcolor": TINTA_2, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": TINTA, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRADE, "grid.linewidth": 0.5, "axes.axisbelow": True,
    "savefig.dpi": 300, "savefig.bbox": "tight", "pdf.fonttype": 42,
})

ROTULOS = {
    "area_util_m2": "Área privativa", "dormitorios": "Dormitórios", "suites": "Suítes",
    "banheiros": "Banheiros", "vagas_garagem": "Vagas", "condominio": "Condomínio",
    "elevadores": "Elevadores", "lavabos": "Lavabos", "mobilia_ord": "Mobília",
    "dist_shopping_km": "Dist. shopping", "dist_hospital_km": "Dist. hospital",
    "dist_ensino_km": "Dist. ensino", "amen_piscina": "Piscina", "amen_academia": "Academia",
    "amen_churrasqueira": "Churrasqueira", "amen_salao_festas": "Salão de festas",
    "amen_playground": "Playground", "amen_portaria": "Portaria", "amen_sacada": "Sacada",
    "amen_ar_condicionado": "Ar-condicionado", "amen_elevador": "Elevador (lista)",
    "amen_lavanderia": "Lavanderia", "amen_aceita_pet": "Aceita pet",
    "na_planta": "Na planta", "dias_anunciado": "Dias anunciado",
    "latitude": "Latitude", "longitude": "Longitude",
}


def reais(x, _=None):
    if x >= 1e6:
        return f"R$ {x / 1e6:.1f} mi".replace(".", ",")
    return f"R$ {x / 1e3:.0f} mil"


def milhar(x, _=None):
    return f"{x:,.0f}".replace(",", ".")


def decimal_br(casas):
    return mticker.FuncFormatter(lambda x, _: f"{x:.{casas}f}".replace(".", ",").replace("-", "−"))


def salvar(fig, nome):
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / f"{nome}.pdf")
    fig.savefig(FIG / f"{nome}.png")
    plt.close(fig)


def fig_distribuicao_preco(df):
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 2.0))
    bins = np.logspace(np.log10(df.preco.min()), np.log10(df.preco.max()), 36)
    ax.hist(df.preco, bins=bins, color=AZUL, edgecolor="#fcfcfb", linewidth=0.6)
    ax.set_xscale("log")
    mediana = df.preco.median()
    ax.axvline(mediana, color=TINTA_2, linewidth=0.8, linestyle="--")
    ax.annotate(f"mediana\n{reais(mediana)}", (mediana, ax.get_ylim()[1] * 0.97),
                xytext=(-4, 0), textcoords="offset points", ha="right", va="top", color=TINTA_2, fontsize=6.5)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: reais(x).replace("R$ ", "")))
    ax.xaxis.set_minor_formatter(mticker.NullFormatter())
    ax.set_xticks([2e5, 5e5, 1e6, 2e6, 5e6])
    ax.set_xlabel("Preço anunciado (R$, escala logarítmica)")
    ax.set_ylabel("Anúncios")
    ax.grid(axis="x", visible=False)
    salvar(fig, "distribuicao_preco")


def fig_preco_area(df):
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 2.5))
    firme = df[df.preco_lancamento == 0]
    lanc = df[df.preco_lancamento == 1]
    ax.scatter(firme.area_util_m2, firme.preco, s=9, color=AZUL, alpha=0.55,
               edgecolor="#fcfcfb", linewidth=0.3, label=f"Valor do imóvel (n = {len(firme)})")
    ax.scatter(lanc.area_util_m2, lanc.preco, s=11, color=LARANJA, alpha=0.8, marker="D",
               edgecolor="#fcfcfb", linewidth=0.3, label=f"\u201cA partir de\u201d (n = {len(lanc)})")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(reais))
    ax.yaxis.set_minor_formatter(mticker.NullFormatter())
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}"))
    ax.xaxis.set_minor_formatter(mticker.NullFormatter())
    ax.set_xticks([25, 50, 100, 200, 400]); ax.set_yticks([2e5, 5e5, 1e6, 2e6, 4e6])
    ax.set_xlabel("Área privativa (m², escala log.)")
    ax.set_ylabel("Preço (escala log.)")
    ax.legend(loc="upper left", frameon=False, handletextpad=0.3)
    salvar(fig, "preco_area")


def fig_preco_m2_bairro(df, min_anuncios=20):
    cont = df.bairro.value_counts()
    bairros = cont[cont >= min_anuncios].index
    sub = df[df.bairro.isin(bairros)]
    ordem = sub.groupby("bairro").preco_m2.median().sort_values().index
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 2.6))
    dados = [sub.loc[sub.bairro == b, "preco_m2"] for b in ordem]
    bp = ax.boxplot(dados, vert=False, widths=0.55, patch_artist=True, showfliers=True,
                    medianprops=dict(color=TINTA, linewidth=1),
                    boxprops=dict(facecolor="#b7d3f6", edgecolor=AZUL, linewidth=0.7),
                    whiskerprops=dict(color=AZUL, linewidth=0.7), capprops=dict(color=AZUL, linewidth=0.7),
                    flierprops=dict(marker="o", markersize=2, markerfacecolor=AZUL, markeredgewidth=0, alpha=0.5))
    ax.set_yticks(range(1, len(ordem) + 1))
    ax.set_yticklabels([f"{b} ({cont[b]})" for b in ordem], color=TINTA_2)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(milhar))
    ax.set_xlabel("Preço por m² (R$)")
    ax.grid(axis="y", visible=False)
    salvar(fig, "preco_m2_bairro")
    return {b: float(df.loc[df.bairro == b, "preco_m2"].median()) for b in ordem}


def fig_mapa(df):
    geo = df[(df.geo_imputada == 0) & df.latitude.notna()].sort_values("preco_m2")
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 3.1))
    lim = geo.preco_m2.quantile([0.05, 0.95]).values
    sc = ax.scatter(geo.longitude, geo.latitude, c=geo.preco_m2.clip(*lim), s=8,
                    cmap=LinearSegmentedColormap.from_list("azul", RAMPA_AZUL),
                    edgecolor="#fcfcfb", linewidth=0.25)
    simbolos = {"shopping": ("s", "Shopping"), "hospital": ("P", "Hospital"), "ensino": ("^", "Ensino")}
    for cat, pontos in config.PONTOS_INTERESSE.items():
        m, rot = simbolos[cat]
        lats = [p[0] for p in pontos.values()]; lons = [p[1] for p in pontos.values()]
        ax.scatter(lons, lats, marker=m, s=26, color=LARANJA, edgecolor=TINTA, linewidth=0.5, label=rot, zorder=3)
    ax.set_aspect(1 / np.cos(np.radians(geo.latitude.mean())))
    ax.set_xlabel("Longitude"); ax.set_ylabel("Latitude")
    ax.xaxis.set_major_formatter(decimal_br(2)); ax.yaxis.set_major_formatter(decimal_br(2))
    ax.tick_params(labelsize=5.5)
    ax.legend(loc="lower left", frameon=True, framealpha=0.9, edgecolor=GRADE, title="Pontos de interesse",
              title_fontsize=6, borderpad=0.4)
    cb = fig.colorbar(sc, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("Preço por m² (R$)", color=TINTA_2)
    cb.ax.yaxis.set_major_formatter(mticker.FuncFormatter(milhar))
    cb.ax.tick_params(labelsize=5.5); cb.outline.set_visible(False)
    salvar(fig, "mapa_preco_m2")
    return len(geo)


def fig_correlacoes(df):
    cols = [c for c in ROTULOS if c in df.columns]
    corr = df[cols].corrwith(np.log(df.preco), method="spearman").dropna().sort_values()
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 3.4))
    cores = [AZUL if v >= 0 else LARANJA for v in corr.values]
    ax.barh([ROTULOS[c] for c in corr.index], corr.values, color=cores, height=0.65)
    ax.axvline(0, color=EIXO, linewidth=0.8)
    for i, v in enumerate(corr.values):
        ax.annotate(f"{v:.2f}".replace(".", ","), (v, i), xytext=(3 if v >= 0 else -3, 0),
                    textcoords="offset points", va="center", ha="left" if v >= 0 else "right",
                    fontsize=5.5, color=TINTA_2)
    ax.set_xlim(-0.35, 0.95)
    ax.xaxis.set_major_formatter(decimal_br(1))
    ax.set_xlabel("Correlação de Spearman com o preço")
    ax.tick_params(axis="y", labelsize=6, colors=TINTA_2)
    ax.grid(axis="y", visible=False)
    salvar(fig, "correlacao_preco")
    return corr.round(3).to_dict()


def fig_matriz_correlacao(df):
    cols = ["area_util_m2", "dormitorios", "suites", "banheiros", "vagas_garagem", "condominio",
            "dist_shopping_km", "dist_hospital_km", "dist_ensino_km"]
    m = df[cols + ["preco"]].corr(method="spearman")
    nomes = [ROTULOS[c] for c in cols] + ["Preço"]
    fig, ax = plt.subplots(figsize=(LARGURA_COLUNA, 3.0))
    im = ax.imshow(m.values, cmap=DIVERGENTE, vmin=-1, vmax=1)
    ax.set_xticks(range(len(nomes))); ax.set_yticks(range(len(nomes)))
    ax.set_xticklabels(nomes, rotation=45, ha="right", fontsize=5.5)
    ax.set_yticklabels(nomes, fontsize=5.5)
    ax.grid(False)
    for i in range(len(nomes)):
        for j in range(len(nomes)):
            v = m.values[i, j]
            texto = "1" if i == j else f"{v:.2f}".replace(".", ",").replace("-", "−")
            ax.text(j, i, texto, ha="center", va="center", fontsize=4.2,
                    color="#ffffff" if abs(v) > 0.6 else TINTA)
    cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
    cb.set_ticks([-1, -0.5, 0, 0.5, 1])
    cb.ax.yaxis.set_major_formatter(decimal_br(1))
    cb.ax.tick_params(labelsize=5.5); cb.outline.set_visible(False)
    salvar(fig, "matriz_correlacao")


def tabela_descritiva(df):
    linhas = [("Preço (R\\$)", "preco", 0), ("Preço por m² (R\\$)", "preco_m2", 0),
              ("Área privativa (m²)", "area_util_m2", 1), ("Dormitórios", "dormitorios", 1),
              ("Suítes", "suites", 1), ("Banheiros", "banheiros", 1), ("Vagas de garagem", "vagas_garagem", 1),
              ("Condomínio (R\\$/mês)", "condominio", 0), ("Dist. shopping (km)", "dist_shopping_km", 2),
              ("Dist. hospital (km)", "dist_hospital_km", 2), ("Dist. ensino (km)", "dist_ensino_km", 2)]

    def fmt(v, casas):
        return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")

    corpo = []
    for rot, col, casas in linhas:
        s = df[col].dropna()
        corpo.append(f"{rot} & {len(s)} & {fmt(s.mean(), casas)} & "
                     f"{fmt(s.median(), casas)} & {fmt(s.std(), casas)} & {fmt(s.min(), casas)} & {fmt(s.max(), casas)} \\\\")
    tex = (
        "% Gerado por analise/eda.py - nao editar a mao\n"
        "\\begin{table*}[ht]\n\\centering\n"
        "\\caption{Estatísticas descritivas das variáveis numéricas da base de modelagem.}\n"
        "\\label{tab:descritiva}\n"
        "\\begin{tabular}{lrrrrrr}\n\\toprule\n"
        "\\textbf{Variável} & \\textbf{n} & \\textbf{Média} & \\textbf{Mediana} & \\textbf{Desvio padrão} & "
        "\\textbf{Mínimo} & \\textbf{Máximo} \\\\\n\\midrule\n"
        + "\n".join(corpo) +
        "\n\\bottomrule\n\\end{tabular}\n\\end{table*}\n"
    )
    TAB.mkdir(parents=True, exist_ok=True)
    (TAB / "descritiva.tex").write_text(tex, encoding="utf-8")


def tabela_funil():
    f = pd.read_csv(FUNIL, encoding="utf-8-sig")
    f = f[(f.removidos > 0) | (f.index == 0)]
    etapa = f.etapa.str.replace("Revisão manual: ", "", regex=False)
    etapa = etapa.str[0].str.upper() + etapa.str[1:]
    corpo = "\n".join(f"{e} & {r.removidos if r.removidos else '--'} & {milhar(r.restantes)} \\\\"
                      for e, r in zip(etapa, f.itertuples()))
    tex = (
        "% Gerado por analise/eda.py - nao editar a mao\n"
        "\\begin{table}[ht]\n\\centering\n"
        "\\caption{Registros removidos em cada etapa do pré-processamento.}\n"
        "\\label{tab:funil}\n"
        "\\begin{tabularx}{\\columnwidth}{Xrr}\n\\toprule\n"
        "\\textbf{Etapa} & \\textbf{Removidos} & \\textbf{Restantes} \\\\\n\\midrule\n"
        + corpo +
        "\n\\bottomrule\n\\end{tabularx}\n\\end{table}\n"
    )
    (TAB / "funil.tex").write_text(tex, encoding="utf-8")


def main():
    df = pd.read_csv(BASE, encoding="utf-8-sig")
    fig_distribuicao_preco(df)
    fig_preco_area(df)
    medianas_bairro = fig_preco_m2_bairro(df)
    n_mapa = fig_mapa(df)
    corr = fig_correlacoes(df)
    fig_matriz_correlacao(df)
    tabela_descritiva(df)
    tabela_funil()

    firme = df[df.preco_lancamento == 0]
    resumo = {
        "n": len(df), "n_preco_firme": len(firme), "n_lancamento": int(df.preco_lancamento.sum()),
        "preco_mediana": float(df.preco.median()), "preco_media": float(df.preco.mean()),
        "preco_m2_mediana": float(df.preco_m2.median()),
        "preco_m2_mediana_firme": float(firme.preco_m2.median()),
        "preco_m2_mediana_lancamento": float(df[df.preco_lancamento == 1].preco_m2.median()),
        "area_mediana": float(df.area_util_m2.median()),
        "assimetria_preco": float(df.preco.skew()), "assimetria_log_preco": float(np.log(df.preco).skew()),
        "n_bairros": int(df.bairro.nunique()), "pct_centro": float((df.bairro == "Centro").mean()),
        "n_mapa": n_mapa, "medianas_preco_m2_bairro": medianas_bairro, "spearman_log_preco": corr,
        "dist_mediana_km": {c: float(df[f"dist_{c}_km"].median()) for c in config.PONTOS_INTERESSE},
        "pct_imob_top3": float(df.imobiliaria_origem.value_counts(normalize=True).head(3).sum()),
    }
    RESUMO.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

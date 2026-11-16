"""
Figuras e tabelas das secoes de desempenho dos modelos e de importancia das
variaveis, a partir dos resultados gravados por experimento_final.py.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Uso:
    python analise/figuras_resultados.py
Entrada:
    dados/resultados/*.csv e dados/resultados/modelos/*.joblib
Saidas:
    saidas/figuras/mape_particoes.pdf|png
    saidas/figuras/importancia_grupos.pdf|png
    saidas/figuras/shap_gradient_boosting.pdf|png
    saidas/tabelas/resultados_modelos.tex
    dados/resultados/importancia_grupos.csv
"""

import warnings

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
from sklearn.metrics import mean_absolute_percentage_error

import eda as e          # paleta, tamanhos e rotulos das figuras do artigo
import modelagem as m

warnings.filterwarnings("ignore", category=UserWarning)

ORDEM = ["LightGBM", "XGBoost", "Gradient Boosting", "Random Forest", "Regressão Linear"]
CORES = {"LightGBM": e.AZUL, "XGBoost": "#6da7ec", "Gradient Boosting": "#184f95",
         "Random Forest": e.LARANJA, "Regressão Linear": e.MUTED}
ARQUIVO_MODELO = {n: n.lower().replace(" ", "_").replace("ã", "a") + ".joblib" for n in ORDEM}

# Blocos de variaveis para a importancia por permutacao agrupada: variaveis muito
# correlacionadas sao embaralhadas juntas, para que a importancia nao seja dividida
# entre elas de forma instavel.
GRUPOS = {
    "Tamanho e padrão": ["area_util_m2", "dormitorios", "suites", "banheiros", "lavabos", "vagas_garagem"],
    "Condomínio": ["condominio"],
    "Localização": ["bairro", "latitude", "longitude", "dist_shopping_km", "dist_hospital_km",
                    "dist_ensino_km"],
    "Amenidades": [c for c in m.NUMERICAS if c.startswith("amen_")],
    "Edifício e unidade": ["elevadores", "posicao", "posicao_solar", "mobilia_ord", "na_planta"],
}
ROTULOS = {**e.ROTULOS, "posicao": "Posição", "posicao_solar": "Posição solar", "bairro": "Bairro"}


def num(x, casas=1):
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tabela_resultados(resumo_cv: pd.DataFrame, teste: pd.DataFrame) -> None:
    cv = resumo_cv[resumo_cv["configuracao"] == "ajustado"].set_index("modelo")
    linhas = []
    for n in ORDEM:
        c, t = cv.loc[n], teste.loc[n]
        linhas.append(
            f"{n} & {num(c.MAPE_mean)} $\\pm$ {num(c.MAPE_std)} & {num(c.R2_mean, 3)} & "
            f"{num(c.RMSE_mean / 1e3, 0)} & {num(t.MAPE)} & {num(t.R2, 3)} & "
            f"{num(t.RMSE / 1e3, 0)} & {num(t.MAE / 1e3, 0)} \\\\"
        )
    tex = "\n".join([
        "% Gerado por analise/figuras_resultados.py - nao editar a mao",
        "\\begin{table*}[ht]",
        "\\centering",
        "\\caption{Desempenho dos modelos ajustados na validação cruzada repetida (média e desvio "
        "padrão das 25 partições do treino) e no conjunto de teste. RMSE e MAE em milhares de reais.}",
        "\\label{tab:resultados}",
        "\\begin{tabular}{lrrrrrrr}",
        "\\toprule",
        "& \\multicolumn{3}{c}{\\textbf{Validação cruzada (treino)}} & "
        "\\multicolumn{4}{c}{\\textbf{Conjunto de teste}} \\\\",
        "\\cmidrule(lr){2-4} \\cmidrule(lr){5-8}",
        "\\textbf{Modelo} & \\textbf{MAPE (\\%)} & \\textbf{$R^2$} & \\textbf{RMSE} & "
        "\\textbf{MAPE (\\%)} & \\textbf{$R^2$} & \\textbf{RMSE} & \\textbf{MAE} \\\\",
        "\\midrule",
        *linhas,
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table*}",
        "",
    ])
    e.TAB.mkdir(parents=True, exist_ok=True)
    (e.TAB / "resultados_modelos.tex").write_text(tex, encoding="utf-8")


def fig_mape_particoes(por_particao: pd.DataFrame, teste: pd.DataFrame) -> None:
    dados = por_particao[por_particao["configuracao"] == "ajustado"]
    fig, ax = plt.subplots(figsize=(e.LARGURA_COLUNA, 2.3))
    ordem = ORDEM[::-1]
    for i, n in enumerate(ordem, 1):
        v = dados.loc[dados.modelo == n, "MAPE"]
        ax.boxplot(v, positions=[i], vert=False, widths=0.55, showfliers=False,
                   medianprops=dict(color=e.TINTA, linewidth=0.9),
                   boxprops=dict(color=e.TINTA_2, linewidth=0.6),
                   whiskerprops=dict(color=e.TINTA_2, linewidth=0.6), capprops=dict(linewidth=0.6))
        jitter = np.random.default_rng(0).uniform(-0.12, 0.12, len(v))
        ax.scatter(v, i + jitter, s=5, color=CORES[n], alpha=0.8, zorder=3, linewidths=0)
        ax.scatter(teste.loc[n, "MAPE"], i, marker="D", s=16, color=e.TINTA, zorder=4)
    ax.set_yticks(range(1, len(ordem) + 1))
    ax.set_yticklabels(ordem)
    ax.set_xlabel("MAPE (%)")
    ax.xaxis.set_major_formatter(e.decimal_br(0))
    ax.grid(axis="y", visible=False)
    ax.scatter([], [], marker="D", s=16, color=e.TINTA, label="Conjunto de teste")
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, handletextpad=0.2,
              borderaxespad=0)
    e.salvar(fig, "mape_particoes")


def importancia_grupos(modelos: dict, X_te, y_te, n_rep: int = 20) -> pd.DataFrame:
    """Aumento do MAPE (p.p.) quando todas as variaveis de um grupo sao embaralhadas
    juntas, com a mesma permutacao de linhas."""
    rng = np.random.default_rng(m.SEMENTE)
    linhas = []
    for nome, modelo in modelos.items():
        base = mean_absolute_percentage_error(y_te, modelo.predict(X_te))
        for grupo, cols in GRUPOS.items():
            aumentos = []
            for _ in range(n_rep):
                Xp = X_te.copy()
                Xp[cols] = X_te[cols].to_numpy()[rng.permutation(len(X_te))]
                aumentos.append(mean_absolute_percentage_error(y_te, modelo.predict(Xp)) - base)
            linhas.append({"modelo": nome, "grupo": grupo,
                           "aumento_MAPE_pp": np.mean(aumentos) * 100, "dp_pp": np.std(aumentos) * 100})
    return pd.DataFrame(linhas)


def fig_importancia_grupos(imp: pd.DataFrame) -> None:
    grupos = imp.groupby("grupo")["aumento_MAPE_pp"].mean().sort_values().index.tolist()
    fig, ax = plt.subplots(figsize=(e.LARGURA_COLUNA, 2.6))
    altura = 0.15
    for j, n in enumerate(ORDEM):
        d = imp[imp.modelo == n].set_index("grupo").loc[grupos]
        pos = np.arange(len(grupos)) + (2 - j) * altura
        ax.barh(pos, d["aumento_MAPE_pp"], height=altura, color=CORES[n], label=n)
    ax.set_yticks(range(len(grupos)))
    ax.set_yticklabels(grupos)
    ax.set_xlabel("Aumento do MAPE ao embaralhar o grupo (p.p.)")
    ax.xaxis.set_major_formatter(e.decimal_br(0))
    ax.grid(axis="y", visible=False)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles, labels, loc="lower right", frameon=False)
    e.salvar(fig, "importancia_grupos")


def rotulo_coluna(col: str) -> str:
    nome = col.split("__", 1)[1]
    ausente = nome.startswith("missingindicator_")
    nome = nome.replace("missingindicator_", "")
    for c in m.CATEGORICAS:
        if nome.startswith(c + "_"):
            valor = nome[len(c) + 1:].replace("_", " ")
            valor = {"nao informado": "não informado", "infrequent sklearn": "outros"}.get(valor, valor)
            return f"{ROTULOS[c]}: {valor}"
    return ROTULOS.get(nome, nome) + (" (ausente)" if ausente else "")


def fig_shap(modelo, X_te) -> pd.DataFrame:
    valores, Xt, _ = m.valores_shap(modelo, X_te)
    Xt = Xt.rename(columns=rotulo_coluna)
    plt.figure()
    shap.summary_plot(valores, Xt, max_display=12, show=False, plot_size=(e.LARGURA_COLUNA, 3.1),
                      color_bar_label="Valor da variável")
    fig = plt.gcf()
    for ax in fig.axes:
        ax.tick_params(labelsize=6.5)
        ax.xaxis.label.set_size(7)
    fig.axes[0].set_xlabel("Contribuição SHAP para log(preço)")
    barra = fig.axes[-1]
    barra.set_yticklabels(["Baixo", "Alto"], fontsize=6.5)
    barra.set_ylabel("Valor da variável", fontsize=7, labelpad=-6)
    for c in fig.axes[0].collections:
        c.set_sizes([6])
    e.salvar(fig, "shap_gradient_boosting")
    # direcao do efeito: correlacao de Spearman entre o valor da variavel e o SHAP
    direcao = pd.Series({c: pd.Series(Xt[c].to_numpy()).corr(pd.Series(valores[:, i]), method="spearman")
                         for i, c in enumerate(Xt.columns)})
    media = pd.Series(np.abs(valores).mean(axis=0), index=Xt.columns)
    return pd.DataFrame({"media_abs_shap": media, "direcao_spearman": direcao}) \
        .sort_values("media_abs_shap", ascending=False)


def main() -> None:
    r = m.RESULTADOS
    resumo = pd.read_csv(r / "cv_repetida_resumo.csv", encoding="utf-8-sig")
    por_particao = pd.read_csv(r / "cv_repetida_por_particao.csv", encoding="utf-8-sig")
    teste = pd.read_csv(r / "teste_metricas.csv", encoding="utf-8-sig").set_index("modelo")
    modelos = {n: joblib.load(r / "modelos" / ARQUIVO_MODELO[n]) for n in ORDEM}
    _, X_te, _, y_te = m.dividir(m.carregar_base())

    tabela_resultados(resumo, teste)
    fig_mape_particoes(por_particao, teste)
    imp = importancia_grupos(modelos, X_te, y_te)
    imp.to_csv(r / "importancia_grupos.csv", index=False, encoding="utf-8-sig")
    fig_importancia_grupos(imp)
    shap_dir = fig_shap(modelos["Gradient Boosting"], X_te)
    shap_dir.to_csv(r / "shap_direcao.csv", encoding="utf-8-sig")

    pd.set_option("display.width", 160)
    print(imp.pivot(index="grupo", columns="modelo", values="aumento_MAPE_pp")[ORDEM].round(2))
    print(shap_dir.head(15).round(3))


if __name__ == "__main__":
    main()

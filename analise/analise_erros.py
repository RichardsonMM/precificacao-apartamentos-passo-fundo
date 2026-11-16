"""
Analise complementar do erro no conjunto de teste: comparacao com estimativas
ingenuas e distribuicao do erro por faixa de preco.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Perguntas respondidas (Secao 4.3 do artigo):
1. O erro dos modelos e alto? Comparacao com duas estimativas que nao usam
   aprendizado de maquina: o preco mediano do treino para todos os imoveis e a
   area do imovel multiplicada pelo preco mediano do metro quadrado no treino.
2. Onde o modelo erra? Erro do melhor modelo no teste por faixa de preco, com o
   vies mediano (sinal do erro) e a parcela do erro quadratico de cada faixa.

Uso:
    python analise/analise_erros.py
Entrada:
    dados/dataset_modelagem.csv e dados/resultados/modelos/*.joblib
Saidas:
    dados/resultados/erro_referencias.csv, dados/resultados/erro_faixas.csv
    saidas/tabelas/erro_referencias.tex, saidas/tabelas/erro_faixas.tex
"""

import warnings

import joblib
import numpy as np
import pandas as pd

import eda as e          # caminho das tabelas do artigo
import modelagem as m

warnings.filterwarnings("ignore", category=UserWarning)

ORDEM = ["LightGBM", "XGBoost", "Gradient Boosting", "Random Forest", "Regressão Linear"]
ARQUIVO_MODELO = {n: n.lower().replace(" ", "_").replace("ã", "a") + ".joblib" for n in ORDEM}
MELHOR = "Gradient Boosting"   # melhor modelo no teste (experimento_resumo.json)
FAIXAS = [0, 400e3, 700e3, 1.2e6, 2e6, np.inf]
ROTULOS_FAIXAS = ["Até 400", "400 a 700", "700 a 1.200", "1.200 a 2.000", "Acima de 2.000"]   # mil R$


def num(x, casas=1):
    return f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def resumo_erro(y_real: np.ndarray, y_prev: np.ndarray) -> dict:
    erro = y_prev - y_real
    ape = np.abs(erro) / y_real * 100
    return {
        "MAE": np.abs(erro).mean(),
        "RMSE": np.sqrt((erro ** 2).mean()),
        "MAPE": ape.mean(),
        "MdAPE": np.median(ape),
        "ate_10pct": (ape <= 10).mean() * 100,
        "ate_20pct": (ape <= 20).mean() * 100,
    }


def referencias(X_tr, y_tr, X_te, y_te, modelos) -> pd.DataFrame:
    area_tr = X_tr["area_util_m2"]
    preco_m2 = (y_tr / area_tr).median()
    area_te = X_te["area_util_m2"].fillna(area_tr.median())
    estimativas = {
        "Preço mediano": np.full(len(y_te), y_tr.median()),
        "Preço do m$^2$ $\\times$ área": area_te.values * preco_m2,
    }
    estimativas.update({n: modelos[n].predict(X_te) for n in ORDEM})
    linhas = [{"estimativa": n, **resumo_erro(y_te.values, p)} for n, p in estimativas.items()]
    return pd.DataFrame(linhas)


def por_faixa(y_te, y_prev) -> pd.DataFrame:
    d = pd.DataFrame({"real": y_te.values, "erro": y_prev - y_te.values})
    d["faixa"] = pd.cut(d["real"], FAIXAS, labels=ROTULOS_FAIXAS)
    total_quad = (d["erro"] ** 2).sum()
    linhas = []
    for faixa, g in d.groupby("faixa", observed=True):
        linhas.append({
            "faixa": faixa, "n": len(g),
            "MAE": g["erro"].abs().mean(),
            "MAPE": (g["erro"].abs() / g["real"]).mean() * 100,
            "vies_mediano_pct": np.median(g["erro"] / g["real"] * 100),
            "parcela_erro_quadratico_pct": (g["erro"] ** 2).sum() / total_quad * 100,
        })
    return pd.DataFrame(linhas)


def tabela_referencias(ref: pd.DataFrame) -> None:
    linhas = []
    for i, r in ref.iterrows():
        if i == 2:
            linhas.append("\\midrule")
        linhas.append(f"{r.estimativa} & {num(r.MAE / 1e3, 0)} & {num(r.MAPE)} & {num(r.MdAPE)} & "
                      f"{num(r.ate_10pct, 0)} & {num(r.ate_20pct, 0)} \\\\")
    tex = "\n".join([
        "% Gerado por analise/analise_erros.py - nao editar a mao",
        "\\begin{table}[ht]",
        "\\centering",
        "\\caption{Erro no conjunto de teste dos modelos e das estimativas ingênuas. MAE em milhares de "
        "reais; MAPE e erro percentual mediano (MdAPE) em \\%; nas duas últimas colunas, percentual de "
        "imóveis com erro de até 10\\% e de até 20\\%.}",
        "\\label{tab:referencias}",
        "\\small",
        "\\begin{tabular}{lrrrrr}",
        "\\toprule",
        "\\textbf{Estimativa} & \\textbf{MAE} & \\textbf{MAPE} & \\textbf{MdAPE} & "
        "\\textbf{$\\leq$10\\%} & \\textbf{$\\leq$20\\%} \\\\",
        "\\midrule",
        *linhas,
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
        "",
    ])
    (e.TAB / "erro_referencias.tex").write_text(tex, encoding="utf-8")


def tabela_faixas(fx: pd.DataFrame) -> None:
    linhas = [
        f"{r.faixa} & {r.n} & {num(r.MAE / 1e3, 0)} & {num(r.MAPE)} & "
        f"{'+' if r.vies_mediano_pct > 0 else '$-$'}{num(abs(r.vies_mediano_pct))} & "
        f"{num(r.parcela_erro_quadratico_pct, 0)} \\\\"
        for r in fx.itertuples()
    ]
    tex = "\n".join([
        "% Gerado por analise/analise_erros.py - nao editar a mao",
        "\\begin{table}[ht]",
        "\\centering",
        f"\\caption{{Erro do \\textit{{{MELHOR}}} no conjunto de teste por faixa de preço anunciado. "
        "Faixas e MAE em milhares de reais; o viés é a mediana do erro relativo (valores positivos "
        "indicam superestimação); Erro$^2$ é a parcela de cada faixa no erro quadrático total.}",
        "\\label{tab:faixas}",
        "\\small",
        "\\begin{tabular}{lrrrrr}",
        "\\toprule",
        "\\textbf{Faixa} & \\textbf{n} & \\textbf{MAE} & \\textbf{MAPE} & \\textbf{Viés} & "
        "\\textbf{Erro$^2$} \\\\",
        "& & & \\textbf{(\\%)} & \\textbf{(\\%)} & \\textbf{(\\%)} \\\\",
        "\\midrule",
        *linhas,
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
        "",
    ])
    (e.TAB / "erro_faixas.tex").write_text(tex, encoding="utf-8")


def main() -> None:
    r = m.RESULTADOS
    base = m.carregar_base()
    X_tr, X_te, y_tr, y_te = m.dividir(base)
    modelos = {n: joblib.load(r / "modelos" / ARQUIVO_MODELO[n]) for n in ORDEM}

    ref = referencias(X_tr, y_tr, X_te, y_te, modelos)
    fx = por_faixa(y_te, modelos[MELHOR].predict(X_te))
    ref.to_csv(r / "erro_referencias.csv", index=False, encoding="utf-8-sig")
    fx.to_csv(r / "erro_faixas.csv", index=False, encoding="utf-8-sig")
    e.TAB.mkdir(parents=True, exist_ok=True)
    tabela_referencias(ref)
    tabela_faixas(fx)

    pd.set_option("display.width", 160)
    print(f"Teste: {len(y_te)} imoveis | mediana R$ {y_te.median():,.0f} | media R$ {y_te.mean():,.0f}")
    print(ref.round(1).to_string(index=False))
    print(fx.round(1).to_string(index=False))
    prev = modelos[MELHOR].predict(X_te)
    ate = y_te.values <= 1.2e6
    erro = prev[ate] - y_te.values[ate]
    print(f"{MELHOR} sem imoveis acima de R$ 1,2 milhao (n={ate.sum()}): "
          f"MAE {np.abs(erro).mean():,.0f} | RMSE {np.sqrt((erro ** 2).mean()):,.0f}")


if __name__ == "__main__":
    main()

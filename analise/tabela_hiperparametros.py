"""
Tabela dos hiperparametros selecionados pela busca aleatoria (Secao 4.3 do artigo).

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Uso:
    python analise/tabela_hiperparametros.py
Entrada:
    dados/resultados/melhores_hiperparametros.csv (gerado por experimento_final.py)
Saida:
    saidas/tabelas/hiperparametros_escolhidos.tex
"""

import pandas as pd

import eda as e
import modelagem as m

ORDEM = ["Random Forest", "Gradient Boosting", "XGBoost", "LightGBM"]
ITALICO = {"Random Forest", "Gradient Boosting"}
IGNORAR = {"subsample_freq"}      # fixo em 1, nao foi sorteado
CASAS = {"learning_rate": 3, "subsample": 2, "colsample_bytree": 2, "reg_lambda": 3, "reg_alpha": 3}
CATEGORIAS = {"sqrt": "raiz quadrada", "None": "todas"}


def num(x, casas):
    return f"{x:.{casas}f}".replace(".", ",")


def valor(param: str, v) -> str:
    if pd.isna(v) or v == "":
        return "sem limite" if param == "max_depth" else "todas"
    if str(v) in CATEGORIAS:
        return CATEGORIAS[str(v)]
    if param in CASAS:
        return num(float(v), CASAS[param])
    return str(int(float(v)))


def main() -> None:
    hp = pd.read_csv(m.RESULTADOS / "melhores_hiperparametros.csv", encoding="utf-8-sig", dtype=str)
    linhas = []
    for modelo in ORDEM:
        sub = hp[(hp["modelo"] == modelo) & ~hp["hiperparametro"].isin(IGNORAR)]
        pares = "; ".join(f"\\texttt{{{p.replace('_', chr(92) + '_')}}}: {valor(p, v)}"
                          for p, v in zip(sub["hiperparametro"], sub["valor"]))
        nome = f"\\textit{{{modelo}}}" if modelo in ITALICO else modelo
        linhas.append(f"{nome} & {pares} \\\\")
    tex = "\n".join([
        "% Gerado por analise/tabela_hiperparametros.py - nao editar a mao",
        "\\begin{table*}[ht]",
        "\\centering",
        "\\caption{Hiperparâmetros selecionados pela busca aleatória (menor MAPE médio na validação "
        "cruzada com cinco partições sobre o conjunto de treino).}",
        "\\label{tab:hiper_escolhidos}",
        "\\begin{tabularx}{\\textwidth}{lX}",
        "\\toprule",
        "\\textbf{Modelo} & \\textbf{Configuração selecionada} \\\\",
        "\\midrule",
        *linhas,
        "\\bottomrule",
        "\\end{tabularx}",
        "\\end{table*}",
        "",
    ])
    e.TAB.mkdir(parents=True, exist_ok=True)
    (e.TAB / "hiperparametros_escolhidos.tex").write_text(tex, encoding="utf-8")
    print(tex)


if __name__ == "__main__":
    main()

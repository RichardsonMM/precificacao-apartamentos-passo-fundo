"""
Modelagem: divisao treino/teste, pipelines dos cinco modelos e avaliacao.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Decisoes de projeto (Secoes 3.2.2 e 3.3 do artigo):
- Alvo: log(preco). O TransformedTargetRegressor treina no log e devolve a
  previsao em reais, entao todas as metricas sao calculadas em R$.
- Divisao 70/30 com embaralhamento e semente fixa. O arquivo vem ordenado por
  preco (ordem da listagem do portal); sem embaralhar, a divisao seria enviesada.
- Imputacao, normalizacao e one-hot ficam DENTRO do pipeline, ajustados so nos
  dados de treino de cada particao, para nao vazar informacao da validacao.
- O conjunto de teste e separado aqui e so e usado na avaliacao final.
- Ajuste de hiperparametros por busca aleatoria (RandomizedSearchCV) no treino.
- Comparacao entre modelos por validacao cruzada repetida (5 x 5), com o teste t
  corrigido para reamostragem (Nadeau e Bengio, 2003) em cada par de modelos e
  correcao de Holm para as comparacoes multiplas.

Uso como modulo (ver notebooks/02_modelagem_e_resultados.ipynb e analise/experimento_final.py):
    base = carregar_base()
    X_tr, X_te, y_tr, y_te = dividir(base)
    resultados = avaliar_cv(modelos_referencia(), X_tr, y_tr)
"""

import itertools
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from scipy.stats import loguniform, randint, t, uniform
from sklearn.base import clone
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import (mean_absolute_error, mean_absolute_percentage_error,
                             r2_score, root_mean_squared_error)
from sklearn.model_selection import (KFold, RandomizedSearchCV, RepeatedKFold,
                                     cross_validate, train_test_split)
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import MinMaxScaler, OneHotEncoder
from xgboost import XGBRegressor

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scraper"))
import config  # noqa: E402

BASE = RAIZ / "dados" / "dataset_modelagem.csv"
RESULTADOS = RAIZ / "dados" / "resultados"

SEMENTE = config.SEMENTE
PROPORCAO_TESTE = 0.30
N_PARTICOES = 5
N_REPETICOES = 5              # validacao cruzada repetida: 5 x 5 = 25 estimativas por modelo
N_ITERACOES_BUSCA = 50        # combinacoes sorteadas por modelo na busca aleatoria
METRICA_SELECAO = "MAPE"      # criterio para escolher a melhor configuracao e ordenar os modelos
ALFA = 0.05
MIN_ANUNCIOS_CATEGORIA = 10   # bairros com menos anuncios no treino viram "infrequentes"

# Variaveis preditoras. Ficam de fora: preco_m2 (deriva do alvo); imobiliaria_origem
# e dias_anunciado (descrevem o anuncio, nao o imovel, e nao existem para um imovel
# novo a ser avaliado); bairro_inferido e geo_imputada (marcas de auditoria).
NUMERICAS = [
    "area_util_m2", "dormitorios", "suites", "banheiros", "lavabos", "vagas_garagem",
    "elevadores", "condominio", "mobilia_ord", "na_planta",
    "latitude", "longitude", "dist_shopping_km", "dist_hospital_km", "dist_ensino_km",
    "amen_piscina", "amen_churrasqueira", "amen_salao_festas", "amen_academia", "amen_elevador",
    "amen_portaria", "amen_sacada", "amen_playground", "amen_lavanderia",
    "amen_ar_condicionado", "amen_aceita_pet",
]
CATEGORICAS = ["bairro", "posicao", "posicao_solar"]

METRICAS = {
    "MAE": "neg_mean_absolute_error",
    "RMSE": "neg_root_mean_squared_error",
    "R2": "r2",
    "MAPE": "neg_mean_absolute_percentage_error",
}


def carregar_base(incluir_lancamentos: bool = False) -> pd.DataFrame:
    """Base de modelagem. Por padrao, so anuncios com preco firme: os 'A partir de'
    sao preco de tabela de lancamento, nao de uma unidade especifica."""
    base = pd.read_csv(BASE, encoding="utf-8-sig")
    if not incluir_lancamentos:
        base = base[base["preco_lancamento"] == 0]
    return base.reset_index(drop=True)


def dividir(base: pd.DataFrame):
    X = base[NUMERICAS + CATEGORICAS]
    y = base["preco"]
    return train_test_split(X, y, test_size=PROPORCAO_TESTE, shuffle=True, random_state=SEMENTE)


def preprocessador(numericas_cols=None) -> ColumnTransformer:
    """O mesmo para todos os modelos. Ausentes numericos: mediana do treino, mais
    uma coluna indicadora (a ausencia de condominio, por exemplo, pode ser
    informativa). Categoricas: ausente vira 'nao_informado'; categorias raras no
    treino sao agrupadas. Min-Max so faz diferenca para a Regressao Linear."""
    numericas = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), MinMaxScaler())
    categoricas = make_pipeline(
        SimpleImputer(strategy="constant", fill_value="nao_informado"),
        OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=MIN_ANUNCIOS_CATEGORIA,
                      sparse_output=False),
    )
    return ColumnTransformer([("num", numericas, numericas_cols or NUMERICAS),
                              ("cat", categoricas, CATEGORICAS)])


def com_alvo_em_log(estimador, numericas_cols=None) -> TransformedTargetRegressor:
    modelo = Pipeline([("prep", preprocessador(numericas_cols)), ("modelo", estimador)])
    return TransformedTargetRegressor(regressor=modelo, func=np.log, inverse_func=np.exp)


def modelos_referencia() -> dict:
    """Os cinco modelos da proposta, com os hiperparametros padrao de cada biblioteca."""
    return {
        "Regressão Linear": com_alvo_em_log(LinearRegression()),
        "Random Forest": com_alvo_em_log(RandomForestRegressor(random_state=SEMENTE, n_jobs=-1)),
        "Gradient Boosting": com_alvo_em_log(GradientBoostingRegressor(random_state=SEMENTE)),
        "XGBoost": com_alvo_em_log(XGBRegressor(random_state=SEMENTE, n_jobs=-1)),
        "LightGBM": com_alvo_em_log(LGBMRegressor(random_state=SEMENTE, n_jobs=-1, verbose=-1)),
    }


# Espacos de busca dos modelos de arvore. Faixas definidas a partir da documentacao
# de cada biblioteca, centradas nos valores padrao e com regularizacao suficiente
# para uma base pequena (~700 anuncios de treino). O prefixo segue a estrutura
# TransformedTargetRegressor -> Pipeline -> passo "modelo".
_P = "regressor__modelo__"
ESPACOS_BUSCA = {
    "Random Forest": {
        _P + "n_estimators": randint(200, 801),
        _P + "max_depth": [None, 10, 20, 30],
        _P + "min_samples_leaf": randint(1, 6),
        _P + "max_features": [1.0, 0.5, 0.33, "sqrt"],
    },
    "Gradient Boosting": {
        _P + "n_estimators": randint(100, 801),
        _P + "learning_rate": loguniform(0.01, 0.2),
        _P + "max_depth": randint(2, 7),
        _P + "min_samples_leaf": randint(1, 11),
        _P + "subsample": uniform(0.6, 0.4),
        _P + "max_features": [None, 0.5, "sqrt"],
    },
    "XGBoost": {
        _P + "n_estimators": randint(100, 801),
        _P + "learning_rate": loguniform(0.01, 0.2),
        _P + "max_depth": randint(2, 9),
        _P + "min_child_weight": randint(1, 11),
        _P + "subsample": uniform(0.6, 0.4),
        _P + "colsample_bytree": uniform(0.5, 0.5),
        _P + "reg_lambda": loguniform(0.1, 10),
        _P + "reg_alpha": loguniform(1e-3, 1),
    },
    "LightGBM": {
        _P + "n_estimators": randint(100, 801),
        _P + "learning_rate": loguniform(0.01, 0.2),
        _P + "num_leaves": randint(8, 65),
        _P + "min_child_samples": randint(5, 41),
        _P + "subsample": uniform(0.6, 0.4),
        _P + "subsample_freq": [1],
        _P + "colsample_bytree": uniform(0.5, 0.5),
        _P + "reg_lambda": loguniform(0.01, 10),
    },
}


def ajustar_hiperparametros(modelos: dict, X, y, n_iter=N_ITERACOES_BUSCA):
    """Busca aleatoria com validacao cruzada de 5 particoes no treino, para cada modelo
    que tem espaco de busca (a Regressao Linear nao tem hiperparametros a ajustar).
    Devolve os modelos com a melhor configuracao (pelo MAPE medio) e uma tabela com
    todas as configuracoes avaliadas."""
    cv = KFold(N_PARTICOES, shuffle=True, random_state=SEMENTE)
    ajustados, historico = {}, []
    for nome, modelo in modelos.items():
        if nome not in ESPACOS_BUSCA:
            ajustados[nome] = modelo
            continue
        modelo = clone(modelo)
        if "n_jobs" in modelo.regressor.named_steps["modelo"].get_params():
            modelo.set_params(**{_P + "n_jobs": 1})   # paraleliza a busca, nao o modelo
        busca = RandomizedSearchCV(
            modelo, ESPACOS_BUSCA[nome], n_iter=n_iter, cv=cv, scoring=METRICAS,
            refit=METRICA_SELECAO, random_state=SEMENTE, n_jobs=-1,
        )
        busca.fit(X, y)
        ajustados[nome] = busca.best_estimator_
        r = pd.DataFrame(busca.cv_results_)
        tabela = pd.DataFrame({
            "modelo": nome,
            "MAPE": -r["mean_test_MAPE"] * 100, "RMSE": -r["mean_test_RMSE"],
            "MAE": -r["mean_test_MAE"], "R2": r["mean_test_R2"],
            "melhor": r["rank_test_MAPE"] == 1,
        })
        params = pd.json_normalize(r["params"]).rename(columns=lambda c: c.replace(_P, ""))
        historico.append(pd.concat([tabela, params], axis=1))
    return ajustados, pd.concat(historico, ignore_index=True)


def melhores_hiperparametros(ajustados: dict) -> pd.DataFrame:
    """Hiperparametros da configuracao escolhida para cada modelo ajustado."""
    linhas = []
    for nome in ESPACOS_BUSCA:
        if nome in ajustados:
            est = ajustados[nome].regressor.named_steps["modelo"].get_params()
            for p in ESPACOS_BUSCA[nome]:
                chave = p.replace(_P, "")
                linhas.append({"modelo": nome, "hiperparametro": chave, "valor": est[chave]})
    return pd.DataFrame(linhas)


def cv_repetida() -> RepeatedKFold:
    """5 particoes x 5 repeticoes, com semente diferente da usada na busca, para que a
    comparacao nao reaproveite exatamente as mesmas particoes do ajuste."""
    return RepeatedKFold(n_splits=N_PARTICOES, n_repeats=N_REPETICOES, random_state=SEMENTE + 1)


def comparar_estatisticamente(por_particao: pd.DataFrame, metrica: str = METRICA_SELECAO):
    """Compara cada par de modelos com o teste t pareado corrigido para reamostragem
    (Nadeau e Bengio, 2003; Bouckaert e Frank, 2004). As particoes da validacao
    cruzada compartilham dados de treino, entao a variancia da diferenca media e
    inflada por (1/k + n_validacao/n_treino) em vez de 1/k. Os valores-p dos pares
    sao ajustados pelo metodo de Holm. Os postos medios resumem a ordem dos modelos
    e sao apenas descritivos. Menor e melhor para MAPE, MAE e RMSE; maior para R2."""
    tabela = por_particao.pivot(index="particao", columns="modelo", values=metrica)
    menor_melhor = metrica != "R2"
    postos = tabela.rank(axis=1, ascending=menor_melhor).mean().sort_values()
    k = len(tabela)
    razao = 1 / (N_PARTICOES - 1)   # tamanho da validacao / tamanho do treino em cada particao

    linhas = []
    for a, b in itertools.combinations(postos.index, 2):   # a e o de melhor posto medio
        dif = tabela[a] - tabela[b]
        estat = dif.mean() / np.sqrt((1 / k + razao) * dif.var(ddof=1))
        linhas.append({
            "modelo_a": a, "modelo_b": b, "diferenca_media": dif.mean(), "t": estat,
            "p": 2 * t.sf(abs(estat), k - 1),
            "a_melhor_em": int((dif < 0).sum() if menor_melhor else (dif > 0).sum()), "particoes": k,
        })
    pares = pd.DataFrame(linhas).sort_values("p").reset_index(drop=True)

    # Holm: o i-esimo menor p e comparado com alfa / (m - i + 1); para no primeiro que falha
    m = len(pares)
    pares["limite_holm"] = ALFA / (m - pares.index)
    pares["p_holm"] = np.minimum(1, (pares["p"] * (m - pares.index)).cummax())
    pares["significativo"] = pares["p_holm"] <= ALFA
    return {"postos_medios": postos, "pares": pares}


def metricas(y_real, y_prev) -> dict:
    return {
        "MAE": mean_absolute_error(y_real, y_prev),
        "RMSE": root_mean_squared_error(y_real, y_prev),
        "R2": r2_score(y_real, y_prev),
        "MAPE": mean_absolute_percentage_error(y_real, y_prev) * 100,
    }


def avaliar_teste(modelos: dict, X_tr, y_tr, X_te, y_te):
    """Avaliacao final: cada modelo e treinado em todo o conjunto de treino e avaliado
    uma unica vez no conjunto de teste. Devolve as metricas e os modelos treinados."""
    treinados, linhas = {}, []
    for nome, modelo in modelos.items():
        m = clone(modelo).fit(X_tr, y_tr)
        treinados[nome] = m
        linhas.append({"modelo": nome, **metricas(y_te, m.predict(X_te))})
    return pd.DataFrame(linhas).set_index("modelo").sort_values(METRICA_SELECAO), treinados


def sensibilidade_lancamentos(modelos: dict, base_firme: pd.DataFrame, base_completa: pd.DataFrame):
    """Analise de sensibilidade dos anuncios 'A partir de'. O conjunto de teste e o
    mesmo da analise principal (so precos firmes); os lancamentos entram apenas no
    treino, com a marca preco_lancamento como variavel adicional. Compara o erro no
    teste com e sem eles, usando os mesmos hiperparametros."""
    X_tr, X_te, y_tr, y_te = dividir(base_firme)
    lanc = base_completa[base_completa["preco_lancamento"] == 1]
    cols = NUMERICAS + ["preco_lancamento"]
    X_tr_l = pd.concat([base_firme.loc[X_tr.index, cols + CATEGORICAS], lanc[cols + CATEGORICAS]])
    y_tr_l = pd.concat([y_tr, lanc["preco"]])
    X_te_l = base_firme.loc[X_te.index, cols + CATEGORICAS]

    linhas = []
    for nome, modelo in modelos.items():
        sem = clone(modelo).fit(X_tr, y_tr)
        estimador = clone(modelo.regressor.named_steps["modelo"])
        com = com_alvo_em_log(estimador, numericas_cols=cols).fit(X_tr_l, y_tr_l)
        for rotulo, m, X in (("sem lançamentos", sem, X_te), ("com lançamentos", com, X_te_l)):
            linhas.append({"modelo": nome, "treino": rotulo, **metricas(y_te, m.predict(X))})
    return pd.DataFrame(linhas), len(lanc)


def importancia_permutacao(modelos: dict, X_te, y_te, n_repeticoes: int = 20) -> pd.DataFrame:
    """Importancia por permutacao no conjunto de teste, medida pelo aumento do MAPE
    (em pontos percentuais) quando a variavel e embaralhada. Funciona sobre as
    variaveis originais (o bairro conta como uma variavel so), entao e comparavel
    entre todos os modelos, inclusive a Regressao Linear."""
    linhas = []
    for nome, modelo in modelos.items():
        r = permutation_importance(modelo, X_te, y_te, scoring="neg_mean_absolute_percentage_error",
                                   n_repeats=n_repeticoes, random_state=SEMENTE, n_jobs=-1)
        for col, media, dp in zip(X_te.columns, r.importances_mean, r.importances_std):
            linhas.append({"modelo": nome, "variavel": col,
                           "aumento_MAPE_pp": media * 100, "dp_pp": dp * 100})
    return pd.DataFrame(linhas)


def valores_shap(modelo: TransformedTargetRegressor, X: pd.DataFrame):
    """Valores SHAP (TreeExplainer) de um modelo de arvore ja treinado. As
    contribuicoes estao na escala do log(preco). Devolve a matriz SHAP, os dados
    transformados e um resumo por variavel original (colunas one-hot do mesmo bairro
    e a indicadora de ausencia sao somadas a variavel de origem)."""
    import shap

    pipe = modelo.regressor_
    Xt = pd.DataFrame(pipe.named_steps["prep"].transform(X),
                      columns=pipe.named_steps["prep"].get_feature_names_out(), index=X.index)
    valores = shap.TreeExplainer(pipe.named_steps["modelo"]).shap_values(Xt)

    def origem(coluna: str) -> str:
        nome = coluna.split("__", 1)[1].replace("missingindicator_", "")
        for c in CATEGORICAS:
            if nome.startswith(c + "_"):
                return c
        return nome

    por_coluna = pd.Series(np.abs(valores).mean(axis=0), index=Xt.columns)
    resumo = por_coluna.groupby(por_coluna.index.map(origem)).sum().sort_values(ascending=False)
    return valores, Xt, resumo


def salvar_modelos(modelos: dict, pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, modelo in modelos.items():
        joblib.dump(modelo, pasta / (nome.lower().replace(" ", "_").replace("ã", "a") + ".joblib"))


def avaliar_cv(modelos: dict, X, y, cv=None, grupos=None) -> pd.DataFrame:
    """Validacao cruzada de cada modelo. Devolve uma linha por (modelo, particao),
    com as metricas em R$ (MAPE em %)."""
    cv = cv or KFold(N_PARTICOES, shuffle=True, random_state=SEMENTE)
    linhas = []
    for nome, modelo in modelos.items():
        r = cross_validate(modelo, X, y, cv=cv, groups=grupos, scoring=METRICAS, n_jobs=1)
        for i in range(len(r["fit_time"])):
            linhas.append({
                "modelo": nome, "particao": i + 1,
                "MAE": -r["test_MAE"][i], "RMSE": -r["test_RMSE"][i], "R2": r["test_R2"][i],
                "MAPE": -r["test_MAPE"][i] * 100, "tempo_s": r["fit_time"][i],
            })
    return pd.DataFrame(linhas)


def resumir(por_particao: pd.DataFrame) -> pd.DataFrame:
    """Media e desvio padrao por modelo, ordenado pelo MAPE medio."""
    agg = por_particao.groupby("modelo")[["MAE", "RMSE", "R2", "MAPE", "tempo_s"]].agg(["mean", "std"])
    return agg.sort_values(("MAPE", "mean"))


def grupos_por_predio(base: pd.DataFrame, indices) -> np.ndarray:
    """Identificador do edificio: a coordenada original do anuncio. Anuncios com
    coordenada imputada (mediana do bairro) ficam cada um no seu proprio grupo."""
    b = base.loc[indices]
    coord = b["latitude"].round(5).astype(str) + "," + b["longitude"].round(5).astype(str)
    return np.where(b["geo_imputada"] == 0, coord, "anuncio_" + b["id"].astype(str))

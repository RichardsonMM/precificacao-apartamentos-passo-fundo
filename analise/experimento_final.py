"""
Experimento final: ajuste de hiperparametros, comparacao estatistica, avaliacao
no teste, sensibilidade aos lancamentos e importancia das variaveis.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Etapas (Secoes 3.2.4, 3.2.5 e 3.3 do artigo):
1. Busca aleatoria de hiperparametros dos quatro modelos de arvore (50
   combinacoes cada, validacao cruzada de 5 particoes no treino).
2. Validacao cruzada repetida (5 x 5) dos cinco modelos, com os hiperparametros
   padrao e com os ajustados; teste t corrigido (Nadeau e Bengio) em cada par de
   modelos, com correcao de Holm; validacao agrupada por predio.
3. Avaliacao unica no conjunto de teste (30%), com os modelos ajustados.
4. Sensibilidade: mesmo teste, com os anuncios "A partir de" incluidos no treino.
5. Importancia por permutacao (todos os modelos) e SHAP (melhor modelo de arvore).

Uso:
    python analise/experimento_final.py
Entrada:
    dados/dataset_modelagem.csv
Saidas (dados/resultados/):
    busca_hiperparametros.csv, melhores_hiperparametros.csv
    cv_repetida_por_particao.csv, cv_repetida_resumo.csv, comparacao_pares.csv, cv_agrupada_predio.csv
    teste_metricas.csv, sensibilidade_lancamentos.csv
    importancia_permutacao.csv, shap_resumo.csv
    experimento_resumo.json, modelos/*.joblib
"""

import json
import time
import warnings

import pandas as pd
from sklearn.model_selection import GroupKFold

import modelagem as m

warnings.filterwarnings("ignore", category=UserWarning)


def etapa(texto: str) -> None:
    print(f"\n[{time.strftime('%H:%M:%S')}] {texto}", flush=True)


def resumo_cv(por_particao: pd.DataFrame, rotulo: str) -> pd.DataFrame:
    r = m.resumir(por_particao)
    r.columns = [f"{a}_{b}" for a, b in r.columns]
    return r.assign(configuracao=rotulo)


def main() -> None:
    out = m.RESULTADOS
    out.mkdir(parents=True, exist_ok=True)
    inicio = time.time()

    base = m.carregar_base(incluir_lancamentos=False)
    X_tr, X_te, y_tr, y_te = m.dividir(base)
    print(f"Base: {len(base)} anuncios com preco firme | treino {len(X_tr)} | teste {len(X_te)}")

    etapa("1/5 Busca aleatoria de hiperparametros")
    padrao = m.modelos_referencia()
    ajustados, historico = m.ajustar_hiperparametros(padrao, X_tr, y_tr)
    historico.to_csv(out / "busca_hiperparametros.csv", index=False, encoding="utf-8-sig")
    melhores = m.melhores_hiperparametros(ajustados)
    melhores.to_csv(out / "melhores_hiperparametros.csv", index=False, encoding="utf-8-sig")
    print(melhores.to_string(index=False))

    etapa("2/5 Validacao cruzada repetida (5 x 5) e testes estatisticos")
    cv_padrao = m.avaliar_cv(padrao, X_tr, y_tr, cv=m.cv_repetida())
    cv_ajust = m.avaliar_cv(ajustados, X_tr, y_tr, cv=m.cv_repetida())
    pd.concat([cv_padrao.assign(configuracao="padrao"), cv_ajust.assign(configuracao="ajustado")]) \
        .to_csv(out / "cv_repetida_por_particao.csv", index=False, encoding="utf-8-sig")
    resumo = pd.concat([resumo_cv(cv_padrao, "padrao"), resumo_cv(cv_ajust, "ajustado")])
    resumo.to_csv(out / "cv_repetida_resumo.csv", encoding="utf-8-sig")
    print(resumo_cv(cv_ajust, "ajustado")[["MAPE_mean", "MAPE_std", "R2_mean", "RMSE_mean"]].to_string())

    comp = m.comparar_estatisticamente(cv_ajust)
    comp["pares"].to_csv(out / "comparacao_pares.csv", index=False, encoding="utf-8-sig")
    print("Postos medios (MAPE, descritivo):", comp["postos_medios"].round(2).to_dict())
    print("Teste t corrigido + Holm (MAPE):")
    print(comp["pares"][["modelo_a", "modelo_b", "diferenca_media", "p", "p_holm",
                         "significativo", "a_melhor_em"]].round(4).to_string(index=False))

    # Robustez: unidades do mesmo predio ficam sempre na mesma particao
    grupos = m.grupos_por_predio(base, X_tr.index)
    cv_predio = m.avaliar_cv(ajustados, X_tr, y_tr, cv=GroupKFold(m.N_PARTICOES), grupos=grupos)
    cv_predio.to_csv(out / "cv_agrupada_predio.csv", index=False, encoding="utf-8-sig")
    print(f"Validacao agrupada por predio ({len(set(grupos))} predios):")
    print(m.resumir(cv_predio)[[("MAPE", "mean"), ("R2", "mean")]].round(3).to_string())

    etapa("3/5 Avaliacao no conjunto de teste")
    teste, treinados = m.avaliar_teste(ajustados, X_tr, y_tr, X_te, y_te)
    teste.to_csv(out / "teste_metricas.csv", encoding="utf-8-sig")
    print(teste.round(3).to_string())
    m.salvar_modelos(treinados, out / "modelos")

    etapa("4/5 Sensibilidade aos anuncios 'A partir de'")
    sens, n_lanc = m.sensibilidade_lancamentos(ajustados, base, m.carregar_base(incluir_lancamentos=True))
    sens.to_csv(out / "sensibilidade_lancamentos.csv", index=False, encoding="utf-8-sig")
    print(f"{n_lanc} lancamentos adicionados ao treino")
    print(sens.pivot(index="modelo", columns="treino", values="MAPE").round(2).to_string())

    etapa("5/5 Importancia das variaveis")
    perm = m.importancia_permutacao(treinados, X_te, y_te)
    perm.to_csv(out / "importancia_permutacao.csv", index=False, encoding="utf-8-sig")
    melhor_arvore = next(n for n in teste.index if n in m.ESPACOS_BUSCA)
    _, _, shap_resumo = m.valores_shap(treinados[melhor_arvore], X_te)
    shap_resumo.rename("media_abs_shap").to_csv(out / "shap_resumo.csv", encoding="utf-8-sig")
    print(f"SHAP ({melhor_arvore}), 10 principais:\n", shap_resumo.head(10).round(4).to_string())

    with open(out / "experimento_resumo.json", "w", encoding="utf-8") as f:
        json.dump({
            "n_base": len(base), "n_treino": len(X_tr), "n_teste": len(X_te),
            "n_lancamentos_sensibilidade": n_lanc,
            "busca": {"n_iteracoes": m.N_ITERACOES_BUSCA, "particoes": m.N_PARTICOES,
                      "criterio": m.METRICA_SELECAO},
            "cv_repetida": {"particoes": m.N_PARTICOES, "repeticoes": m.N_REPETICOES},
            "postos_medios": comp["postos_medios"].to_dict(),
            "pares_significativos_holm": comp["pares"].loc[comp["pares"]["significativo"],
                                                           ["modelo_a", "modelo_b"]].values.tolist(),
            "melhor_modelo_teste": teste.index[0], "melhor_arvore_shap": melhor_arvore,
            "duracao_min": round((time.time() - inicio) / 60, 1),
        }, f, ensure_ascii=False, indent=2)
    etapa(f"Concluido em {(time.time() - inicio) / 60:.1f} min. Resultados em {out}")


if __name__ == "__main__":
    main()

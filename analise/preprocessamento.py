"""
Pre-processamento da base bruta: da coleta a base limpa.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Aplica apenas transformacoes POR REGISTRO, que nao dependem do conjunto de
treino: exclusoes da revisao manual, correcao de valores de preenchimento,
inferencia de campos ausentes a partir do proprio anuncio e padronizacao de
categorias. Imputacao estatistica (mediana/moda), escalonamento e one-hot
encoding ficam no pipeline de modelagem, ajustados so no treino, para evitar
vazamento de informacao do conjunto de teste.

Uso:
    python analise/preprocessamento.py
Entradas:
    dados/dataset_bruto.csv
    dados/revisao/revisao_manual.csv
Saidas:
    dados/dataset_limpo.csv
    dados/funil_preprocessamento.csv   registros removidos por etapa (tabela do artigo)
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "analise"))
from gerar_planilha_revisao import sugerir_bairros  # noqa: E402

ENTRADA = RAIZ / "dados" / "dataset_bruto.csv"
REVISAO = RAIZ / "dados" / "revisao" / "revisao_manual.csv"
SAIDA = RAIZ / "dados" / "dataset_limpo.csv"
FUNIL = RAIZ / "dados" / "funil_preprocessamento.csv"

DATA_COLETA = pd.Timestamp("2026-08-23")

VALOR_PREENCHIMENTO = 1.0   # condominio/IPTU <= R$ 1 sao placeholder do cadastro
AREA_MAX_STUDIO_M2 = 45     # sem dormitorio informado e ate essa area: studio/kitnet
K_VIZINHOS_BAIRRO = 5       # vizinhos usados para inferir bairro pela coordenada
MIN_ANUNCIOS_CENTROIDE = 3  # bairro precisa de N anuncios georreferenciados p/ centroide

NUMERO_POR_EXTENSO = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3, "quatro": 4}
RE_DORM_TITULO = re.compile(r"\b(\d|um|uma|dois|duas|tr[eê]s|quatro)\s+dorm", re.I)

MOBILIA_ORDINAL = {"Sem mobilia": 0, "Semimobiliado": 1, "Mobiliado": 2}

# Colunas que NAO podem ser preditoras: derivam do proprio preco, sao artefato
# da pagina, ou estao vazias na origem. Ficam fora da base limpa.
DESCARTAR = [
    "preco_card", "preco_anterior", "variacao_preco_pct", "teve_reducao_preco",   # derivam do preco
    "n_caracteres_html", "jsonld_presente", "registro_valido", "geo_origem",      # artefatos da coleta
    "andar", "comodos", "mobilia",                                                # vazias na origem
    "ano_construcao",                                                             # 82% ausente
    "area_total_m2", "area_nao_privativa_m2",                                     # inconsistentes; usa-se a privativa
    "amen_salao_jogos",                                                           # 1 ocorrencia
    "amen_mobiliado",                                                             # redundante com mobilia_ord
    "iptu",                                                                       # 90% ausente
    "corretor", "creci", "endereco", "slug", "destaques_texto",                   # identificacao/auditoria
    "propriedades_extras", "alertas_qualidade", "disponibilidade", "cidade", "uf", "rotulo_preco",
]


class Funil:
    """Registra quantos anuncios cada etapa remove."""

    def __init__(self, n_inicial: int):
        self.etapas = [("Base bruta (coleta de 23/08/2026)", 0, n_inicial)]

    def remover(self, df: pd.DataFrame, mascara: pd.Series, etapa: str) -> pd.DataFrame:
        restante = df[~mascara]
        self.etapas.append((etapa, int(mascara.sum()), len(restante)))
        return restante

    def tabela(self) -> pd.DataFrame:
        return pd.DataFrame(self.etapas, columns=["etapa", "removidos", "restantes"])


def contar(texto: pd.Series, padrao: str) -> pd.Series:
    return pd.to_numeric(texto.str.extract(padrao, flags=re.I)[0], errors="coerce")


def aplicar_revisao(df: pd.DataFrame, funil: Funil) -> pd.DataFrame:
    rev = pd.read_csv(REVISAO, encoding="utf-8-sig")
    excluir = rev[rev["decisao"] == "excluir"].drop_duplicates("id")
    for categoria, motivo in [
        ("falha_carga", "Anúncio retirado do portal durante a coleta"),
        ("nao_apartamento", "Não é apartamento (box, casa, imóvel misto)"),
        ("sem_preco", "Sem preço publicado"),
        ("area_suspeita", "Área privativa inválida ou não publicada"),
        ("duplicata", "Mesmo imóvel anunciado por outra imobiliária"),
    ]:
        ids = excluir.loc[excluir["categoria"] == categoria, "id"]
        df = funil.remover(df, df["id"].isin(ids), f"Revisão manual: {motivo.lower()}")

    for _, c in rev[rev["decisao"] == "corrigir"].iterrows():
        valor = c["valor_corrigido"] if pd.notna(c["valor_corrigido"]) else np.nan
        df.loc[df["id"] == c["id"], c["campo"]] = valor
    return df


def corrigir_valores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.loc[df["condominio"] <= VALOR_PREENCHIMENTO, "condominio"] = np.nan

    lista = df["amenidades_texto"].fillna("")
    titulo = df["titulo"].fillna("")

    # Suites: a ficha so exibe "(sendo N suites)" quando ha suite. Vazio com
    # dormitorios conhecidos e sem "Suite" na lista de caracteristicas = 0.
    sem_suite = df["suites"].isna() & df["dormitorios"].notna()
    cita_suite = lista.str.contains(r"\bSu[ií]te", case=False)
    df.loc[sem_suite & cita_suite, "suites"] = 1
    df.loc[sem_suite & ~cita_suite, "suites"] = 0

    # Lavabos e elevadores: mesma convencao da ficha (so aparecem quando existem).
    # Elevador vazio so vira 0 se a lista de caracteristicas tambem nao o cita.
    df["lavabos"] = df["lavabos"].fillna(0)
    df.loc[df["elevadores"].isna() & (df["amen_elevador"] == 0), "elevadores"] = 0

    # Vagas e banheiros: recupera da lista de caracteristicas ("Garagem p/ 2 Carros", "Banheiros (2)")
    df["vagas_garagem"] = df["vagas_garagem"].fillna(contar(lista, r"Garagem p/ (\d+) Carro"))
    df["banheiros"] = df["banheiros"].fillna(contar(lista, r"Banheiros ?\((\d+)\)"))

    # Dormitorios: primeiro pelo titulo ("TRES DORMITORIOS"); depois, studio/kitnet = 0
    no_titulo = titulo.str.extract(RE_DORM_TITULO)[0].str.lower()
    no_titulo = pd.to_numeric(no_titulo.replace(NUMERO_POR_EXTENSO), errors="coerce")
    df["dormitorios"] = df["dormitorios"].fillna(no_titulo)
    studio = df["dormitorios"].isna() & (df["area_util_m2"] <= AREA_MAX_STUDIO_M2)
    df.loc[studio, "dormitorios"] = 0
    df.loc[studio, "suites"] = df.loc[studio, "suites"].fillna(0)

    df["mobilia_ord"] = df["propriedades_extras"].str.extract(r"Mobília=([^|]+)")[0].str.strip().map(MOBILIA_ORDINAL)
    return df


def padronizar_bairro(df: pd.DataFrame, bruto: pd.DataFrame) -> pd.DataFrame:
    """Unifica grafias (caixa, acento, prefixo 'Bairro') e infere o bairro
    ausente pelos K anuncios georreferenciados mais proximos."""
    df = df.copy()
    de_para = sugerir_bairros(bruto).set_index("bairro_original")["sugestao"]
    df["bairro"] = df["bairro"].map(lambda b: de_para.get(b, b) if pd.notna(b) else np.nan)

    df["bairro_inferido"] = 0
    conhecidos = df.dropna(subset=["bairro", "latitude"])
    alvo = df["bairro"].isna() & df["latitude"].notna()
    for idx in df.index[alvo]:
        d = np.hypot(conhecidos["latitude"] - df.at[idx, "latitude"],
                     conhecidos["longitude"] - df.at[idx, "longitude"])
        vizinhos = conhecidos.loc[d.nsmallest(K_VIZINHOS_BAIRRO).index, "bairro"]
        df.at[idx, "bairro"] = vizinhos.mode().iloc[0]
        df.at[idx, "bairro_inferido"] = 1
    return df


def imputar_coordenadas(df: pd.DataFrame) -> pd.DataFrame:
    """Anuncio sem coordenada recebe o centroide do seu bairro. A marca
    geo_imputada permite medir o efeito disso na analise de sensibilidade."""
    df = df.copy()
    geo = df.dropna(subset=["latitude"])
    tamanho = geo.groupby("bairro").size()
    centroide = geo.groupby("bairro")[["latitude", "longitude"]].median()
    centroide = centroide[tamanho.reindex(centroide.index) >= MIN_ANUNCIOS_CENTROIDE]

    df["geo_imputada"] = 0
    alvo = df["latitude"].isna() & df["bairro"].isin(centroide.index)
    df.loc[alvo, "latitude"] = df.loc[alvo, "bairro"].map(centroide["latitude"])
    df.loc[alvo, "longitude"] = df.loc[alvo, "bairro"].map(centroide["longitude"])
    df.loc[alvo, "geo_imputada"] = 1
    return df


def derivar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    badges = df["badges"].fillna("")
    df["preco_lancamento"] = (df["rotulo_preco"] == "A partir de").astype(int)
    df["na_planta"] = (badges.str.contains("Em construcao|Lancamento") | df["previsao_entrega"].notna()).astype(int)
    df["preco_m2"] = (df["preco"] / df["area_util_m2"]).round(2)
    publicado = pd.to_datetime(df["data_publicacao"], errors="coerce")
    df["dias_anunciado"] = (DATA_COLETA - publicado).dt.days
    return df.drop(columns=["badges", "previsao_entrega", "data_publicacao", "amenidades_texto"])


def main():
    bruto = pd.read_csv(ENTRADA, encoding="utf-8-sig")
    df = bruto.copy()
    df.insert(0, "id", np.arange(1, len(df) + 1))   # mesmo id da planilha de revisao
    funil = Funil(len(df))

    df = aplicar_revisao(df, funil)
    df = funil.remover(df, df["preco"].isna(), "Sem preço (restantes)")
    df = funil.remover(df, df["area_util_m2"].isna(), "Sem área privativa (restantes)")

    df = corrigir_valores(df)
    df = padronizar_bairro(df, bruto)
    df = imputar_coordenadas(df)
    df = derivar(df)
    df = df.drop(columns=[c for c in DESCARTAR if c in df.columns])

    df.to_csv(SAIDA, index=False, encoding="utf-8-sig")
    tabela = funil.tabela()
    tabela.to_csv(FUNIL, index=False, encoding="utf-8-sig")

    print(tabela.to_string(index=False))
    print(f"\nBase limpa: {len(df)} registros x {df.shape[1]} colunas -> {SAIDA.relative_to(RAIZ)}")
    print(f"  preço 'a partir de' (decisão pendente): {df['preco_lancamento'].sum()}")
    print(f"  bairro inferido pela coordenada: {df['bairro_inferido'].sum()}  | ainda sem bairro: {df['bairro'].isna().sum()}")
    print(f"  coordenada imputada (centroide do bairro): {df['geo_imputada'].sum()}  | ainda sem coordenada: {df['latitude'].isna().sum()}")
    print("\nAusentes que ficam para a imputação no pipeline de modelagem:")
    ausentes = df.isna().sum()
    print(ausentes[ausentes > 0].sort_values(ascending=False).to_string())


if __name__ == "__main__":
    main()

"""
Gera a planilha de revisao manual da base bruta.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

Nao altera nem exclui nenhum registro: apenas marca os casos suspeitos,
agrupa-os por tipo de problema e deixa colunas de decisao para preenchimento
manual. As regras de marcacao estao todas neste arquivo, para que a revisao
seja reproduzivel e citavel no texto do trabalho.

Uso:
    python analise/gerar_planilha_revisao.py
Saida:
    dados/revisao/planilha_revisao.xlsx
"""

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "dados" / "dataset_bruto.csv"
SAIDA = RAIZ / "dados" / "revisao" / "planilha_revisao.xlsx"

# ---------------------------------------------------------------------------
# Limiares das regras de marcacao. Sao criterios de SUSPEITA, nao de exclusao:
# tudo o que eles pegam passa por revisao manual antes de qualquer decisao.
# ---------------------------------------------------------------------------
AREA_MIN_APTO_M2 = 20          # abaixo disso, area incompativel com apto com dormitorio
PRECO_M2_MIN = 3_000           # ~percentil 1 da base
PRECO_M2_MAX = 20_000          # ~percentil 99 da base
CONDOMINIO_PLACEHOLDER = 1.0   # valores <= R$ 1 sao preenchimento, nao taxa real

# Titulos que indicam outro tipo de imovel. "CASA" so no inicio do titulo, e
# com excecao dos edificios cujo nome contem "Casa" (Casa Alba, Casa Mirone...).
RE_BOX = re.compile(r"^\s*BOX\b", re.I)
RE_CASA = re.compile(r"^\s*CASA\b(?!\s+(?:ALBA|MIRONE|BELGA)\b)", re.I)
RE_COMERCIAL = re.compile(r"PR[EÉ]DIO\s+COMERCIAL|\bLOJAS?\b", re.I)
RE_OUTRA_CIDADE = re.compile(r"ARROIO DO SAL", re.I)
# Paginas que nao carregaram ficam com o titulo generico do portal
# ("... | Encontre seu imovel em Passo Fundo", "Meus favoritos - ..."). Na base
# publicada, o nome do portal nesses titulos foi substituido por "Portal imobiliário".
TITULO_FALHA_CARGA = "Portal imobiliário"

# Rotulo das suspeitas, na ordem em que aparecem na planilha
SUSPEITAS = {
    "falha_carga": "Página não carregou (sem JSON-LD, título genérico)",
    "nao_apartamento": "Título indica box, casa, prédio comercial ou outra cidade",
    "sem_preco": "Anúncio sem preço",
    "area_suspeita": f"Área útil ausente ou < {AREA_MIN_APTO_M2} m² com dormitório",
    "preco_m2_suspeito": f"Preço/m² fora de R$ {PRECO_M2_MIN:,} – R$ {PRECO_M2_MAX:,}".replace(",", "."),
    "duplicata": "Mesmo preço, área e dormitórios de outro anúncio",
    "mesma_planta": "Mesmo prédio (coordenada), área e dormitórios, preço diferente",
    "preco_a_partir_de": "Preço de lançamento (\"A partir de\")",
    "condominio_placeholder": f"Condomínio ≤ R$ {CONDOMINIO_PLACEHOLDER:.0f} (valor de preenchimento)",
    "bairro_revisar": "Bairro ausente, grafia fora do padrão ou com menos de 3 anúncios",
}


def sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def chave_bairro(nome) -> str:
    if pd.isna(nome):
        return ""
    k = sem_acento(str(nome)).lower().strip()
    k = re.sub(r"^bairro\s+", "", k)
    return re.sub(r"\s+", " ", k)


def sugerir_bairros(df: pd.DataFrame) -> pd.DataFrame:
    """Agrupa grafias equivalentes (caixa, acento, prefixo 'Bairro') e sugere
    a forma mais frequente como canonica. Grafias raras sem equivalente ficam
    marcadas para revisao."""
    cont = df["bairro"].value_counts()
    tab = pd.DataFrame({"bairro_original": cont.index, "anuncios": cont.values})
    tab["chave"] = tab["bairro_original"].map(chave_bairro)
    # Em empate, prefere a grafia sem o prefixo "Bairro" ("Cruzeiro", nao "Bairro Cruzeiro")
    tab["_prefixo"] = tab["bairro_original"].str.lower().str.startswith("bairro ")
    canonico = (tab.sort_values(["anuncios", "_prefixo"], ascending=[False, True])
                   .drop_duplicates("chave").set_index("chave")["bairro_original"])
    tab = tab.drop(columns="_prefixo")
    total_chave = tab.groupby("chave")["anuncios"].sum()
    tab["sugestao"] = tab["chave"].map(canonico)
    tab["revisar"] = (tab["bairro_original"] != tab["sugestao"]) | (tab["chave"].map(total_chave) < 3)
    return tab.drop(columns="chave").sort_values(["revisar", "anuncios"], ascending=[False, False])


def marcar(df: pd.DataFrame, bairros: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.insert(0, "id", np.arange(1, len(df) + 1))
    df["preco_m2"] = (df["preco"] / df["area_util_m2"]).round(0)
    titulo = df["titulo"].fillna("")
    alertas = df["alertas_qualidade"].fillna("")

    m = {}
    m["falha_carga"] = (df["jsonld_presente"] == 0) & titulo.str.contains(TITULO_FALHA_CARGA, regex=False)
    m["nao_apartamento"] = (titulo.str.contains(RE_BOX) | titulo.str.contains(RE_CASA)
                            | titulo.str.contains(RE_COMERCIAL) | titulo.str.contains(RE_OUTRA_CIDADE))
    m["sem_preco"] = df["preco"].isna() & ~m["falha_carga"]
    m["area_suspeita"] = (df["area_util_m2"].isna()
                          | ((df["area_util_m2"] < AREA_MIN_APTO_M2) & df["dormitorios"].notna())) & ~m["falha_carga"]
    m["preco_m2_suspeito"] = (df["preco_m2"] < PRECO_M2_MIN) | (df["preco_m2"] > PRECO_M2_MAX)

    # Duplicatas: mesmo preco, area e dormitorios. Cada grupo ganha um numero
    # para que os anuncios irmaos aparecam lado a lado.
    chave_dup = ["preco", "area_util_m2", "dormitorios"]
    validos = df.dropna(subset=["preco", "area_util_m2"])
    dup = validos[validos.duplicated(subset=chave_dup, keep=False)]
    grupos = dup.groupby(chave_dup, dropna=False).ngroup() + 1
    df["grupo_duplicata"] = grupos.reindex(df.index)
    m["duplicata"] = df["grupo_duplicata"].notna()

    # Mesma planta no mesmo predio com preco diferente: nao e duplicata, mas
    # mostra unidades quase identicas que podem cair em treino e teste.
    chave_planta = ["latitude", "longitude", "area_util_m2", "dormitorios"]
    geo = df.dropna(subset=["latitude", "area_util_m2"])
    planta = geo[geo.duplicated(subset=chave_planta, keep=False)]
    grupos_planta = planta.groupby(chave_planta, dropna=False).ngroup() + 1
    df["grupo_mesma_planta"] = grupos_planta.reindex(df.index)
    m["mesma_planta"] = df["grupo_mesma_planta"].notna() & ~m["duplicata"]

    m["preco_a_partir_de"] = alertas.str.contains("preco_a_partir_de")
    m["condominio_placeholder"] = df["condominio"] <= CONDOMINIO_PLACEHOLDER

    revisar = set(bairros.loc[bairros["revisar"], "bairro_original"])
    df["bairro_sugerido"] = df["bairro"].map(bairros.set_index("bairro_original")["sugestao"])
    m["bairro_revisar"] = (df["bairro"].isna() | df["bairro"].isin(revisar)) & ~m["falha_carga"]

    for nome, mascara in m.items():
        df["_" + nome] = mascara.fillna(False).astype(bool)
    df["suspeitas"] = df.apply(
        lambda r: "; ".join(n for n in SUSPEITAS if r["_" + n]), axis=1)
    df["n_suspeitas"] = df[["_" + n for n in SUSPEITAS]].sum(axis=1)
    return df


# ---------------------------------------------------------------------------
# Escrita da planilha
# ---------------------------------------------------------------------------
FONTE = "Arial"
CAB_FILL = PatternFill("solid", fgColor="1F3864")
EDIT_FILL = PatternFill("solid", fgColor="FFF2CC")   # colunas para preencher
CAB_FONT = Font(name=FONTE, bold=True, color="FFFFFF")
BASE_FONT = Font(name=FONTE, size=10)
LINK_FONT = Font(name=FONTE, size=10, color="0563C1", underline="single")

COLUNAS_VISAO = [
    "id", "suspeitas", "titulo", "preco", "area_util_m2", "preco_m2", "dormitorios",
    "suites", "banheiros", "vagas_garagem", "condominio", "bairro", "bairro_sugerido",
    "imobiliaria_origem", "codigo_imovel", "rotulo_preco", "badges",
    "grupo_duplicata", "grupo_mesma_planta", "latitude", "longitude",
    "alertas_qualidade", "url",
]
COLUNAS_DECISAO = ["decisao", "observacao"]
OPCOES_DECISAO = "manter,excluir,corrigir"

FORMATOS = {
    "preco": "#,##0", "preco_m2": "#,##0", "condominio": "#,##0.00",
    "area_util_m2": "#,##0.00", "latitude": "0.000000", "longitude": "0.000000",
}
LARGURAS = {
    "id": 6, "suspeitas": 34, "titulo": 44, "preco": 12, "area_util_m2": 10,
    "preco_m2": 10, "bairro": 18, "bairro_sugerido": 18, "imobiliaria_origem": 28,
    "badges": 24, "alertas_qualidade": 30, "url": 60, "decisao": 11, "observacao": 36,
}


def escrever_tabela(ws, df: pd.DataFrame, colunas, com_decisao: bool):
    cols = (COLUNAS_DECISAO if com_decisao else []) + list(colunas)
    for j, nome in enumerate(cols, 1):
        c = ws.cell(row=1, column=j, value=nome)
        c.font, c.fill = CAB_FONT, CAB_FILL
        c.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(j)].width = LARGURAS.get(nome, 11)

    for i, (_, reg) in enumerate(df.iterrows(), 2):
        for j, nome in enumerate(cols, 1):
            valor = None if nome in COLUNAS_DECISAO else reg[nome]
            if isinstance(valor, float) and np.isnan(valor):
                valor = None
            elif isinstance(valor, (np.integer, np.floating)):
                valor = valor.item()
            c = ws.cell(row=i, column=j, value=valor)
            c.font = BASE_FONT
            if nome in FORMATOS:
                c.number_format = FORMATOS[nome]
            if nome in COLUNAS_DECISAO:
                c.fill = EDIT_FILL
            if nome == "url" and str(valor).startswith("http"):
                c.hyperlink, c.font = valor, LINK_FONT

    ws.freeze_panes = ws.cell(row=2, column=(len(COLUNAS_DECISAO) + 3) if com_decisao else 3)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(len(df) + 1, 2)}"
    if com_decisao and len(df):
        dv = DataValidation(type="list", formula1=f'"{OPCOES_DECISAO}"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"A2:A{len(df) + 1}")


def escrever_leiame(ws):
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 95
    linhas = [
        ("Planilha de revisão da base bruta", None),
        (None, None),
        ("Origem", "dados/dataset_bruto.csv — 1 linha por anúncio (coleta de 23/08/2026)."),
        ("Gerada por", "analise/gerar_planilha_revisao.py — as regras de marcação estão no início do script."),
        ("O que é", "Nenhum registro foi alterado ou excluído. A planilha só MARCA casos suspeitos para análise."),
        (None, None),
        ("Abas", None),
        ("Resumo", "Quantos registros caem em cada suspeita."),
        ("Todos", "Os 1.219 registros, com a coluna 'suspeitas'. Use o filtro para navegar."),
        ("Abas temáticas", "Uma por tipo de problema, já ordenadas para facilitar a comparação "
                           "(duplicatas lado a lado pelo número do grupo)."),
        ("Bairros", "Grafias de bairro encontradas e a forma padronizada sugerida."),
        (None, None),
        ("Colunas a preencher", "Células em amarelo. Preencha nas abas temáticas e em 'Bairros'."),
        ("decisao", "manter | excluir | corrigir (lista suspensa). Em branco = ainda não revisado."),
        ("observacao", "Motivo da decisão, ou o valor correto quando a decisão for 'corrigir'."),
        ("Exemplo", "decisao = excluir · observacao = \"box de garagem, não é apartamento\""),
        (None, None),
        ("Dica", "Ao comparar duplicatas, abra as URLs: se for o mesmo imóvel anunciado por duas "
                 "imobiliárias, mantenha um e exclua o outro; se forem unidades diferentes do mesmo "
                 "prédio, mantenha ambos."),
    ]
    for i, (a, b) in enumerate(linhas, 1):
        ca, cb = ws.cell(row=i, column=1, value=a), ws.cell(row=i, column=2, value=b)
        ca.font = Font(name=FONTE, bold=True, size=14 if i == 1 else 10)
        cb.font = BASE_FONT
        cb.alignment = Alignment(wrap_text=True, vertical="top")
    ws.cell(row=16, column=2).fill = EDIT_FILL


def escrever_resumo(ws, n_total: int):
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 62
    ws.column_dimensions["C"].width = 12
    for j, nome in enumerate(["suspeita", "descrição", "anúncios"], 1):
        c = ws.cell(row=1, column=j, value=nome)
        c.font, c.fill = CAB_FONT, CAB_FILL
    ultima = n_total + 1
    for i, (nome, desc) in enumerate(SUSPEITAS.items(), 2):
        ws.cell(row=i, column=1, value=nome).font = BASE_FONT
        ws.cell(row=i, column=2, value=desc).font = BASE_FONT
        ws.cell(row=i, column=3,
                value=f'=COUNTIF(Todos!$B$2:$B${ultima},"*{nome}*")').font = BASE_FONT
    i = len(SUSPEITAS) + 3
    ws.cell(row=i, column=1, value="sem nenhuma suspeita").font = Font(name=FONTE, bold=True)
    ws.cell(row=i, column=3, value=f'=COUNTBLANK(Todos!$B$2:$B${ultima})').font = Font(name=FONTE, bold=True)
    ws.cell(row=i + 1, column=1, value="total de registros").font = Font(name=FONTE, bold=True)
    ws.cell(row=i + 1, column=3, value=f"=COUNTA(Todos!$A$2:$A${ultima})").font = Font(name=FONTE, bold=True)
    ws.cell(row=i + 3, column=1,
            value="Um anúncio pode ter mais de uma suspeita, por isso as linhas não somam o total.").font = \
        Font(name=FONTE, italic=True, size=9)


ABAS_TEMATICAS = [
    ("Falha_carga", "falha_carga", ["id"]),
    ("Nao_apartamento", "nao_apartamento", ["preco"]),
    ("Duplicatas", "duplicata", ["grupo_duplicata", "id"]),
    ("Mesma_planta", "mesma_planta", ["grupo_mesma_planta", "preco"]),
    ("Area_e_preco_m2", None, ["preco_m2"]),
    ("A_partir_de", "preco_a_partir_de", ["titulo"]),
    ("Condominio", "condominio_placeholder", ["id"]),
    ("Sem_preco", "sem_preco", ["id"]),
]


def main():
    bruto = pd.read_csv(ENTRADA, encoding="utf-8-sig")
    bairros = sugerir_bairros(bruto)
    df = marcar(bruto, bairros)

    wb = Workbook()
    escrever_leiame(wb.active)
    wb.active.title = "Leia-me"
    escrever_resumo(wb.create_sheet("Resumo"), len(df))

    todos = df.assign(suspeitas=df["suspeitas"].replace("", None))
    escrever_tabela(wb.create_sheet("Todos"), todos, COLUNAS_VISAO, com_decisao=False)

    for aba, flag, ordem in ABAS_TEMATICAS:
        if flag is None:   # area e preco/m2 juntos: costumam ser o mesmo erro
            sel = df[df["_area_suspeita"] | df["_preco_m2_suspeito"]]
        else:
            sel = df[df["_" + flag]]
        escrever_tabela(wb.create_sheet(aba), sel.sort_values(ordem), COLUNAS_VISAO, com_decisao=True)

    ws = wb.create_sheet("Bairros")
    escrever_tabela(ws, bairros.assign(revisar=bairros["revisar"].map({True: "sim", False: ""})),
                    ["bairro_original", "anuncios", "sugestao", "revisar"], com_decisao=True)
    sem_bairro = int(df["bairro"].isna().sum())
    ws.cell(row=len(bairros) + 3, column=3,
            value=f"Além destes, {sem_bairro} anúncios estão sem bairro (ver aba Todos, filtro 'bairro_revisar').").font = \
        Font(name=FONTE, italic=True, size=9)

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    wb.save(SAIDA)

    print(f"Planilha gravada em {SAIDA.relative_to(RAIZ)}")
    for nome in SUSPEITAS:
        print(f"  {nome:<24}{int(df['_' + nome].sum()):>5}")
    print(f"  {'sem nenhuma suspeita':<24}{int((df['n_suspeitas'] == 0).sum()):>5}")


if __name__ == "__main__":
    main()

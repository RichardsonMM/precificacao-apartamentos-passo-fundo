# Precificação de apartamentos em Passo Fundo com aprendizado de máquina

Código e dados do Trabalho de Conclusão de Curso *Precificação de imóveis com
aprendizado de máquina: um estudo aplicado ao mercado de apartamentos de Passo
Fundo*, do curso de Ciência da Computação da Universidade de Passo Fundo (2026).

**Autor:** Richardson Patrick Matos De Moraes
**Orientador:** Prof. Carlos Amaral Holbig

O trabalho compara Regressão Linear Múltipla, Random Forest, Gradient Boosting
Regressor, XGBoost e LightGBM na predição do preço anunciado de apartamentos, a
partir de uma base própria de 1.219 anúncios coletados em 23/08/2026 em um portal
imobiliário regional e enriquecidos com distâncias a pontos de interesse.

## Estrutura

```
├── scraper/     coleta dos anúncios
├── analise/     pré-processamento, features, análise exploratória, modelagem e figuras
├── notebooks/   o mesmo pipeline em formato comentado, para execução no Google Colab
├── dados/       base de cada etapa, decisões da revisão manual e resultados
└── saidas/      figuras e tabelas do artigo
```

## Pipeline

| Etapa | Script | Saída |
|---|---|---|
| 1. Coleta | `scraper/run_scraper.py` | `dados/dataset_bruto.csv` |
| 2. Revisão manual | `analise/gerar_planilha_revisao.py`, `analise/conferir_anuncios.py` | `dados/revisao/revisao_manual.csv` |
| 3. Pré-processamento | `analise/preprocessamento.py` | `dados/dataset_limpo.csv`, `dados/funil_preprocessamento.csv` |
| 4. Engenharia de features | `analise/features.py` | `dados/dataset_modelagem.csv` |
| 5. Análise exploratória | `analise/eda.py` | `saidas/`, `dados/eda_resumo.json` |
| 6. Modelagem e avaliação | `analise/experimento_final.py` | `dados/resultados/` |
| 7. Figuras e tabelas | `analise/figuras_resultados.py`, `analise/analise_erros.py`, `analise/tabela_hiperparametros.py` | `saidas/` |

Na etapa 2, a planilha marca os anúncios suspeitos, cada um é conferido na página
original e a decisão (manter, excluir ou corrigir) é registrada, com motivo e
evidência, em `revisao_manual.csv`, que o pré-processamento aplica.

Da base bruta, o pré-processamento mantém 1.138 anúncios. Os 1.010 com preço firme
formam a base de modelagem, dividida em 707 anúncios de treino e 303 de teste.

## Como reproduzir

Requer Python 3.13.

```bash
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python analise/preprocessamento.py
python analise/features.py
python analise/eda.py
python analise/experimento_final.py
python analise/figuras_resultados.py
python analise/analise_erros.py
python analise/tabela_hiperparametros.py
```

A partir da etapa 3, tudo roda sobre os CSVs versionados, sem acesso à internet.
Os modelos treinados (`dados/resultados/modelos/`) não são versionados:
`experimento_final.py` os recria.

As etapas 1 e 2 acessam o portal. Elas exigem o navegador do Playwright
(`playwright install chromium`) e a variável de ambiente `PORTAL_URL` com o
endereço do portal, que não é versionado. O cache de HTML da coleta também não é
versionado.

## Dados

As colunas da base bruta estão descritas em
[`scraper/DICIONARIO_DE_DADOS.md`](scraper/DICIONARIO_DE_DADOS.md).

Para não identificar o portal, as imobiliárias e os corretores, a base publicada
difere da coletada em quatro pontos:

- `url` traz só o caminho da página, sem o domínio;
- `imobiliaria_origem` traz um código (`imobiliaria_01` a `imobiliaria_14`) no
  lugar do domínio da imobiliária;
- as colunas `corretor` e `creci` foram removidas;
- no título das páginas que não carregaram, o nome do portal foi trocado por
  "Portal imobiliário".

Nenhuma dessas colunas é usada como preditora, e os resultados não dependem delas.

Os dados foram coletados de páginas públicas, para fins acadêmicos, com pausa de
dois a três segundos entre as requisições.

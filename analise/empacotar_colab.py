"""
Empacota em um unico .zip tudo o que os notebooks precisam para rodar no Colab.

TCC - Precificacao de Imoveis com Aprendizado de Maquina
Mercado de apartamentos de Passo Fundo/RS

O painel de arquivos do Colab nao preserva pastas ao enviar arquivos soltos;
o notebook recebe este .zip e o extrai com a estrutura do repositorio.
Rode de novo sempre que a base ou os scripts mudarem.

Uso:
    python analise/empacotar_colab.py
Saida:
    notebooks/projeto_colab.zip
"""

import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "notebooks" / "projeto_colab.zip"

ARQUIVOS = [
    "scraper/config.py",
    "analise/gerar_planilha_revisao.py",
    "analise/preprocessamento.py",
    "analise/features.py",
    "analise/eda.py",
    "analise/modelagem.py",
    "analise/figuras_resultados.py",
    "dados/dataset_bruto.csv",
    "dados/revisao/revisao_manual.csv",
    "dados/dataset_limpo.csv",
    "dados/dataset_modelagem.csv",
    "dados/funil_preprocessamento.csv",
]


def main():
    SAIDA.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(SAIDA, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in ARQUIVOS:
            z.write(RAIZ / rel, arcname=rel)
    print(f"{len(ARQUIVOS)} arquivos -> {SAIDA.relative_to(RAIZ)} ({SAIDA.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()

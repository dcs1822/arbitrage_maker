"""
test_increment_3.py - Validacao do storage SQLite + estado por empresa.

Valida:
    1. Criacao do schema (4 tabelas)
    2. Inicializacao do company_state a partir do universo selecionado
    3. Leitura de uma empresa especifica (WEST3)
    4. Escrita em metadata, flags e teses (operacoes que o pipeline vai usar)
    5. Contagem final por tabela

Execucao:
    cd "P:\\Analise\\Trader\\Projetos\\Fato Relevante GPT"
    python -m corporate_events_v3.test_increment_3
"""
import sys

from . import config, universe_selector
from .state import db, company


def main() -> int:
    print("=" * 64)
    print("CORPORATE EVENTS V3 - INCREMENTO 3")
    print("Storage SQLite + estado por empresa")
    print("=" * 64)

    # === 1. Inicializar DB ===
    print("\n[1] Inicializando schema SQLite...")
    print(f"    Path: {config.DB_PATH}")
    db.init_db()
    counts = db.table_counts()
    print(f"    Tabelas criadas: {list(counts.keys())}")
    print(f"    Linhas atuais:   {counts}")

    # === 2. Popular company_state ===
    print("\n[2] Populando company_state com o universo do incremento 2...")
    selecionados = universe_selector.build_universe()
    n_inseridas = company.initialize_from_universe(selecionados)
    print(f"    {n_inseridas} empresas inseridas/atualizadas")

    # === 3. Listar tudo ===
    print("\n[3] Empresas em company_state:")
    todas = company.all_companies()
    for c in todas:
        ticker = c["ticker"] or "-"
        print(f"    {c['cd_cvm']:>6}  {c['fonte']:7}  {ticker:8}  {c['denom']}")

    # === 4. Operacoes que o pipeline vai usar ===
    print("\n[4] Testando operacoes de update (em WEST3)...")
    company.update_metadata(
        "25518",
        caixa_brl=120_000_000,
        divida_brl=10_000_000,
        market_cap_brl=80_000_000,
        free_float_pct=0.45,
    )
    company.set_flags(
        "25518",
        ["caixa_maior_que_mc", "free_float_baixo"],
    )
    company.set_teses(
        "25518",
        [
            {
                "tese": "Reducao de capital + caixa > MC",
                "abertura": "2026-01-15",
                "alvo": "OPA implicita ou retorno via reducao",
                "status": "monitorando",
            }
        ],
    )

    # Le de volta
    west = company.get_company("25518")
    print(f"    Denom:    {west['denom']}")
    print(f"    Ticker:   {west['ticker']}")
    print(f"    Fonte:    {west['fonte']}")
    print(f"    Metadata: {west['metadata']}")
    print(f"    Flags:    {west['flags']}")
    print(f"    Teses:    {len(west['teses'])} aberta(s)")
    for t in west["teses"]:
        print(f"      - {t['tese']} (status={t['status']})")

    # === 5. Contagem final ===
    print("\n[5] Contagem final por tabela:")
    counts = db.table_counts()
    for tbl, n in counts.items():
        print(f"    {tbl:15} {n:>5}")

    print("\n" + "=" * 64)
    print("Incremento 3 concluido.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())

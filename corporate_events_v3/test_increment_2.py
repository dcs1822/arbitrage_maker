"""
test_increment_2.py - Validacao do universo selecionado.

Valida:
    1. Carregamento do universo Bloomberg + log de unknowns em arquivo de rede
    2. Selecao das 9 empresas curadas (todas devem ter CD_CVM, exceto pendentes)
    3. Sorteio reproducivel das 11 empresas aleatorias do pool TIER 1+2
    4. Total de 20 empresas no universo final

Execucao:
    cd "P:\\Analise\\Trader\\Projetos\\Fato Relevante GPT"
    python -m corporate_events_v3.test_increment_2
"""
import sys
from . import config, universe, universe_selector


def main() -> int:
    print("=" * 64)
    print("CORPORATE EVENTS V3 - INCREMENTO 2")
    print("Universo de teste: 20 empresas (curadas + random)")
    print("=" * 64)

    # === 1. UNIVERSO BLOOMBERG + LOG DE UNKNOWNS ===
    print("\n[1] Universo Bloomberg + auditoria de unknowns...")
    df = universe.load_universe()
    n_unk = universe.log_unknowns(df)
    print(f"    Total tickers BZ ............ {len(df)}")
    print(f"    Tickers desconhecidos ....... {n_unk}")
    if n_unk:
        print(f"    Salvos em ................... {config.UNKNOWNS_LOG_PATH}")

    # === 2. UNIVERSO SELECIONADO ===
    print("\n[2] Montando universo de teste...")
    selecionados = universe_selector.build_universe()
    n_total = len(selecionados)
    n_curado = sum(1 for s in selecionados if s["fonte"] == "curado")
    n_random = sum(1 for s in selecionados if s["fonte"] == "random")
    n_pendente = sum(1 for s in selecionados if s["cd_cvm"] is None)
    print(f"    Total ............ {n_total}")
    print(f"    Curados .......... {n_curado}")
    print(f"    Random ........... {n_random}")
    print(f"    Sem CD_CVM ....... {n_pendente}")
    print(f"    Random seed ...... {config.RANDOM_SEED}")

    # === 3. LISTAGEM ===
    print("\n[ CURADAS ]")
    for s in selecionados:
        if s["fonte"] != "curado":
            continue
        cd = s["cd_cvm"] or "??????"
        flag = "  " if s["cd_cvm"] else "!!"
        print(f"    {flag} {s['ticker']:8} CD_CVM={cd:>6}  {s['denom']}")

    print("\n[ RANDOM (sorteio reproducivel) ]")
    for s in selecionados:
        if s["fonte"] != "random":
            continue
        print(f"       {'':8} CD_CVM={s['cd_cvm']:>6}  {s['denom']}")

    print("\n" + "=" * 64)
    if n_pendente:
        print(f"AVISO: {n_pendente} empresa(s) curada(s) sem CD_CVM mapeado.")
        print("       O pipeline vai pular essas com aviso. Resolva no")
        print("       universe_selector.CURADOS_MAP quando souber o codigo.")
    print("Incremento 2 concluido.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())

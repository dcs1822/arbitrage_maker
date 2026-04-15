"""
test_increment_1.py — Validação do incremento 1.

O que valida:
    1. Carregamento do universo Bloomberg → DataFrame enriquecido
    2. Estatísticas do universo (totais, distribuição por tipo)
    3. Conectividade com o provider LLM (Gemini), se a chave estiver setada

Execução (de qualquer lugar, usando o pai como root):
    cd "P:\\Analise\\Trader\\Projetos\\Fato Relevante GPT"
    python -m corporate_events_v3.test_increment_1
"""
import sys
from . import config, universe


def main() -> int:
    print("=" * 64)
    print("CORPORATE EVENTS V3 - INCREMENTO 1")
    print("=" * 64)

    # === 1. UNIVERSO ===
    print("\n[1] Carregando universo Bloomberg...")
    print(f"    Fonte: {config.BLOOMBERG_TICKERS_PATH}")
    if not config.BLOOMBERG_TICKERS_PATH.exists():
        print(f"    ERRO: arquivo não encontrado.")
        return 1

    df = universe.load_universe()
    summary = universe.universe_summary(df)

    print(f"    Total tickers BZ ................. {summary['total_tickers']}")
    print(f"    Roots distintos (~empresas) ...... {summary['roots_distintos']}")
    print(f"\n    Distribuicao por tipo de papel:")
    for tipo, n in sorted(summary["por_tipo"].items(), key=lambda x: -x[1]):
        print(f"      {tipo:25} {n:>5}")

    print(f"\n    Amostra ON (10 primeiros):")
    for _, r in df[df["tipo"] == "ON"].head(10).iterrows():
        print(f"      {r['ticker']:10} root={r['root']}")

    print(f"\n    Amostra Units/FIIs (10 primeiros):")
    for _, r in df[df["tipo"] == "UNIT_OU_FII"].head(10).iterrows():
        print(f"      {r['ticker']:10} root={r['root']}")

    # === 2. LLM PROVIDER ===
    print("\n[2] Testando provider LLM...")
    print(f"    Provider configurado: {config.LLM_PROVIDER}")
    print(f"    Modelo triagem: {config.LLM_TRIAGE[1]}")
    print(f"    Modelo analise: {config.LLM_DEEP[1]}")

    if not config.GEMINI_API_KEY:
        print("\n    GEMINI_API_KEY nao encontrada - pulando teste de chamada.")
        print("    Para configurar (PowerShell):")
        print('      setx GEMINI_API_KEY "sua-chave-aqui"')
        print("    Depois reabra o terminal e rode esse script de novo.")
    else:
        try:
            from . import llm_provider
            prov = llm_provider.get_provider()
            print("    Chamando triage()...")
            r = prov.triage("Responda com a única palavra: OK")
            print(f"    Resposta: {r[:200]!r}")
            print("    [OK] Gemini acessivel.")
        except Exception as e:
            print(f"    ERRO chamando Gemini: {e}")
            return 2

    print("\n" + "=" * 64)
    print("Incremento 1 concluido.")
    print("Proximo passo: incremento 2 (market cap + filtro R$ 1bi).")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())

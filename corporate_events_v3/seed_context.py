"""
seed_context.py - Script de seed para popular company_state.metadata
com dados conhecidos manualmente.

Esse script eh TEMPORARIO e vai ser substituido pelos screens do incremento 6.
Hoje serve apenas para demonstrar que a injecao de contexto no analyzer
funciona: injetar caixa > MC da Westwing para validar a flag cash_gt_mc_trigger
em caso de reducao de capital.

Execucao:
    python -m corporate_events_v3.seed_context
"""
from __future__ import annotations

from .state import company, db

# Dados conhecidos (valores aproximados, so para o teste do incremento 5).
# Em producao isso vem de um screen de dados de mercado (incremento 6).
SEED = {
    "25518": {  # Westwing
        "denom_hint": "WESTWING",
        "metadata": {
            "mc": "~R$ 80 milhoes",
            "caixa": "~R$ 120 milhoes",
            "divida": "baixa",
            "observacao": "cash > MC (net-net)",
        },
        "flags": ["cash_gt_mc"],
    },
    "22454": {  # T4F / SHOW3
        "denom_hint": "T4F",
        "metadata": {
            "mc": "~R$ 150 milhoes",
            "caixa": "~R$ 70 milhoes",
            "observacao": "caixa alto relativo ao MC",
        },
        "flags": [],
    },
    "15253": {  # Energisa
        "denom_hint": "ENERGISA",
        "metadata": {
            "mc": "~R$ 25 bilhoes",
            "estrutura_acoes": "ON + PN + Unit (ENGI3, ENGI4, ENGI11)",
            "observacao": "acompanhar arbitragem Units vs ON+PN",
        },
        "flags": ["units_watch"],
    },
    "24317": {  # ZAMP
        "denom_hint": "ZAMP",
        "metadata": {
            "observacao": "em processo de deslistagem / fechamento de capital",
        },
        "flags": ["deslistagem_em_curso"],
    },
}


def main() -> int:
    db.init_db()
    n = 0
    for cd, data in SEED.items():
        existing = company.get_company(cd)
        if existing is None:
            print(f"  [SKIP] {cd} nao existe em company_state")
            continue
        company.update_metadata(cd, **data["metadata"])
        if data.get("flags"):
            company.set_flags(cd, data["flags"])
        print(f"  [OK] {cd} {data['denom_hint']:12} flags={data['flags']}")
        n += 1
    print(f"\n{n} empresas atualizadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

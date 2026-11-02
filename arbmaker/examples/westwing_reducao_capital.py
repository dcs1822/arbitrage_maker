"""
Demo com dados reais do repo: WestWing (WEST3), redução de capital de R$60M (mar/2026).

Mostra os dois comportamentos que o ROADMAP exige do motor:
  1. Quando falta input (dívida bruta de 2025 não está nos dados estruturados), o motor
     PEDE o dado em vez de estimar.
  2. Quando os inputs existem, devolve a conta reconciliada com fontes.

Uso: python -m arbmaker.examples.westwing_reducao_capital
"""
from __future__ import annotations

import json
from pathlib import Path

from arbmaker.calc import MissingInput, capital_ops, capital_structure

ROOT = Path(__file__).resolve().parents[2]
WW = ROOT / "data" / "westwing" / "structured"


def _price_on(prices: list[dict], d: str) -> dict:
    cand = [p for p in prices if p["date"] <= d]
    return cand[-1]


def _fin(fins: list[dict], periodo: str) -> dict:
    """Entre entradas duplicadas do mesmo periodo, usa a mais completa (mais campos de balanco preenchidos)."""
    cands = [f for f in fins if "raw" not in f and f.get("periodo") == periodo]
    if not cands:
        raise KeyError(f"periodo {periodo} nao encontrado nos dados estruturados")
    return max(cands, key=lambda f: sum(v is not None for v in f.get("balanco", {}).values()))


def main() -> None:
    prices = json.loads((WW / "prices.json").read_text(encoding="utf-8"))
    fins = json.loads((WW / "financials_timeline.json").read_text(encoding="utf-8"))
    est = json.loads((WW / "estatuto_vigente.json").read_text(encoding="utf-8"))
    acoes = est["capital_social"]["total_acoes"]
    print("AVISO: numero de acoes vem do estatuto de", est["data_versao"], "e os precos do yfinance sao ajustados por"
          " grupamento/desdobramento. Para datas antigas, confirmar a quantidade de acoes no FRE/DFP da epoca.\n")

    # -------- 1) Momento detectável: DFP 2022 publicada (caixa 158,2M) --------
    dfp22 = _fin(fins, "2022")
    px = _price_on(prices, "2023-03-31")
    mc = capital_structure.market_cap({"ON": acoes}, {"ON": px["close"]})
    print(mc.with_sources(acoes={"origem": "estatuto_vigente.json", "data": est["data_versao"]},
                          precos={"origem": "prices.json", "data": px["date"]}).render(), "\n")
    r1 = capital_ops.cash_vs_market_cap(
        caixa=dfp22["balanco"]["caixa_total"] * 1000,
        divida_bruta=dfp22["balanco"]["divida_bruta"] * 1000,
        market_cap=mc.outputs["market_cap"],
        queima_caixa_12m=abs(dfp22["dre"]["lucro_liquido"]) * 1000,   # proxy declarado: prejuízo 2022
    ).with_sources(caixa={"origem": "DFP 2022", "data": "2022-12-31"},
                   divida_bruta={"origem": "DFP 2022", "data": "2022-12-31"},
                   queima_caixa_12m={"origem": "DFP 2022 (lucro líquido como proxy, NÃO é FCO)", "data": "2022-12-31"})
    print(r1.render(), "\n")

    # -------- 2) Mar/2026: caixa do 4T25 existe, dívida bruta não (LLM não extraiu) --------
    itr4t25 = _fin(fins, "4T25")
    px2 = _price_on(prices, "2026-03-20")   # último fechamento antes do FR de 22/03
    mc2 = capital_structure.market_cap({"ON": acoes}, {"ON": px2["close"]})
    try:
        capital_ops.cash_vs_market_cap(caixa=itr4t25["balanco"]["caixa_total"] * 1000,
                                       divida_bruta=itr4t25["balanco"].get("divida_bruta"),
                                       market_cap=mc2.outputs["market_cap"])
    except MissingInput as e:
        print("PEDIDO DE DADO >>", e, "\n")

    # -------- 3) Redução de capital R$60M: conta com o que existe --------
    r3 = capital_ops.capital_reduction(
        valor_restituido=60_000_000,
        acoes=acoes,
        preco=px2["close"],
        caixa_total=itr4t25["balanco"]["caixa_total"] * 1000,
        divida_bruta=None,
    ).with_sources(valor_restituido={"origem": "Fato Relevante (alerta backtest)", "data": "2026-03-22"},
                   acoes={"origem": "estatuto_vigente.json", "data": est["data_versao"]},
                   preco={"origem": "prices.json", "data": px2["date"]},
                   caixa_total={"origem": "ITR 4T25", "data": "2025-12-31"})
    print(r3.render(), "\n")

    # -------- 4) O que aconteceu depois (último preço disponível) --------
    last = prices[-1]
    ret = last["close"] / px2["close"] - 1
    print(f"Preço {px2['date']}: {px2['close']:.2f}  ->  {last['date']}: {last['close']:.2f}  ({ret*100:+.1f}%)")
    print(f"Restituição por ação R${r3.outputs['restituicao_por_acao']:.2f} = {r3.outputs['restituicao_sobre_preco_pct']:.1f}% do preço pré-anúncio")


if __name__ == "__main__":
    main()

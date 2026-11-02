"""
arbmaker.calc.parity — paridade entre classes (ON/PN) e Units.
"""
from __future__ import annotations

from .core import Check, Result, annualize, close, non_negative, positive, require, pct


def class_parity(
    preco_a: float,
    preco_b: float,
    razao_a_por_b: float = 1.0,
    dividendo_a: float = 0.0,
    dividendo_b: float = 0.0,
    aluguel_a_aa_pct: float = 0.0,
    aluguel_b_aa_pct: float = 0.0,
    dias: int | None = None,
) -> Result:
    """
    Paridade entre duas classes (ex: A = ENGI3 ON, B = ENGI4 PN). razao_a_por_b e quantas
    acoes A equivalem a 1 B na regra de conversao (1.0 se 1:1).

    premio_a_pct > 0  => A cara vs B: trade = vender A (tomada em aluguel) / comprar B.
    O carry considera: aluguel da perna vendida e dividendos (recebe da comprada, paga da vendida)
    no horizonte `dias`. Sem `dias`, devolve so o premio bruto.
    """
    calc = "parity.class_parity"
    require(calc, preco_a=preco_a, preco_b=preco_b)
    positive(calc, preco_a=preco_a, preco_b=preco_b, razao_a_por_b=razao_a_por_b)
    non_negative(calc, aluguel_a_aa_pct=aluguel_a_aa_pct, aluguel_b_aa_pct=aluguel_b_aa_pct)

    teorico_a = preco_b / razao_a_por_b          # preco de A que zera a paridade
    premio_a = preco_a / teorico_a - 1.0
    out = {
        "preco_teorico_a": teorico_a,
        "premio_a_sobre_b_pct": pct(premio_a),
        "perna_vendida": "A" if premio_a > 0 else "B",
        "perna_comprada": "B" if premio_a > 0 else "A",
        "spread_bruto_por_par": abs(preco_a - teorico_a),
    }
    notas = ["Paridade so converge se existir mecanismo (conversao estatutaria, OPA com mesmo preco, "
             "unificacao de classes). Sem mecanismo, o spread e historico, nao arbitragem."]
    checks = []
    if dias is not None:
        positive(calc, dias=dias)
        t = dias / 365.0
        if premio_a > 0:
            custo_aluguel = preco_a * aluguel_a_aa_pct / 100.0 * t
            carry_div = dividendo_b - dividendo_a * razao_a_por_b
        else:
            custo_aluguel = preco_b * aluguel_b_aa_pct / 100.0 * t
            carry_div = dividendo_a * razao_a_por_b - dividendo_b
        liquido = out["spread_bruto_por_par"] - custo_aluguel + carry_div
        base = min(preco_a, teorico_a)
        out.update({
            "dias": dias,
            "custo_aluguel_periodo": custo_aluguel,
            "carry_dividendos_periodo": carry_div,
            "spread_liquido_por_par": liquido,
            "retorno_liquido_pct": pct(liquido / base),
            "retorno_liquido_aa_pct": pct(annualize(liquido / base, dias)),
        })
        checks.append(Check("spread_liquido_positivo", liquido > 0, f"{liquido:.4f} por par"))
    return Result(calc, inputs={
        "preco_a": preco_a, "preco_b": preco_b, "razao_a_por_b": razao_a_por_b,
        "dividendo_a": dividendo_a, "dividendo_b": dividendo_b,
        "aluguel_a_aa_pct": aluguel_a_aa_pct, "aluguel_b_aa_pct": aluguel_b_aa_pct, "dias": dias,
    }, outputs=out, checks=checks, notas=notas)


def unit_parity(
    preco_unit: float,
    composicao: dict[str, int],
    precos: dict[str, float],
    custo_montagem_por_unit: float = 0.0,
) -> Result:
    """
    Unit vs cesta. composicao = {"ON": 1, "PN": 2}; precos = {"ON": 10.0, "PN": 9.5}.
    premio_unit_pct > 0 => Unit cara: comprar cesta, montar Unit, vender Unit.
    premio_unit_pct < 0 => Unit barata: comprar Unit, desmontar, vender cesta.
    """
    calc = "parity.unit_parity"
    require(calc, preco_unit=preco_unit, composicao=composicao, precos=precos)
    positive(calc, preco_unit=preco_unit)
    faltando = [c for c in composicao if precos.get(c) is None]
    if faltando:
        from .core import MissingInput
        raise MissingInput(calc, [f"preco_{c}" for c in faltando])
    teorico = sum(q * precos[c] for c, q in composicao.items())
    premio = preco_unit / teorico - 1.0
    bruto = preco_unit - teorico
    liquido = abs(bruto) - custo_montagem_por_unit
    out = {
        "preco_teorico_unit": teorico,
        "premio_unit_pct": pct(premio),
        "direcao": "comprar cesta / vender unit" if premio > 0 else "comprar unit / vender cesta",
        "spread_bruto": bruto,
        "spread_liquido": liquido,
        "retorno_liquido_pct": pct(liquido / min(preco_unit, teorico)),
    }
    checks = [Check("spread_cobre_custo_montagem", liquido > 0, f"{liquido:.4f} por unit")]
    notas = ["Verificar no estatuto/regulamento se montagem e desmontagem sao livres e o prazo (D+n) de cada operacao."]
    return Result(calc, inputs={"preco_unit": preco_unit, "composicao": composicao, "precos": precos,
                                "custo_montagem_por_unit": custo_montagem_por_unit},
                  outputs=out, checks=checks, notas=notas)

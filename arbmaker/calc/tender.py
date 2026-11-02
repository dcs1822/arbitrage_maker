"""
arbmaker.calc.tender — OPA (oferta publica), tag along (art. 254-A) e recesso.
"""
from __future__ import annotations

from .core import Check, Result, annualize, days_between, non_negative, positive, require, pct


def opa_spread(
    preco_mercado: float,
    preco_oferta: float,
    data_ref,
    data_liquidacao_esperada,
    prob_sucesso: float | None = None,
    preco_sem_oferta: float | None = None,
    ajuste_oferta: float = 0.0,
) -> Result:
    """
    Spread de OPA / oferta de fechamento / oferta por controle.

    preco_oferta + ajuste_oferta : preco final esperado (ajuste = juros/correcao ate a liquidacao, se houver)
    prob_sucesso (0..1) e preco_sem_oferta : opcionais, para valor esperado e prob. de breakeven
    """
    calc = "tender.opa_spread"
    require(calc, preco_mercado=preco_mercado, preco_oferta=preco_oferta, data_ref=data_ref,
            data_liquidacao_esperada=data_liquidacao_esperada)
    positive(calc, preco_mercado=preco_mercado, preco_oferta=preco_oferta)
    dias = days_between(data_ref, data_liquidacao_esperada)
    if dias <= 0:
        raise ValueError(f"[{calc}] data_liquidacao_esperada deve ser posterior a data_ref")
    alvo = preco_oferta + ajuste_oferta
    spread = alvo / preco_mercado - 1.0
    out = {
        "preco_alvo": alvo,
        "spread_bruto_pct": pct(spread),
        "dias_ate_liquidacao": dias,
        "spread_anualizado_pct": pct(annualize(spread, dias)),
    }
    checks = []
    notas = []
    if prob_sucesso is not None or preco_sem_oferta is not None:
        require(calc, prob_sucesso=prob_sucesso, preco_sem_oferta=preco_sem_oferta)
        if not 0.0 <= prob_sucesso <= 1.0:
            raise ValueError(f"[{calc}] prob_sucesso deve estar em [0,1]")
        esperado = prob_sucesso * alvo + (1 - prob_sucesso) * preco_sem_oferta
        ret_esp = esperado / preco_mercado - 1.0
        denom = alvo - preco_sem_oferta
        breakeven = (preco_mercado - preco_sem_oferta) / denom if denom else None
        out.update({
            "preco_esperado": esperado,
            "retorno_esperado_pct": pct(ret_esp),
            "retorno_esperado_aa_pct": pct(annualize(ret_esp, dias)),
            "downside_se_falhar_pct": pct(preco_sem_oferta / preco_mercado - 1.0),
            "prob_breakeven_implicita_pct": pct(breakeven) if breakeven is not None else None,
        })
        checks.append(Check("mercado_entre_downside_e_oferta", preco_sem_oferta <= preco_mercado <= alvo,
                            "fora desse intervalo o mercado precifica outra coisa (oferta melhorada ou falha certa)"))
        notas.append("prob_sucesso e preco_sem_oferta sao premissas do analista, nao dados: registre a fonte do raciocinio.")
    return Result(calc, inputs={
        "preco_mercado": preco_mercado, "preco_oferta": preco_oferta, "data_ref": str(data_ref),
        "data_liquidacao_esperada": str(data_liquidacao_esperada), "prob_sucesso": prob_sucesso,
        "preco_sem_oferta": preco_sem_oferta, "ajuste_oferta": ajuste_oferta,
    }, outputs=out, checks=checks, notas=notas)


def tag_along_price(preco_pago_por_acao_controle: float, tag_along_pct: float, preco_mercado: float | None = None) -> Result:
    """
    Preco minimo da OPA por alienacao de controle (art. 254-A: 80% por lei; estatuto pode dar 100%).
    """
    calc = "tender.tag_along_price"
    require(calc, preco_pago_por_acao_controle=preco_pago_por_acao_controle, tag_along_pct=tag_along_pct)
    positive(calc, preco_pago_por_acao_controle=preco_pago_por_acao_controle, tag_along_pct=tag_along_pct)
    preco_opa = preco_pago_por_acao_controle * tag_along_pct / 100.0
    out = {"preco_minimo_opa": preco_opa}
    checks = [Check("tag_along_legal_minimo_80", tag_along_pct >= 80.0, "abaixo de 80% viola art. 254-A da Lei 6.404")]
    if preco_mercado is not None:
        positive(calc, preco_mercado=preco_mercado)
        out["premio_vs_mercado_pct"] = pct(preco_opa / preco_mercado - 1.0)
    notas = ["O preco por acao do controle pode embutir premio por bloco e parcelas contingentes; "
             "a CVM pode questionar o preco atribuido. Classes PN sem tag along estatutario nao tem o direito."]
    return Result(calc, inputs={"preco_pago_por_acao_controle": preco_pago_por_acao_controle,
                                "tag_along_pct": tag_along_pct, "preco_mercado": preco_mercado},
                  outputs=out, checks=checks, notas=notas)


def recesso(valor_reembolso_por_acao: float, preco_mercado: float, data_ref=None, data_pagamento=None) -> Result:
    """
    Direito de recesso (arts. 137/45): reembolso ao valor patrimonial (ou economico, se o estatuto
    previr). Vale a pena quando reembolso > preco de mercado.
    """
    calc = "tender.recesso"
    require(calc, valor_reembolso_por_acao=valor_reembolso_por_acao, preco_mercado=preco_mercado)
    positive(calc, valor_reembolso_por_acao=valor_reembolso_por_acao, preco_mercado=preco_mercado)
    premio = valor_reembolso_por_acao / preco_mercado - 1.0
    out = {"premio_recesso_pct": pct(premio), "vale_recesso": premio > 0}
    if data_ref is not None and data_pagamento is not None:
        dias = days_between(data_ref, data_pagamento)
        if dias > 0:
            out["dias_ate_pagamento"] = dias
            out["premio_anualizado_pct"] = pct(annualize(premio, dias))
    notas = ["So tem recesso quem era acionista na data da primeira convocacao/fato relevante (art. 137 §1) e nao votou a favor. "
             "Acoes com liquidez e dispersao (art. 137 II) podem nao ter recesso. A companhia pode reconsiderar a deliberacao se o recesso custar caro (art. 137 §3)."]
    return Result(calc, inputs={"valor_reembolso_por_acao": valor_reembolso_por_acao, "preco_mercado": preco_mercado,
                                "data_ref": str(data_ref) if data_ref else None,
                                "data_pagamento": str(data_pagamento) if data_pagamento else None},
                  outputs=out, notas=notas)

"""
arbmaker.calc.merger — relacao de troca em incorporacao / fusao e spread de merger arb.
"""
from __future__ import annotations

from .core import Check, Result, annualize, days_between, non_negative, positive, require, pct


def exchange_ratio(
    preco_adquirente: float,
    preco_alvo: float,
    razao_acoes_adquirente_por_alvo: float,
    caixa_por_acao_alvo: float = 0.0,
    data_ref=None,
    data_fechamento=None,
    prob_sucesso: float | None = None,
    preco_alvo_sem_deal: float | None = None,
) -> Result:
    """
    Preco implicito do alvo = razao * preco_adquirente + caixa. Spread = implicito / preco_alvo - 1.
    Hedge: para cada acao do alvo comprada, vender `razao` acoes do adquirente.
    """
    calc = "merger.exchange_ratio"
    require(calc, preco_adquirente=preco_adquirente, preco_alvo=preco_alvo,
            razao_acoes_adquirente_por_alvo=razao_acoes_adquirente_por_alvo)
    positive(calc, preco_adquirente=preco_adquirente, preco_alvo=preco_alvo, razao_acoes_adquirente_por_alvo=razao_acoes_adquirente_por_alvo)
    non_negative(calc, caixa_por_acao_alvo=caixa_por_acao_alvo)
    implicito = razao_acoes_adquirente_por_alvo * preco_adquirente + caixa_por_acao_alvo
    spread = implicito / preco_alvo - 1.0
    out = {
        "preco_implicito_alvo": implicito,
        "spread_bruto_pct": pct(spread),
        "hedge_ratio_acoes_adquirente_por_alvo": razao_acoes_adquirente_por_alvo,
        "parcela_caixa_pct": pct(caixa_por_acao_alvo / implicito) if implicito else None,
    }
    checks = []
    notas = ["Spread liquido exige: custo de aluguel do adquirente (perna vendida), dividendos das duas pernas ate o fechamento, "
             "e risco de ajuste da relacao (collar, laudo, recesso)."]
    if data_ref is not None and data_fechamento is not None:
        dias = days_between(data_ref, data_fechamento)
        if dias <= 0:
            raise ValueError(f"[{calc}] data_fechamento deve ser posterior a data_ref")
        out["dias_ate_fechamento"] = dias
        out["spread_anualizado_pct"] = pct(annualize(spread, dias))
        if prob_sucesso is not None or preco_alvo_sem_deal is not None:
            require(calc, prob_sucesso=prob_sucesso, preco_alvo_sem_deal=preco_alvo_sem_deal)
            esperado = prob_sucesso * implicito + (1 - prob_sucesso) * preco_alvo_sem_deal
            ret = esperado / preco_alvo - 1.0
            denom = implicito - preco_alvo_sem_deal
            out.update({
                "preco_esperado_alvo": esperado,
                "retorno_esperado_pct": pct(ret),
                "retorno_esperado_aa_pct": pct(annualize(ret, dias)),
                "prob_breakeven_implicita_pct": pct((preco_alvo - preco_alvo_sem_deal) / denom) if denom else None,
            })
            checks.append(Check("alvo_entre_sem_deal_e_implicito", preco_alvo_sem_deal <= preco_alvo <= implicito))
    return Result(calc, inputs={
        "preco_adquirente": preco_adquirente, "preco_alvo": preco_alvo,
        "razao_acoes_adquirente_por_alvo": razao_acoes_adquirente_por_alvo, "caixa_por_acao_alvo": caixa_por_acao_alvo,
        "data_ref": str(data_ref) if data_ref else None, "data_fechamento": str(data_fechamento) if data_fechamento else None,
        "prob_sucesso": prob_sucesso, "preco_alvo_sem_deal": preco_alvo_sem_deal,
    }, outputs=out, checks=checks, notas=notas)

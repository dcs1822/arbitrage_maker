"""
arbmaker.calc.capital_ops — aumento de capital (TERP/direitos), reducao de capital, caixa vs MC.
"""
from __future__ import annotations

from .core import Check, Result, close, non_negative, positive, require, pct


def terp(preco: float, acoes_existentes: int, acoes_novas: float, preco_subscricao: float) -> Result:
    """
    Preco teorico ex-direitos e valor do direito de subscricao.
    """
    calc = "capital_ops.terp"
    require(calc, preco=preco, acoes_existentes=acoes_existentes, acoes_novas=acoes_novas, preco_subscricao=preco_subscricao)
    positive(calc, preco=preco, acoes_existentes=acoes_existentes, acoes_novas=acoes_novas, preco_subscricao=preco_subscricao)
    total = acoes_existentes + acoes_novas
    terp_v = (preco * acoes_existentes + preco_subscricao * acoes_novas) / total
    direito_por_nova = terp_v - preco_subscricao
    direitos_por_antiga = acoes_novas / acoes_existentes
    direito_por_antiga = direitos_por_antiga * direito_por_nova
    out = {
        "terp": terp_v,
        "valor_direito_por_acao_nova": direito_por_nova,
        "direitos_por_acao_antiga": direitos_por_antiga,
        "valor_direito_por_acao_antiga": direito_por_antiga,
        "desconto_subscricao_vs_terp_pct": pct(1.0 - preco_subscricao / terp_v),
        "desconto_subscricao_vs_preco_pct": pct(1.0 - preco_subscricao / preco),
        "diluicao_quem_nao_subscreve_pct": pct(acoes_novas / total),
        "captacao": acoes_novas * preco_subscricao,
    }
    checks = [Check("terp_entre_subscricao_e_preco", min(preco, preco_subscricao) <= terp_v <= max(preco, preco_subscricao)),
              Check("preco_menos_terp_igual_direito_por_antiga", close(preco - terp_v, direito_por_antiga))]
    notas = ["Se o direito negocia abaixo de valor_direito_por_acao_nova, comprar direito + subscrever bate comprar a acao. "
             "Considerar rateio de sobras, prazo ate a homologacao e preco da acao na data da liquidacao."]
    return Result(calc, inputs={"preco": preco, "acoes_existentes": acoes_existentes, "acoes_novas": acoes_novas,
                                "preco_subscricao": preco_subscricao}, outputs=out, checks=checks, notas=notas)


def capital_reduction(
    valor_restituido: float,
    acoes: int,
    preco: float,
    caixa_total: float,
    divida_bruta: float | None = None,
) -> Result:
    """
    Reducao de capital com restituicao em dinheiro (art. 173). Quanto volta por acao e o que
    sobra de equity depois.
    """
    calc = "capital_ops.capital_reduction"
    require(calc, valor_restituido=valor_restituido, acoes=acoes, preco=preco, caixa_total=caixa_total)
    positive(calc, valor_restituido=valor_restituido, acoes=acoes, preco=preco)
    non_negative(calc, caixa_total=caixa_total)
    por_acao = valor_restituido / acoes
    mc_pre = acoes * preco
    preco_ex = preco - por_acao
    mc_ex = preco_ex * acoes
    caixa_pos = caixa_total - valor_restituido
    out = {
        "restituicao_por_acao": por_acao,
        "restituicao_sobre_preco_pct": pct(por_acao / preco),
        "preco_ex_teorico": preco_ex,
        "market_cap_pre": mc_pre,
        "market_cap_ex_teorico": mc_ex,
        "caixa_pos": caixa_pos,
        "caixa_pos_sobre_mc_ex": (caixa_pos / mc_ex) if mc_ex > 0 else None,
    }
    checks = [
        Check("caixa_cobre_restituicao", valor_restituido <= caixa_total, f"restitui {valor_restituido:,.0f} de caixa {caixa_total:,.0f}"),
        Check("mc_reconcilia", close(mc_pre - valor_restituido, mc_ex)),
    ]
    notas = ["Prazo: 60 dias apos publicacao da ata para oposicao de credores quirografarios (art. 174); "
             "so depois a reducao e eficaz. Restituicao de capital nao e dividendo: tratamento fiscal distinto."]
    if divida_bruta is not None:
        non_negative(calc, divida_bruta=divida_bruta)
        caixa_liq_pos = caixa_pos - divida_bruta
        out["caixa_liquido_pos"] = caixa_liq_pos
        out["ev_pos_teorico"] = mc_ex - caixa_liq_pos
    else:
        notas.append("divida_bruta nao informada: caixa liquido e EV pos nao calculados (nao estimamos).")
    if preco_ex <= 0:
        notas.append("Restituicao por acao >= preco: mercado precifica o equity abaixo do caixa devolvido. Verificar.")
    return Result(calc, inputs={"valor_restituido": valor_restituido, "acoes": acoes, "preco": preco,
                                "caixa_total": caixa_total, "divida_bruta": divida_bruta},
                  outputs=out, checks=checks, notas=notas)


def cash_vs_market_cap(caixa: float, divida_bruta: float, market_cap: float, queima_caixa_12m: float | None = None) -> Result:
    """
    Screen classico de special situation: caixa liquido vs market cap.
    """
    calc = "capital_ops.cash_vs_market_cap"
    require(calc, caixa=caixa, divida_bruta=divida_bruta, market_cap=market_cap)
    non_negative(calc, caixa=caixa, divida_bruta=divida_bruta)
    positive(calc, market_cap=market_cap)
    caixa_liq = caixa - divida_bruta
    ev = market_cap - caixa_liq
    out = {
        "caixa_liquido": caixa_liq,
        "caixa_liquido_sobre_mc": caixa_liq / market_cap,
        "ev": ev,
        "caixa_liquido_maior_que_mc": caixa_liq > market_cap,
        "desconto_mc_sobre_caixa_liquido_pct": pct(1.0 - market_cap / caixa_liq) if caixa_liq > 0 else None,
    }
    checks = []
    notas = []
    if queima_caixa_12m is not None:
        non_negative(calc, queima_caixa_12m=queima_caixa_12m)
        if queima_caixa_12m > 0:
            out["anos_de_caixa_na_queima_atual"] = caixa_liq / queima_caixa_12m if caixa_liq > 0 else 0.0
            out["mc_sobre_caixa_liq_daqui_1_ano"] = market_cap / (caixa_liq - queima_caixa_12m) if caixa_liq > queima_caixa_12m else None
            notas.append("Caixa > MC so e tese se a queima parar ou se houver evento de distribuicao (reducao de capital, dividendo extra, OPA). Caso contrario o desconto e racional.")
    return Result(calc, inputs={"caixa": caixa, "divida_bruta": divida_bruta, "market_cap": market_cap,
                                "queima_caixa_12m": queima_caixa_12m}, outputs=out, checks=checks, notas=notas)

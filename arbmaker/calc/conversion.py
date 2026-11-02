"""
arbmaker.calc.conversion — conversao de divida em equity.

Pergunta central: e mais barato entrar no equity comprando a acao ou comprando a divida
que vai virar acao? E quanto o acionista atual dilui?
"""
from __future__ import annotations

from .core import Check, Result, close, non_negative, positive, require, pct


def debt_to_equity(
    divida_face: float,
    preco_conversao: float,
    acoes_existentes: int,
    preco_acao: float,
    haircut_pct: float = 0.0,
    parcela_convertida_pct: float = 100.0,
    preco_bond_pct_par: float | None = None,
    capital_autorizado_acoes: int | None = None,
) -> Result:
    """
    divida_face            : valor de face da divida elegivel (mesma unidade de preco_acao * acoes)
    preco_conversao        : R$ por acao nova (fixado no plano/escritura)
    acoes_existentes       : acoes antes da conversao
    preco_acao             : preco de mercado da acao hoje
    haircut_pct            : desagio aplicado antes de converter (30 = converte 70% da face)
    parcela_convertida_pct : fatia da divida que converte (o resto fica como divida)
    preco_bond_pct_par     : preco de mercado da divida, se existir (para comparar os dois caminhos)
    capital_autorizado_acoes: limite do capital autorizado (se None, nao checa)
    """
    calc = "conversion.debt_to_equity"
    require(calc, divida_face=divida_face, preco_conversao=preco_conversao,
            acoes_existentes=acoes_existentes, preco_acao=preco_acao)
    positive(calc, divida_face=divida_face, preco_conversao=preco_conversao, acoes_existentes=acoes_existentes, preco_acao=preco_acao)
    non_negative(calc, haircut_pct=haircut_pct, parcela_convertida_pct=parcela_convertida_pct)
    if haircut_pct >= 100 or parcela_convertida_pct > 100:
        raise ValueError(f"[{calc}] haircut_pct deve ser < 100 e parcela_convertida_pct <= 100")

    fator = (parcela_convertida_pct / 100.0) * (1.0 - haircut_pct / 100.0)
    divida_convertida = divida_face * fator
    acoes_novas = divida_convertida / preco_conversao
    acoes_pos = acoes_existentes + acoes_novas
    stake_credores = acoes_novas / acoes_pos
    diluicao = 1.0 - acoes_existentes / acoes_pos

    mc_pre = acoes_existentes * preco_acao
    mc_pos_mesmo_preco = acoes_pos * preco_acao
    # valor de mercado do equity recebido por R$1 de face
    acoes_por_face = fator / preco_conversao
    valor_equity_por_face_pct = acoes_por_face * preco_acao * 100.0   # "preco do bond implicito pelo equity"

    out = {
        "divida_convertida": divida_convertida,
        "acoes_novas": acoes_novas,
        "acoes_pos_conversao": acoes_pos,
        "stake_credores_pct": pct(stake_credores),
        "diluicao_acionistas_atuais_pct": pct(diluicao),
        "premio_preco_conversao_vs_mercado_pct": pct(preco_conversao / preco_acao - 1.0),
        "market_cap_pre": mc_pre,
        "market_cap_pos_ao_preco_atual": mc_pos_mesmo_preco,
        "acoes_por_R$1_de_face": acoes_por_face,
        "preco_bond_implicito_pelo_equity_pct_par": valor_equity_por_face_pct,
    }
    checks = [
        Check("acoes_reconciliam", close(acoes_existentes + acoes_novas, acoes_pos)),
        Check("stake_mais_diluicao_consistente", close(stake_credores, diluicao)),
    ]
    notas = []

    if capital_autorizado_acoes is not None:
        cabe = acoes_pos <= capital_autorizado_acoes + 1e-9
        checks.append(Check("cabe_no_capital_autorizado", cabe,
                            f"pos={acoes_pos:,.0f} vs autorizado={capital_autorizado_acoes:,}"))
        if not cabe:
            notas.append("Conversao excede o capital autorizado: exige AGE (quorum e voto de minoritarios relevantes passam a importar).")

    if preco_bond_pct_par is not None:
        non_negative(calc, preco_bond_pct_par=preco_bond_pct_par)
        custo_por_face = preco_bond_pct_par / 100.0
        breakeven = custo_por_face / acoes_por_face if acoes_por_face else None   # preco da acao que iguala os dois caminhos
        ratio = valor_equity_por_face_pct / preco_bond_pct_par if preco_bond_pct_par else None
        out.update({
            "preco_bond_pct_par": preco_bond_pct_par,
            "preco_acao_breakeven": breakeven,
            "equity_recebido_sobre_custo_bond": ratio,
            "caminho_mais_barato": ("divida" if preco_acao > breakeven else "acao") if breakeven else None,
            "desconto_via_divida_pct": pct(1.0 - breakeven / preco_acao) if breakeven else None,
        })
        notas.append("Comparacao ignora: tempo ate a conversao, risco de o plano mudar, cupons/juros ate la, "
                     "custo de aluguel se a perna curta for a acao, e parcela nao convertida que continua como credito.")

    return Result(calc, inputs={
        "divida_face": divida_face, "preco_conversao": preco_conversao, "acoes_existentes": acoes_existentes,
        "preco_acao": preco_acao, "haircut_pct": haircut_pct, "parcela_convertida_pct": parcela_convertida_pct,
        "preco_bond_pct_par": preco_bond_pct_par, "capital_autorizado_acoes": capital_autorizado_acoes,
    }, outputs=out, checks=checks, notas=notas)

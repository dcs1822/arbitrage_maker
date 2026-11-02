"""
arbmaker.calc.capital_structure — market cap, EV, waterfall e leitura cruzada bond x equity.

Convencao de unidades: todos os valores monetarios na MESMA unidade (R$ ou R$ mil,
tanto faz, mas consistente). Precos de bond em % do par (40.0 = 40% do par).
"""
from __future__ import annotations

from dataclasses import dataclass

from .core import Check, Result, close, non_negative, positive, require, pct


# ---------------------------------------------------------------------------
# Market cap e EV
# ---------------------------------------------------------------------------

def market_cap(acoes: dict[str, int], precos: dict[str, float]) -> Result:
    """
    Market cap somando todas as classes (ON, PN, Units ja desmontadas, etc).

    acoes : {"ON": 11109348, "PN": 0}
    precos: {"ON": 6.72, "PN": None}  (classe sem acoes pode ter preco None)
    """
    calc = "capital_structure.market_cap"
    require(calc, acoes=acoes, precos=precos)
    faltando = [c for c, q in acoes.items() if q and precos.get(c) is None]
    if faltando:
        from .core import MissingInput
        raise MissingInput(calc, [f"preco_{c}" for c in faltando])

    por_classe = {}
    total = 0.0
    total_acoes = 0
    for classe, qtd in acoes.items():
        if not qtd:
            continue
        v = qtd * float(precos[classe])
        por_classe[classe] = v
        total += v
        total_acoes += qtd

    return Result(
        calc,
        inputs={"acoes": acoes, "precos": precos},
        outputs={"market_cap": total, "total_acoes": total_acoes, "por_classe": por_classe},
        checks=[Check("soma_das_classes", close(sum(por_classe.values()), total), "")],
    )


def enterprise_value(
    market_cap: float,
    divida_bruta: float,
    caixa: float,
    minoritarios: float = 0.0,
    outras_reivindicacoes: float = 0.0,
) -> Result:
    """
    EV = MC + divida bruta - caixa + minoritarios + outras reivindicacoes (ex: preferenciais
    resgataveis, earn-outs, passivos de RJ reconhecidos).

    `caixa` deve ser o que voce considera caixa disponivel (caixa + aplicacoes). Se a
    empresa tem caixa restrito, trate como decisao explicita do analista.
    """
    calc = "capital_structure.enterprise_value"
    require(calc, market_cap=market_cap, divida_bruta=divida_bruta, caixa=caixa)
    non_negative(calc, divida_bruta=divida_bruta, caixa=caixa)
    divida_liquida = divida_bruta - caixa
    ev = market_cap + divida_liquida + minoritarios + outras_reivindicacoes
    out = {
        "ev": ev,
        "divida_liquida": divida_liquida,
        "caixa_liquido": -divida_liquida,
        "divida_liquida_sobre_mc": (divida_liquida / market_cap) if market_cap else None,
        "ev_negativo": ev < 0,
    }
    checks = [
        Check("ev_reconcilia", close(ev - market_cap - divida_bruta + caixa - minoritarios - outras_reivindicacoes, 0.0)),
    ]
    notas = []
    if ev < 0:
        notas.append("EV negativo: mercado paga menos pelo equity do que o caixa liquido. Checar caixa restrito, queima de caixa e passivos fora do balanco antes de concluir.")
    return Result(calc, inputs={
        "market_cap": market_cap, "divida_bruta": divida_bruta, "caixa": caixa,
        "minoritarios": minoritarios, "outras_reivindicacoes": outras_reivindicacoes,
    }, outputs=out, checks=checks, notas=notas)


# ---------------------------------------------------------------------------
# Waterfall de prioridade absoluta
# ---------------------------------------------------------------------------

@dataclass
class Claim:
    nome: str
    valor: float          # face / saldo devedor (mesma unidade do EV)
    senioridade: int      # 1 = mais senior. Mesmo numero = pari passu
    preco_pct_par: float | None = None   # preco de mercado em % do par, se existir


def waterfall(ev: float, claims: list[Claim]) -> Result:
    """
    Distribui o EV pelas reivindicacoes em ordem de senioridade (regra de prioridade
    absoluta). Pari passu dentro do mesmo nivel recebe pro-rata. O residuo e o equity.

    Devolve, por tranche: recuperacao em valor, em % do par, e o preco de mercado
    informado (se houver) para comparar.
    """
    calc = "capital_structure.waterfall"
    require(calc, ev=ev, claims=claims)
    if not claims:
        raise ValueError(f"[{calc}] lista de claims vazia")
    for c in claims:
        non_negative(calc, **{f"valor_{c.nome}": c.valor})

    restante = max(ev, 0.0)
    tranches = []
    niveis = sorted({c.senioridade for c in claims})
    for n in niveis:
        grupo = [c for c in claims if c.senioridade == n]
        face_grupo = sum(c.valor for c in grupo)
        pago_grupo = min(restante, face_grupo)
        for c in grupo:
            pago = pago_grupo * (c.valor / face_grupo) if face_grupo else 0.0
            rec_pct = (pago / c.valor * 100.0) if c.valor else None
            tranches.append({
                "nome": c.nome,
                "senioridade": n,
                "face": c.valor,
                "recuperacao": pago,
                "recuperacao_pct_par": rec_pct,
                "preco_mercado_pct_par": c.preco_pct_par,
                "mercado_vs_waterfall_pp": (c.preco_pct_par - rec_pct) if (c.preco_pct_par is not None and rec_pct is not None) else None,
            })
        restante -= pago_grupo

    equity = restante
    total_face = sum(c.valor for c in claims)
    total_pago = sum(t["recuperacao"] for t in tranches)
    checks = [
        Check("ev_totalmente_distribuido", close(total_pago + equity, max(ev, 0.0)),
              f"pago={total_pago:,.0f} + equity={equity:,.0f} vs ev={max(ev, 0.0):,.0f}"),
        Check("nenhuma_tranche_acima_do_par", all((t["recuperacao_pct_par"] or 0) <= 100.0 + 1e-9 for t in tranches)),
    ]
    notas = []
    if equity <= 0 and ev < total_face:
        notas.append("Equity vale zero pela prioridade absoluta. Qualquer valor de mercado do equity precisa ser explicado por: opcao sobre recuperacao, violacao negociada da prioridade (new money, conversao), ou informacao diferente.")
    return Result(calc, inputs={"ev": ev, "claims": [vars(c) for c in claims]},
                  outputs={"tranches": tranches, "equity_residual": equity,
                           "cobertura_total_pct": (ev / total_face * 100.0) if total_face else None},
                  checks=checks, notas=notas)


# ---------------------------------------------------------------------------
# EV implicito pelo preco do bond e leitura cruzada com o equity
# ---------------------------------------------------------------------------

def implied_ev_from_bond(
    preco_bond_pct_par: float,
    face_bond: float,
    face_pari_passu_outros: float = 0.0,
    face_senior: float = 0.0,
    face_junior: float = 0.0,
) -> Result:
    """
    Le o EV que o preco do bond esta embutindo sob prioridade absoluta e SEM valor
    temporal (preco = recuperacao esperada). Util como ancora, nao como verdade.

    Se preco < 100: seniores recebem 100%, o nivel do bond recebe `preco` %, juniores e
    equity recebem 0.  EV_bond = face_senior + preco% * (face_bond + face_pari_passu).
    Se preco >= 100: o bond so da um piso: EV >= face_senior + nivel do bond.
    """
    calc = "capital_structure.implied_ev_from_bond"
    require(calc, preco_bond_pct_par=preco_bond_pct_par, face_bond=face_bond)
    positive(calc, face_bond=face_bond)
    non_negative(calc, preco_bond_pct_par=preco_bond_pct_par, face_pari_passu_outros=face_pari_passu_outros,
                 face_senior=face_senior, face_junior=face_junior)

    nivel = face_bond + face_pari_passu_outros
    p = preco_bond_pct_par / 100.0
    if p < 1.0:
        ev = face_senior + p * nivel
        equity = 0.0
        piso = False
        rec_junior = 0.0
    else:
        ev = face_senior + nivel          # piso
        equity = None                     # indeterminado
        piso = True
        rec_junior = None

    total_divida = face_senior + nivel + face_junior
    out = {
        "ev_implicito_bond": ev,
        "ev_e_apenas_piso": piso,
        "recuperacao_nivel_bond_pct": min(preco_bond_pct_par, 100.0),
        "recuperacao_junior_pct": rec_junior,
        "equity_implicito": equity,
        "haircut_implicito_total": (1 - ev / total_divida) if (total_divida and not piso) else None,
    }
    notas = ["Assume preco = recuperacao esperada (sem desconto temporal, sem premio de risco). "
             "Se o bond paga cupom e o plano e longo, a recuperacao nominal e maior que o preco."]
    return Result(calc, inputs={
        "preco_bond_pct_par": preco_bond_pct_par, "face_bond": face_bond,
        "face_pari_passu_outros": face_pari_passu_outros, "face_senior": face_senior, "face_junior": face_junior,
    }, outputs=out, notas=notas)


def cross_check_bond_vs_equity(
    market_cap: float,
    divida_bruta_total: float,
    caixa: float,
    preco_bond_pct_par: float,
    face_bond: float,
    face_pari_passu_outros: float = 0.0,
    face_senior: float = 0.0,
    face_junior: float = 0.0,
) -> Result:
    """
    Compara o EV visto pelo equity (MC + divida bruta a valor de face - caixa) com o EV
    visto pelo bond (implied_ev_from_bond). A diferenca e o que precisa ser explicado.

    Caso tipico (Raizen/SPX): bond < 60 e market cap > 0. Sob prioridade absoluta o
    equity vale zero; o MC positivo e o "premio" que alguem esta pagando por opcao,
    voto ou expectativa de quebra de prioridade (conversao com diluicao negociada).
    """
    calc = "capital_structure.cross_check_bond_vs_equity"
    require(calc, market_cap=market_cap, divida_bruta_total=divida_bruta_total, caixa=caixa,
            preco_bond_pct_par=preco_bond_pct_par, face_bond=face_bond)
    ev_eq = enterprise_value(market_cap, divida_bruta_total, caixa)
    ev_bd = implied_ev_from_bond(preco_bond_pct_par, face_bond, face_pari_passu_outros, face_senior, face_junior)

    ev_equity_view = ev_eq.outputs["ev"]
    ev_bond_view = ev_bd.outputs["ev_implicito_bond"]
    gap = ev_equity_view - ev_bond_view
    out = {
        "ev_visao_equity": ev_equity_view,
        "ev_visao_bond": ev_bond_view,
        "gap_equity_menos_bond": gap,
        "gap_pct_do_ev_bond": (gap / ev_bond_view) if ev_bond_view else None,
        "recuperacao_bond_pct": ev_bd.outputs["recuperacao_nivel_bond_pct"],
        "mc_a_explicar_se_apr": market_cap if preco_bond_pct_par < 100 else 0.0,
        "mc_sobre_face_nivel_bond": market_cap / (face_bond + face_pari_passu_outros),
    }
    checks = [
        Check("divida_total_cobre_tranches",
              divida_bruta_total + 1e-6 >= face_senior + face_bond + face_pari_passu_outros + face_junior,
              "divida bruta total deve ser >= soma das tranches informadas"),
    ]
    notas = list(ev_bd.notas)
    if preco_bond_pct_par < 100 and market_cap > 0:
        notas.append("Inconsistencia a explicar: bond abaixo do par (equity deveria valer ~0 sob prioridade absoluta) "
                     "mas MC > 0. Hipoteses a testar: (1) opcao barata sobre recuperacao; (2) posicao para votar em AGE "
                     "(diluicao/conversao precisa de assembleia se exceder capital autorizado); (3) complemento de posicao "
                     "em bond; (4) expectativa de new money/quebra de prioridade; (5) bond ilíquido mal precificado.")
    return Result(calc, inputs={
        "market_cap": market_cap, "divida_bruta_total": divida_bruta_total, "caixa": caixa,
        "preco_bond_pct_par": preco_bond_pct_par, "face_bond": face_bond,
        "face_pari_passu_outros": face_pari_passu_outros, "face_senior": face_senior, "face_junior": face_junior,
    }, outputs=out, checks=checks, notas=notas)

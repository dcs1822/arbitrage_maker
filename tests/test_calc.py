"""Testes do motor determinístico (valores conferidos à mão)."""
import pytest

from arbmaker.calc import MissingInput, annualize, days_between
from arbmaker.calc import capital_structure as cs
from arbmaker.calc import conversion, parity, tender, capital_ops, merger
from arbmaker.calc.capital_structure import Claim


def approx(x, rel=1e-6):
    return pytest.approx(x, rel=rel)


# ---------------------------------------------------------------- core
def test_annualize_and_days():
    assert annualize(0.10, 365) == approx(0.10)
    assert annualize(0.10, 182.5) == approx(0.21)
    assert days_between("2026-01-01", "2026-07-01") == 181
    with pytest.raises(ValueError):
        annualize(0.1, 0)


# ---------------------------------------------------------------- capital_structure
def test_market_cap_multiclass():
    r = cs.market_cap({"ON": 100, "PN": 50}, {"ON": 10.0, "PN": 8.0})
    assert r.outputs["market_cap"] == approx(1400.0)
    assert r.outputs["total_acoes"] == 150
    assert r.ok


def test_market_cap_missing_price_raises():
    with pytest.raises(MissingInput) as e:
        cs.market_cap({"ON": 100, "PN": 50}, {"ON": 10.0})
    assert "preco_PN" in str(e.value)


def test_enterprise_value():
    r = cs.enterprise_value(1400.0, 500.0, 300.0)
    assert r.outputs["ev"] == approx(1600.0)
    assert r.outputs["divida_liquida"] == approx(200.0)
    assert r.ok


def test_waterfall_absolute_priority():
    claims = [Claim("senior", 600, 1), Claim("bond", 800, 2, preco_pct_par=40.0), Claim("sub", 200, 3)]
    r = cs.waterfall(1000.0, claims)
    t = {x["nome"]: x for x in r.outputs["tranches"]}
    assert t["senior"]["recuperacao_pct_par"] == approx(100.0)
    assert t["bond"]["recuperacao_pct_par"] == approx(50.0)
    assert t["bond"]["mercado_vs_waterfall_pp"] == approx(-10.0)
    assert t["sub"]["recuperacao"] == approx(0.0)
    assert r.outputs["equity_residual"] == approx(0.0)
    assert r.ok


def test_waterfall_pari_passu_and_equity_residual():
    r = cs.waterfall(500.0, [Claim("A", 400, 1), Claim("B", 400, 1)])
    t = {x["nome"]: x for x in r.outputs["tranches"]}
    assert t["A"]["recuperacao"] == approx(250.0)
    assert t["B"]["recuperacao_pct_par"] == approx(62.5)
    r2 = cs.waterfall(2000.0, [Claim("A", 600, 1), Claim("B", 1000, 2)])
    assert r2.outputs["equity_residual"] == approx(400.0)
    assert r2.ok


def test_implied_ev_from_bond():
    r = cs.implied_ev_from_bond(40.0, 1000.0, face_senior=500.0)
    assert r.outputs["ev_implicito_bond"] == approx(900.0)
    assert r.outputs["equity_implicito"] == 0.0
    assert r.outputs["haircut_implicito_total"] == approx(0.4)
    r2 = cs.implied_ev_from_bond(105.0, 1000.0, face_senior=500.0)
    assert r2.outputs["ev_e_apenas_piso"] is True
    assert r2.outputs["ev_implicito_bond"] == approx(1500.0)


def test_cross_check_bond_vs_equity():
    r = cs.cross_check_bond_vs_equity(market_cap=200.0, divida_bruta_total=1500.0, caixa=100.0,
                                      preco_bond_pct_par=40.0, face_bond=1000.0, face_senior=500.0)
    assert r.outputs["ev_visao_equity"] == approx(1600.0)
    assert r.outputs["ev_visao_bond"] == approx(900.0)
    assert r.outputs["gap_equity_menos_bond"] == approx(700.0)
    assert r.outputs["mc_a_explicar_se_apr"] == approx(200.0)
    assert any("Inconsistencia" in n for n in r.notas)
    assert r.ok


# ---------------------------------------------------------------- conversion
def test_debt_to_equity_basic():
    r = conversion.debt_to_equity(1000.0, 2.0, 1000, 2.5)
    o = r.outputs
    assert o["acoes_novas"] == approx(500.0)
    assert o["stake_credores_pct"] == approx(33.33, rel=1e-3)
    assert o["diluicao_acionistas_atuais_pct"] == approx(33.33, rel=1e-3)
    assert o["premio_preco_conversao_vs_mercado_pct"] == approx(-20.0)
    assert o["preco_bond_implicito_pelo_equity_pct_par"] == approx(125.0)
    assert r.ok


def test_debt_to_equity_haircut_parcela_and_bond_price():
    r = conversion.debt_to_equity(1000.0, 2.0, 1000, 2.5, haircut_pct=30, parcela_convertida_pct=50)
    assert r.outputs["divida_convertida"] == approx(350.0)
    assert r.outputs["acoes_novas"] == approx(175.0)
    r2 = conversion.debt_to_equity(1000.0, 2.0, 1000, 2.5, preco_bond_pct_par=40.0)
    assert r2.outputs["preco_acao_breakeven"] == approx(0.8)
    assert r2.outputs["caminho_mais_barato"] == "divida"
    assert r2.outputs["desconto_via_divida_pct"] == approx(68.0)


def test_debt_to_equity_capital_autorizado_check():
    r = conversion.debt_to_equity(1000.0, 2.0, 1000, 2.5, capital_autorizado_acoes=1200)
    assert not r.ok
    assert any(c.nome == "cabe_no_capital_autorizado" and not c.ok for c in r.checks)


# ---------------------------------------------------------------- parity
def test_class_parity():
    r = parity.class_parity(10.0, 9.0)
    assert r.outputs["premio_a_sobre_b_pct"] == approx(11.11, rel=1e-3)
    assert r.outputs["perna_vendida"] == "A"
    r2 = parity.class_parity(10.0, 9.0, dias=365, aluguel_a_aa_pct=5.0)
    assert r2.outputs["custo_aluguel_periodo"] == approx(0.5)
    assert r2.outputs["spread_liquido_por_par"] == approx(0.5)
    assert r2.outputs["retorno_liquido_pct"] == approx(5.56, rel=1e-3)
    assert r2.ok


def test_unit_parity():
    r = parity.unit_parity(30.0, {"ON": 1, "PN": 2}, {"ON": 10.0, "PN": 9.5})
    assert r.outputs["preco_teorico_unit"] == approx(29.0)
    assert r.outputs["premio_unit_pct"] == approx(3.45, rel=1e-3)
    assert r.outputs["direcao"].startswith("comprar cesta")


# ---------------------------------------------------------------- tender
def test_opa_spread():
    r = tender.opa_spread(9.0, 10.0, "2026-01-01", "2026-07-01")
    assert r.outputs["dias_ate_liquidacao"] == 181
    assert r.outputs["spread_bruto_pct"] == approx(11.11, rel=1e-3)
    assert r.outputs["spread_anualizado_pct"] == approx(23.70, rel=1e-2)
    r2 = tender.opa_spread(9.0, 10.0, "2026-01-01", "2026-07-01", prob_sucesso=0.8, preco_sem_oferta=7.0)
    assert r2.outputs["preco_esperado"] == approx(9.4)
    assert r2.outputs["prob_breakeven_implicita_pct"] == approx(66.67, rel=1e-3)
    assert r2.ok


def test_tag_along_and_recesso():
    r = tender.tag_along_price(12.0, 80.0, preco_mercado=8.0)
    assert r.outputs["preco_minimo_opa"] == approx(9.6)
    assert r.outputs["premio_vs_mercado_pct"] == approx(20.0)
    r2 = tender.recesso(12.0, 10.0)
    assert r2.outputs["premio_recesso_pct"] == approx(20.0)
    assert r2.outputs["vale_recesso"] is True


# ---------------------------------------------------------------- capital_ops
def test_terp():
    r = capital_ops.terp(10.0, 1000, 500, 7.0)
    assert r.outputs["terp"] == approx(9.0)
    assert r.outputs["valor_direito_por_acao_nova"] == approx(2.0)
    assert r.outputs["valor_direito_por_acao_antiga"] == approx(1.0)
    assert r.outputs["diluicao_quem_nao_subscreve_pct"] == approx(33.33, rel=1e-3)
    assert r.ok


def test_capital_reduction_westwing_numbers():
    r = capital_ops.capital_reduction(60_000_000, 11_109_348, 6.72, 121_348_000)
    assert r.outputs["restituicao_por_acao"] == approx(5.4009, rel=1e-4)
    assert r.outputs["restituicao_sobre_preco_pct"] == approx(80.37, rel=1e-3)
    assert r.outputs["caixa_pos"] == approx(61_348_000)
    assert r.ok
    assert any("divida_bruta nao informada" in n for n in r.notas)


def test_cash_vs_market_cap_requires_debt():
    r = capital_ops.cash_vs_market_cap(121_348_000, 0, 74_654_818)
    assert r.outputs["caixa_liquido_maior_que_mc"] is True
    with pytest.raises(MissingInput):
        capital_ops.cash_vs_market_cap(121_348_000, None, 74_654_818)


# ---------------------------------------------------------------- merger
def test_exchange_ratio():
    r = merger.exchange_ratio(20.0, 9.0, 0.5)
    assert r.outputs["preco_implicito_alvo"] == approx(10.0)
    assert r.outputs["spread_bruto_pct"] == approx(11.11, rel=1e-3)
    r2 = merger.exchange_ratio(20.0, 9.0, 0.5, data_ref="2026-01-01", data_fechamento="2026-07-01",
                               prob_sucesso=0.5, preco_alvo_sem_deal=8.0)
    assert r2.outputs["preco_esperado_alvo"] == approx(9.0)
    assert r2.outputs["prob_breakeven_implicita_pct"] == approx(50.0)


def test_render_and_sources():
    r = capital_ops.capital_reduction(60_000_000, 11_109_348, 6.72, 121_348_000).with_sources(
        valor_restituido={"origem": "Fato Relevante 2026-03-22", "data": "2026-03-22"})
    txt = r.render()
    assert "capital_ops.capital_reduction" in txt and "Fato Relevante" in txt
    assert r.to_dict()["ok"] is True

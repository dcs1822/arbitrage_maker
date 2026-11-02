"""Testes offline do conector CVM com CSV sintetico no formato oficial."""
import pandas as pd

from arbmaker.sources import cvm_open_data as cvm

COLS_BAL = ["CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM", "GRUPO_DFP", "MOEDA", "ESCALA_MOEDA",
            "ORDEM_EXERC", "DT_FIM_EXERC", "CD_CONTA", "DS_CONTA", "VL_CONTA", "ST_CONTA_FIXA"]
COLS_DRE = COLS_BAL[:9] + ["DT_INI_EXERC"] + COLS_BAL[9:]


def _row(cols, dt_refer, conta, valor, versao="1", escala="MIL", dt_ini=None, ordem="ÚLTIMO"):
    base = {"CNPJ_CIA": "00.000.000/0001-00", "DT_REFER": dt_refer, "VERSAO": versao, "DENOM_CIA": "TESTE S.A.",
            "CD_CVM": "25518", "GRUPO_DFP": "x", "MOEDA": "REAL", "ESCALA_MOEDA": escala, "ORDEM_EXERC": ordem,
            "DT_FIM_EXERC": dt_refer, "CD_CONTA": conta, "DS_CONTA": "d", "VL_CONTA": str(valor), "ST_CONTA_FIXA": "S"}
    if "DT_INI_EXERC" in cols:
        base["DT_INI_EXERC"] = dt_ini or dt_refer[:4] + "-01-01"
    return {c: base[c] for c in cols}


def test_extract_financials_dfp_with_reapresentacao_and_scale():
    bpa = pd.DataFrame([
        _row(COLS_BAL, "2025-12-31", "1.01.01", 100000),
        _row(COLS_BAL, "2025-12-31", "1.01.02", 20000),
        _row(COLS_BAL, "2025-12-31", "1.01.01", 999, versao="1"),          # duplicata v1
        _row(COLS_BAL, "2025-12-31", "1.01.01", 110000, versao="2"),       # reapresentacao vence
        _row(COLS_BAL, "2025-12-31", "1.01.01", 5, ordem="PENÚLTIMO"),     # ignorado
    ])
    bpp = pd.DataFrame([
        _row(COLS_BAL, "2025-12-31", "2.01.04", 30000),
        _row(COLS_BAL, "2025-12-31", "2.01.04.03", 25000),
        _row(COLS_BAL, "2025-12-31", "2.02.01", 10000000, escala="UNIDADE"),   # 10.000 mil
        _row(COLS_BAL, "2025-12-31", "2.03", 220000),
    ])
    dre = pd.DataFrame([
        _row(COLS_DRE, "2025-12-31", "3.01", 150000),
        _row(COLS_DRE, "2025-12-31", "3.05", -20000),
        _row(COLS_DRE, "2025-12-31", "3.11", -25000),
    ])
    dva = pd.DataFrame([_row(COLS_DRE, "2025-12-31", "7.04.01", 8000)])
    dfc = pd.DataFrame([_row(COLS_DRE, "2025-12-31", "6.01", -15000)])

    recs = cvm.extract_financials({"BPA": bpa, "BPP": bpp, "DRE": dre, "DVA": dva, "DFC_MI": dfc}, "25518", "DFP")
    assert len(recs) == 1
    r = recs[0]
    assert r["periodo"] == "2025" and r["unidade"] == "R$ mil"
    b = r["balanco"]
    assert b["caixa_equivalentes"] == 110000          # versao 2 venceu
    assert b["caixa_total"] == 130000
    assert b["divida_bruta"] == 40000                 # 30.000 + 10.000 (UNIDADE -> mil)
    assert b["divida_bruta_ex_arrendamento"] == 15000
    assert r["dre"]["ebitda"] == -12000               # ebit -20.000 + D&A 8.000
    assert r["dre"]["lucro_liquido"] == -25000
    assert r["fluxo"]["fco"] == -15000


def test_extract_financials_itr_quarter_vs_accumulated():
    dre = pd.DataFrame([
        _row(COLS_DRE, "2025-06-30", "3.01", 40000, dt_ini="2025-04-01"),   # 2T isolado
        _row(COLS_DRE, "2025-06-30", "3.01", 75000, dt_ini="2025-01-01"),   # acumulado 1S
    ])
    recs = cvm.extract_financials({"DRE": dre}, 25518, "ITR")
    assert recs[0]["periodo"] == "2T25"
    assert recs[0]["dre"]["receita_liquida"] == 40000
    assert recs[0]["dre_acumulado"]["receita_liquida"] == 75000


def test_ipe_filter_participacao_relevante():
    df = pd.DataFrame({
        "Codigo_CVM": ["25518", "25518", "999"],
        "Categoria": ["Comunicado ao Mercado", "Fato Relevante", "Comunicado ao Mercado"],
        "Tipo": ["Comunicado sobre aquisição ou alienação de participação acionária relevante", "", "Outros"],
        "Assunto": ["Oriz Asset atinge 32,15%", "Redução de capital", "x"],
        "Link_Download": ["u1", "u2", "u3"],
    })
    d = cvm.ipe_filter(df, cd_cvm=25518, padroes=["participacao_relevante"])
    assert list(d["Link_Download"]) == ["u1"]
    d2 = cvm.ipe_filter(df, cd_cvm="025518", padroes=["reducao_capital", "participacao_relevante"])
    assert list(d2["Link_Download"]) == ["u1", "u2"]

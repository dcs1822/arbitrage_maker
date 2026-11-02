"""Testes offline do coletor (resolucao de CD_CVM pelo cadastro e nome de arquivo)."""
import pandas as pd
import pytest

from arbmaker.sources import rad_collect as rc
from arbmaker.universe_cases import EMPRESAS, Empresa

CAD = pd.DataFrame({
    "CNPJ_CIA": ["1", "2", "3", "4", "5"],
    "DENOM_SOCIAL": ["GETNINJAS S.A.", "CM HOSPITALAR S.A.", "ENERGISA S.A.", "ENERGISA MINAS GERAIS - DISTRIBUIDORA DE ENERGIA S.A.", "RAÍZEN S.A."],
    "SIT": ["ATIVO", "ATIVO", "ATIVO", "ATIVO", "ATIVO"],
    "CD_CVM": ["25000", "25001", "15253", "9999", "25002"],
})


def test_resolve_by_regex():
    assert rc.resolve_cd_cvm(EMPRESAS["getninjas"], CAD)[0] == "25000"
    assert rc.resolve_cd_cvm(EMPRESAS["viveo"], CAD)[0] == "25001"
    assert rc.resolve_cd_cvm(EMPRESAS["raizen"], CAD)[0] == "25002"       # acento normalizado


def test_resolve_known_code_and_ambiguity():
    cd, nome = rc.resolve_cd_cvm(EMPRESAS["energisa"], CAD)
    assert cd == "15253" and nome.startswith("ENERGISA S.A.")
    with pytest.raises(LookupError):
        rc.resolve_cd_cvm(Empresa("x", "x", r"ENERGISA", []), CAD)        # 2 hits -> ambiguo
    with pytest.raises(LookupError):
        rc.resolve_cd_cvm(Empresa("y", "y", r"NAO EXISTE", []), CAD)


def test_pdf_name_is_deterministic():
    row = pd.Series({"Data_Entrega": "2026-03-22", "Categoria": "Fato Relevante"})
    a = rc._pdf_name(row, "https://x/doc?1")
    assert a == rc._pdf_name(row, "https://x/doc?1") and a.startswith("20260322_Fato_Relevante_")

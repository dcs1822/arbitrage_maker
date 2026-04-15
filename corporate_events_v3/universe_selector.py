"""
universe_selector.py
====================
Seleciona o universo de empresas que sera processado pelo pipeline.

No incremento 2 trabalhamos com TARGET_UNIVERSE_SIZE empresas (default 20):
    - As listadas em config.TICKERS_CURADOS (escolha manual do analista)
    - + o restante sorteado do pool TIER 1+2 do Cadastro CVM

Cada empresa eh representada por um dict:
    {
        "cd_cvm": str | None,
        "denom":  str,
        "ticker": str | None,   # ticker representativo (so para curados)
        "fonte":  "curado" | "random",
    }
"""
from __future__ import annotations

import random
import pandas as pd

from . import config


# =========================================================================
# Mapeamento manual ticker -> CD_CVM para os curados.
# Construido a partir de cad_cia_aberta.csv em 2026-04-10.
# Se o usuario adicionar um ticker em TICKERS_CURADOS que nao esteja aqui,
# load_curados() vai marcar fonte_cd_cvm = None e o pipeline pula a empresa
# com aviso (em vez de quebrar).
# =========================================================================
CURADOS_MAP: dict[str, tuple[str | None, str]] = {
    "RENT3":  ("19739", "LOCALIZA RENT A CAR SA"),
    "RDNI3":  ("20451", "RNI NEGOCIOS IMOBILIARIOS S.A."),
    "TKNO4":  ("11231", "TEKNO S.A. INDUSTRIA E COMERCIO"),
    "WEST3":  ("25518", "WESTWING COMERCIO VAREJISTA S.A."),
    "SHOW3":  ("22454", "T4F ENTRETENIMENTO SA"),
    "ZAMP3":  ("24317", "ZAMP S.A."),
    "ATED3":  (None,    "ATED3 - PENDENTE (nao encontrado no cadastro)"),
    "ENGI11": ("15253", "ENERGISA SA"),
    "ALPA4":  ("10456", "ALPARGATAS SA"),
}


def load_curados() -> list[dict]:
    """Devolve os dicts das empresas curadas listadas em config.TICKERS_CURADOS."""
    out = []
    for tk in config.TICKERS_CURADOS:
        if tk not in CURADOS_MAP:
            out.append({
                "cd_cvm": None,
                "denom": f"{tk} - SEM MAPEAMENTO",
                "ticker": tk,
                "fonte": "curado",
            })
            continue
        cd, denom = CURADOS_MAP[tk]
        out.append({
            "cd_cvm": cd,
            "denom": denom,
            "ticker": tk,
            "fonte": "curado",
        })
    return out


def load_random_pool() -> pd.DataFrame:
    """
    Carrega o pool de empresas elegiveis para sorteio aleatorio.
    Hoje: TIER 1+2 do Cadastro CVM.xlsx (mantido manualmente pelo analista).
    """
    df = pd.read_excel(config.CADASTRO_CVM_XLSX)
    df.columns = [c.strip() for c in df.columns]

    # A coluna do codigo CVM vem com encoding meio quebrado as vezes
    cd_col = next((c for c in df.columns if "digo CVM" in c), None)
    if cd_col is None:
        raise RuntimeError(f"Coluna 'Codigo CVM' nao encontrada. Colunas: {list(df.columns)}")

    df = df.rename(columns={cd_col: "cd_cvm", "Nome Empresa": "denom", "TIER": "tier"})
    df["cd_cvm"] = (
        df["cd_cvm"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    )
    df["tier"] = df["tier"].astype(str).str.strip()
    df = df[df["tier"].isin(["1", "2"])].copy()
    df = df.dropna(subset=["cd_cvm", "denom"])
    return df[["cd_cvm", "denom", "tier"]].reset_index(drop=True)


def pick_random(n: int, exclude: set[str]) -> list[dict]:
    """Sorteio reproducivel (RANDOM_SEED) de n empresas do pool, excluindo as ja usadas."""
    pool = load_random_pool()
    pool = pool[~pool["cd_cvm"].isin(exclude)].reset_index(drop=True)
    if len(pool) < n:
        raise ValueError(f"Pool insuficiente: {len(pool)} disponiveis, {n} pedidas")
    rng = random.Random(config.RANDOM_SEED)
    indices = rng.sample(range(len(pool)), n)
    out = []
    for i in indices:
        row = pool.iloc[i]
        out.append({
            "cd_cvm": row["cd_cvm"],
            "denom": row["denom"],
            "ticker": None,
            "fonte": "random",
        })
    return out


def build_universe() -> list[dict]:
    """
    Monta o universo de teste:
        - todos os curados
        - + (TARGET_UNIVERSE_SIZE - len(curados)) sorteados do pool

    Se faltar mapeamento de algum curado, ele entra mas com cd_cvm=None
    (pipeline pula com aviso, sem quebrar).
    """
    curados = load_curados()
    excl = {c["cd_cvm"] for c in curados if c["cd_cvm"]}
    n_random = max(0, config.TARGET_UNIVERSE_SIZE - len(curados))
    randoms = pick_random(n_random, excl) if n_random else []
    return curados + randoms

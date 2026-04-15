"""
universe.py — Carregamento e parsing do universo investível.

Fonte primária: arquivo Bloomberg em config.BLOOMBERG_TICKERS_PATH.
Estrutura esperada do arquivo:

    Ticker
    [linha em branco]
    Tudo_Brasil
    PETR4 BZ
    VALE3 BZ
    PBR US
    ...

Saída: DataFrame enriquecido com root, classe e tipo de papel.
A ponte ticker → CD_CVM e o filtro de market cap são tratados
em módulos separados (próximos incrementos).
"""
from pathlib import Path
import pandas as pd

from . import config

# Mapa do digito de classe ao tipo de papel na B3
TIPO_PAPEL = {
    1:  "DIREITO_ON",
    2:  "DIREITO_PN",
    3:  "ON",
    4:  "PN",
    5:  "PNA",
    6:  "PNB",
    7:  "PNC",
    8:  "PND",
    9:  "RECIBO_SUBSCR_ON",
    10: "RECIBO_SUBSCR_PN",
    11: "UNIT_OU_FII",        # ambiguo - desambiguacao no modulo de fundamentals
    12: "BDR_NIVEL_2",
    13: "BDR_NIVEL_3",
    31: "BDR",
    32: "BDR",
    33: "BDR",
    34: "BDR",
    35: "BDR",
    39: "BDR",
}

# Linhas que devem ser ignoradas (cabeçalhos / labels do arquivo Bloomberg)
SKIP_LINES = {"Ticker", "Tudo_Brasil"}


def load_raw_tickers(path: Path | None = None) -> pd.DataFrame:
    """Lê o arquivo Bloomberg e retorna DataFrame cru com ticker e exchange."""
    p = Path(path or config.BLOOMBERG_TICKERS_PATH)
    rows = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line in SKIP_LINES:
                continue
            parts = line.split()
            if len(parts) != 2:
                continue
            ticker, exch = parts
            rows.append({"raw": line, "ticker": ticker, "exchange": exch})
    return pd.DataFrame(rows)


def parse_ticker(ticker: str) -> dict:
    """
    Quebra um ticker brasileiro em (root, class_num, suffix, tipo).

    Estrategia: peeling da direita.
        1. Se termina em letra precedida de digito (ex: MRSA3B), separa o sufixo.
        2. Pega ate 2 digitos finais como classe.
        3. O que sobra, com pelo menos 1 letra, vira o root.

    Funciona para roots com digitos no meio: B3SA3, G2DI33, S2GM34.
    """
    s = ticker
    suffix = ""
    if len(s) > 2 and s[-1].isalpha() and s[-2].isdigit():
        suffix = s[-1]
        s = s[:-1]

    digits = ""
    while s and s[-1].isdigit() and len(digits) < 2:
        digits = s[-1] + digits
        s = s[:-1]

    if not digits or not s or not any(c.isalpha() for c in s):
        return {"root": ticker, "class_num": None, "suffix": "", "tipo": "DESCONHECIDO"}

    class_num = int(digits)
    return {
        "root": s,
        "class_num": class_num,
        "suffix": suffix,
        "tipo": TIPO_PAPEL.get(class_num, f"OUTRO_{class_num}"),
    }


def load_universe(path: Path | None = None) -> pd.DataFrame:
    """
    Universo enriquecido — uma linha por ticker.
    Aplica:
        - filtro por exchange (config.EXCHANGES_INVESTIBLE)
        - parsing de root/classe/tipo

    Filtros de market cap e FII/ação ficam para os próximos incrementos
    (precisam de dados fundamentalistas).
    """
    df = load_raw_tickers(path)
    df = df[df["exchange"].isin(config.EXCHANGES_INVESTIBLE)].copy()
    parsed = df["ticker"].apply(parse_ticker).apply(pd.Series)
    df = pd.concat([df.reset_index(drop=True), parsed.reset_index(drop=True)], axis=1)
    return df


def universe_summary(df: pd.DataFrame) -> dict:
    """Estatísticas resumidas do universo carregado."""
    return {
        "total_tickers": int(len(df)),
        "exchanges": df["exchange"].value_counts().to_dict(),
        "por_tipo": df["tipo"].value_counts().to_dict(),
        "roots_distintos": int(df["root"].nunique()),
    }


def log_unknowns(df: pd.DataFrame) -> int:
    """
    Salva tickers nao reconhecidos pelo parser num arquivo de auditoria
    em config.UNKNOWNS_LOG_PATH (acessivel via rede).
    Retorna a quantidade salva. Falhas no log nao quebram o pipeline.
    """
    unknowns = df[df["tipo"] == "DESCONHECIDO"]
    n = int(len(unknowns))
    if n == 0:
        return 0
    try:
        path = config.UNKNOWNS_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Tickers nao reconhecidos pelo parser - {n} entradas\n")
            f.write(f"# Gerado em: {pd.Timestamp.now().isoformat()}\n")
            f.write(f"# Fonte: {config.BLOOMBERG_TICKERS_PATH}\n\n")
            for _, r in unknowns.iterrows():
                f.write(f"{r['raw']}\n")
    except Exception:
        pass
    return n

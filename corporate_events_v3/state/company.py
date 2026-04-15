"""
state/company.py - CRUD do estado por empresa (tabela company_state).

API:
    upsert_company(cd_cvm, denom, ticker, fonte) -> None
    get_company(cd_cvm)                          -> dict | None
    all_companies()                              -> list[dict]
    initialize_from_universe(selecionados)       -> int  (qtd inseridas/atualizadas)
    update_metadata(cd_cvm, **fields)            -> None  (merge no metadata_json)
    set_flags(cd_cvm, flags: list[str])          -> None
    set_teses(cd_cvm, teses: list[dict])         -> None
"""
from __future__ import annotations

import json

from . import db


def _row_to_dict(row) -> dict:
    """Converte sqlite3.Row para dict, decodificando os campos JSON."""
    d = dict(row)
    d["flags"] = json.loads(d.pop("flags_json") or "[]")
    d["teses"] = json.loads(d.pop("teses_json") or "[]")
    d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
    return d


def upsert_company(
    cd_cvm: str,
    denom: str | None = None,
    ticker: str | None = None,
    fonte: str | None = None,
) -> None:
    """
    Insere ou atualiza uma empresa em company_state.
    Campos None nao sobrescrevem valores existentes (preserva o que ja foi setado).
    """
    if not cd_cvm:
        raise ValueError("cd_cvm obrigatorio")

    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT cd_cvm FROM company_state WHERE cd_cvm = ?",
            (cd_cvm,),
        ).fetchone()

        if existing:
            sets = []
            params: list = []
            if denom is not None:
                sets.append("denom = ?"); params.append(denom)
            if ticker is not None:
                sets.append("ticker = ?"); params.append(ticker)
            if fonte is not None:
                sets.append("fonte = ?"); params.append(fonte)
            sets.append("updated_at = ?"); params.append(db.now_iso())
            params.append(cd_cvm)
            conn.execute(
                f"UPDATE company_state SET {', '.join(sets)} WHERE cd_cvm = ?",
                params,
            )
        else:
            conn.execute(
                """
                INSERT INTO company_state
                    (cd_cvm, denom, ticker, fonte, flags_json, teses_json, metadata_json, updated_at)
                VALUES (?, ?, ?, ?, '[]', '[]', '{}', ?)
                """,
                (cd_cvm, denom, ticker, fonte, db.now_iso()),
            )


def get_company(cd_cvm: str) -> dict | None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM company_state WHERE cd_cvm = ?",
            (cd_cvm,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def all_companies() -> list[dict]:
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM company_state ORDER BY denom"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def initialize_from_universe(selecionados: list[dict]) -> int:
    """
    Garante que toda empresa do universo selecionado existe na company_state.
    Devolve quantas foram inseridas/atualizadas.
    Pula entradas com cd_cvm None (curados sem mapeamento).
    """
    n = 0
    for s in selecionados:
        cd = s.get("cd_cvm")
        if not cd:
            continue
        upsert_company(
            cd_cvm=cd,
            denom=s.get("denom"),
            ticker=s.get("ticker"),
            fonte=s.get("fonte"),
        )
        n += 1
    return n


def update_metadata(cd_cvm: str, **fields) -> None:
    """
    Faz merge no campo metadata_json (caixa, divida, free_float, MC, etc).
    Ex: update_metadata('25518', caixa=120e6, divida=10e6, mc=80e6)
    """
    cur = get_company(cd_cvm)
    if cur is None:
        raise ValueError(f"cd_cvm {cd_cvm} nao existe em company_state")
    meta = cur["metadata"]
    meta.update(fields)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE company_state SET metadata_json = ?, updated_at = ? WHERE cd_cvm = ?",
            (json.dumps(meta, ensure_ascii=False), db.now_iso(), cd_cvm),
        )


def set_flags(cd_cvm: str, flags: list[str]) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE company_state SET flags_json = ?, updated_at = ? WHERE cd_cvm = ?",
            (json.dumps(flags, ensure_ascii=False), db.now_iso(), cd_cvm),
        )


def set_teses(cd_cvm: str, teses: list[dict]) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE company_state SET teses_json = ?, updated_at = ? WHERE cd_cvm = ?",
            (json.dumps(teses, ensure_ascii=False), db.now_iso(), cd_cvm),
        )


def touch_last_seen(cd_cvm: str, when_iso: str) -> None:
    """Atualiza last_seen_doc_at se a data for mais recente que a atual."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT last_seen_doc_at FROM company_state WHERE cd_cvm = ?",
            (cd_cvm,),
        ).fetchone()
        if row is None:
            return
        cur = row["last_seen_doc_at"]
        if cur is None or (when_iso and when_iso > cur):
            conn.execute(
                "UPDATE company_state SET last_seen_doc_at = ?, updated_at = ? WHERE cd_cvm = ?",
                (when_iso, db.now_iso(), cd_cvm),
            )


def context_snippet(cd_cvm: str) -> str:
    """
    Gera uma frase compacta com o contexto conhecido da empresa, para injetar
    no prompt do estagio 2. Ex:
        "WESTWING (25518) | MC=R$80mi, caixa=R$120mi [net-net] | flags: cash>mc"
    Quando nao ha dados, devolve so denom + cd_cvm.
    """
    c = get_company(cd_cvm)
    if c is None:
        return f"(sem contexto para cd_cvm {cd_cvm})"
    partes: list[str] = [f"{c.get('denom') or '-'} ({cd_cvm})"]
    meta = c.get("metadata") or {}
    campos: list[str] = []
    for k in ("mc", "caixa", "divida", "free_float", "controlador_pct"):
        v = meta.get(k)
        if v is not None:
            campos.append(f"{k}={v}")
    if campos:
        partes.append(" | ".join(campos))
    flags = c.get("flags") or []
    if flags:
        partes.append("flags: " + ", ".join(flags))
    teses = c.get("teses") or []
    if teses:
        nomes = []
        for t in teses:
            if isinstance(t, dict):
                nomes.append(str(t.get("nome") or t.get("titulo") or "tese"))
            else:
                nomes.append(str(t))
        partes.append("teses: " + ", ".join(nomes[:3]))
    return " | ".join(partes)

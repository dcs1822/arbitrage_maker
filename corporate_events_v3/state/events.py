"""
state/events.py - CRUD da tabela events e do triage_cache.

API events:
    event_exists(link_pdf)                          -> bool
    insert_event(...)                               -> int (id)
    update_triage(event_id, decision, reason)       -> None
    update_text_hash(event_id, text_hash)           -> None
    count_by_decision()                             -> dict[str, int]
    list_relevant(limit=50)                         -> list[dict]
    get_event(event_id)                             -> dict | None

API triage_cache:
    get_triage_cache(text_hash)                     -> dict | None
    set_triage_cache(text_hash, decision, reason, model) -> None
"""
from __future__ import annotations

from . import db


# =====================================================================
# events
# =====================================================================

def event_exists(link_pdf: str) -> bool:
    """Verifica se um link ja foi processado (deduplicacao)."""
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT 1 FROM events WHERE link_pdf = ? LIMIT 1",
            (link_pdf,),
        ).fetchone()
    return row is not None


def insert_event(
    cd_cvm: str,
    denom: str | None,
    ticker: str | None,
    categoria: str | None,
    data_documento: str | None,
    link_pdf: str,
    pdf_path: str | None,
    fonte: str | None,
) -> int:
    """Insere um evento na fase de download. Estagios posteriores fazem UPDATE."""
    ts = db.now_iso()
    with db.transaction() as conn:
        cur = conn.execute(
            """
            INSERT INTO events
                (cd_cvm, denom, ticker, categoria, data_documento,
                 link_pdf, pdf_path, fonte, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (cd_cvm, denom, ticker, categoria, data_documento,
             link_pdf, pdf_path, fonte, ts, ts),
        )
        return int(cur.lastrowid)


def update_text_hash(event_id: int, text_hash: str) -> None:
    with db.transaction() as conn:
        conn.execute(
            "UPDATE events SET text_hash = ?, updated_at = ? WHERE id = ?",
            (text_hash, db.now_iso(), event_id),
        )


def update_triage(event_id: int, decision: str, reason: str | None) -> None:
    with db.transaction() as conn:
        conn.execute(
            """
            UPDATE events
            SET triage_decision = ?, triage_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (decision, reason, db.now_iso(), event_id),
        )


def count_by_decision() -> dict[str, int]:
    """Conta eventos por triage_decision (incluindo NULL = ainda nao triado)."""
    out: dict[str, int] = {"relevante": 0, "descartar": 0, "pendente": 0}
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(triage_decision, 'pendente') AS d, COUNT(*) AS n
            FROM events GROUP BY d
            """
        ).fetchall()
    for r in rows:
        out[r["d"]] = int(r["n"])
    return out


def list_relevant(limit: int = 50) -> list[dict]:
    """Lista eventos triados como relevantes, mais recentes primeiro."""
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT id, cd_cvm, denom, ticker, categoria, data_documento,
                   triage_reason, link_pdf
            FROM events
            WHERE triage_decision = 'relevante'
            ORDER BY data_documento DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_event(event_id: int) -> dict | None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,)
        ).fetchone()
    return dict(row) if row else None


def list_pending_deep(limit: int = 100) -> list[dict]:
    """
    Lista eventos triados como relevantes que ainda nao passaram pelo estagio 2
    (deep_analysis_json IS NULL). Mais recentes primeiro.
    """
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT id, cd_cvm, denom, ticker, categoria, data_documento,
                   link_pdf, pdf_path, triage_reason, fonte
            FROM events
            WHERE triage_decision = 'relevante'
              AND deep_analysis_json IS NULL
            ORDER BY data_documento DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_deep_analysis(
    event_id: int,
    analysis_json: str,
    severidade: int | None,
    urgencia: str | None,
    tipo_evento: str | None,
    flags_json: str | None,
) -> None:
    """Grava o resultado do estagio 2 (deep analyzer)."""
    with db.transaction() as conn:
        conn.execute(
            """
            UPDATE events
            SET deep_analysis_json = ?,
                severidade = ?,
                urgencia = ?,
                tipo_evento = ?,
                flags_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (analysis_json, severidade, urgencia, tipo_evento,
             flags_json, db.now_iso(), event_id),
        )


def top_by_severity(limit: int = 20) -> list[dict]:
    """Lista eventos com deep analysis ordenados por severidade desc."""
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT id, cd_cvm, denom, ticker, categoria, data_documento,
                   severidade, urgencia, tipo_evento, triage_reason,
                   deep_analysis_json
            FROM events
            WHERE deep_analysis_json IS NOT NULL
            ORDER BY severidade DESC, data_documento DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# =====================================================================
# triage_cache
# =====================================================================

def get_triage_cache(text_hash: str) -> dict | None:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM triage_cache WHERE text_hash = ?",
            (text_hash,),
        ).fetchone()
    return dict(row) if row else None


def set_triage_cache(
    text_hash: str,
    decision: str,
    reason: str | None,
    model: str | None,
) -> None:
    """Insere ou substitui entrada do cache (REPLACE = idempotente)."""
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO triage_cache
                (text_hash, decision, reason, model, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (text_hash, decision, reason, model, db.now_iso()),
        )

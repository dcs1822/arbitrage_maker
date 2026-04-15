"""
state/db.py - Camada de banco SQLite.

Responsabilidades:
    - Conectar / criar schema
    - Helpers transacionais
    - Utilitarios genericos (timestamp, hash de texto)

Schema (4 tabelas):
    company_state  - snapshot por empresa (1 linha por CD_CVM)
    events         - 1 linha por documento processado
    triage_cache   - cache de decisao de triagem por hash de texto
    runs           - log de execucoes do pipeline diario
"""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from .. import config


SCHEMA = """
-- =====================================================================
-- company_state: snapshot agregado por empresa
-- =====================================================================
CREATE TABLE IF NOT EXISTS company_state (
    cd_cvm           TEXT PRIMARY KEY,
    denom            TEXT,
    ticker           TEXT,
    fonte            TEXT,           -- 'curado' | 'random'
    last_seen_doc_at TEXT,           -- ISO timestamp do ultimo doc visto
    flags_json       TEXT NOT NULL DEFAULT '[]',   -- flags ativas (lista)
    teses_json       TEXT NOT NULL DEFAULT '[]',   -- teses em aberto (lista)
    metadata_json    TEXT NOT NULL DEFAULT '{}',   -- caixa, divida, free_float, etc
    updated_at       TEXT NOT NULL
);

-- =====================================================================
-- events: 1 linha por documento processado pelo pipeline
-- =====================================================================
CREATE TABLE IF NOT EXISTS events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    cd_cvm              TEXT NOT NULL,
    denom               TEXT,
    ticker              TEXT,
    categoria           TEXT,
    data_documento      TEXT,
    link_pdf            TEXT UNIQUE,         -- link RAD/CVM e o id natural
    pdf_path            TEXT,
    text_hash           TEXT,
    triage_decision     TEXT,                -- 'relevante' | 'descartar'
    triage_reason       TEXT,
    deep_analysis_json  TEXT,                -- JSON estruturado do estagio 2
    severidade          INTEGER,             -- 1-10
    urgencia            TEXT,                -- 'alta' | 'media' | 'baixa'
    tipo_evento         TEXT,                -- 'opa' | 'aumento_cap' | ...
    flags_json          TEXT,                -- flags disparadas pela rules engine
    fonte               TEXT,                -- 'curado' | 'random'
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_cd_cvm     ON events(cd_cvm);
CREATE INDEX IF NOT EXISTS idx_events_data_doc   ON events(data_documento);
CREATE INDEX IF NOT EXISTS idx_events_severidade ON events(severidade);
CREATE INDEX IF NOT EXISTS idx_events_text_hash  ON events(text_hash);

-- =====================================================================
-- triage_cache: evita pagar LLM duas vezes pelo mesmo doc
-- =====================================================================
CREATE TABLE IF NOT EXISTS triage_cache (
    text_hash   TEXT PRIMARY KEY,
    decision    TEXT NOT NULL,
    reason      TEXT,
    model       TEXT,
    created_at  TEXT NOT NULL
);

-- =====================================================================
-- runs: log de execucoes do pipeline diario
-- =====================================================================
CREATE TABLE IF NOT EXISTS runs (
    run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    status            TEXT,                  -- 'ok' | 'erro' | 'em_andamento'
    docs_baixados     INTEGER DEFAULT 0,
    docs_triados      INTEGER DEFAULT 0,
    docs_aprofundados INTEGER DEFAULT 0,
    eventos_high      INTEGER DEFAULT 0,
    eventos_medium    INTEGER DEFAULT 0,
    eventos_low       INTEGER DEFAULT 0,
    erros             TEXT
);
"""


def get_connection() -> sqlite3.Connection:
    """Abre conexao SQLite com row_factory para acesso por nome de coluna."""
    config.ensure_dirs()
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Cria todas as tabelas se nao existirem. Idempotente."""
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Context manager: commita no sucesso, faz rollback no erro, sempre fecha."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_iso() -> str:
    """Timestamp ISO sem microssegundos, para colunas TEXT."""
    return datetime.now().isoformat(timespec="seconds")


def text_hash(text: str) -> str:
    """SHA1 do texto normalizado, para cache de triagem."""
    norm = " ".join((text or "").split()).lower()
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def table_counts() -> dict[str, int]:
    """Devolve quantas linhas existem em cada tabela. Util para debug."""
    out = {}
    with transaction() as conn:
        for tbl in ("company_state", "events", "triage_cache", "runs"):
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {tbl}").fetchone()
            out[tbl] = int(row["n"])
    return out

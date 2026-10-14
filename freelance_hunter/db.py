"""Persistência em SQLite: evita notificar/rascunhar a mesma vaga duas vezes."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .models import Job, Score

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key           TEXT PRIMARY KEY,           -- plataforma:id
    platform      TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT NOT NULL,
    url           TEXT NOT NULL,
    budget_min    REAL,
    budget_max    REAL,
    budget_raw    TEXT,
    is_hourly     INTEGER DEFAULT 0,
    skills        TEXT DEFAULT '[]',
    score         INTEGER,
    score_json    TEXT,
    status        TEXT NOT NULL DEFAULT 'nova',
    proposta      TEXT,                       -- rascunho para você copiar e colar
    checklist     TEXT DEFAULT '[]',
    valor_fechado REAL,
    prazo         TEXT,
    notificado    INTEGER DEFAULT 0,
    first_seen    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_seen ON jobs(first_seen);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS fetch_log (
    source TEXT NOT NULL, ts REAL NOT NULL, ok INTEGER NOT NULL, info TEXT
);
"""


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---------- vagas ----------
    def is_known(self, key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM jobs WHERE key=?", (key,)).fetchone() is not None

    def insert_job(self, job: Job, score: Score) -> None:
        now = time.time()
        status = "nova" if score.total > 0 else "descartada"
        with self.tx() as c:
            c.execute(
                """INSERT OR IGNORE INTO jobs
                (key, platform, external_id, title, description, url, budget_min, budget_max,
                 budget_raw, is_hourly, skills, score, score_json, status, first_seen, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job.key, job.platform, job.external_id, job.title, job.description, job.url,
                 job.budget_min, job.budget_max, job.budget_raw, int(job.is_hourly),
                 json.dumps(job.skills, ensure_ascii=False), score.total,
                 json.dumps(score.__dict__, ensure_ascii=False), status, now, now),
            )

    def update_job(self, key: str, **fields) -> None:
        if not fields:
            return
        for k in ("checklist",):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE jobs SET {cols} WHERE key=?", (*fields.values(), key))

    def get_job(self, key: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()

    def find_job(self, ref: str) -> sqlite3.Row | None:
        """Aceita a chave completa ou o rowid curto mostrado no Telegram (#12)."""
        ref = ref.lstrip("#")
        if ref.isdigit():
            row = self.conn.execute("SELECT * FROM jobs WHERE rowid=?", (int(ref),)).fetchone()
            if row:
                return row
        return self.get_job(ref)

    def short_id(self, key: str) -> int:
        return self.conn.execute("SELECT rowid FROM jobs WHERE key=?", (key,)).fetchone()[0]

    def jobs_by_status(self, *status: str) -> list[sqlite3.Row]:
        q = ",".join("?" * len(status))
        return self.conn.execute(
            f"SELECT rowid AS sid, * FROM jobs WHERE status IN ({q}) ORDER BY score DESC, updated_at DESC",
            status,
        ).fetchall()

    def pending_notifications(self, min_score: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT rowid AS sid, * FROM jobs WHERE status='nova' AND notificado=0 AND score>=? "
            "ORDER BY score DESC",
            (min_score,),
        ).fetchall()

    def jobs_since(self, ts: float) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs WHERE first_seen>=?", (ts,)).fetchall()

    def counts(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    # ---------- configurações / log ----------
    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?,?)", (key, value))

    def log_fetch(self, source: str, ok: bool, info: str = "") -> None:
        with self.tx() as c:
            c.execute("INSERT INTO fetch_log VALUES (?,?,?,?)", (source, time.time(), int(ok), info[:500]))

    def last_fetch(self, source: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM fetch_log WHERE source=? ORDER BY ts DESC LIMIT 1", (source,)
        ).fetchone()

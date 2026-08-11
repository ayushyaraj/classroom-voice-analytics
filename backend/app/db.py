"""SQLite persistence for jobs, segments, metrics, and session metadata.

One connection per call site via connect(). WAL mode lets the worker write
segments while API requests read progress. All writes commit immediately so a
crashed worker resumes from the last persisted stage instead of restarting.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from app.config import DB_PATH

# Job lifecycle states, in order. failed can happen from any stage.
JOB_STATES = (
    "queued",
    "preprocessing",
    "transcribing",
    "analyzing",
    "done",
    "failed",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT,                  -- last stage that completed, for resume
    error TEXT,
    error_stage TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    original_filename TEXT,
    audio_path TEXT,             -- uploaded file as stored on disk
    wav_path TEXT,               -- preprocessed 16 kHz mono wav
    photo_path TEXT,             -- optional classroom photo attachment
    language TEXT NOT NULL DEFAULT 'mr',
    model_size TEXT NOT NULL DEFAULT 'medium',
    student_count INTEGER,
    duration_seconds REAL,
    progress REAL NOT NULL DEFAULT 0.0,   -- seconds processed / total seconds
    compute_type TEXT,           -- int8 or float16, which path actually ran
    detected_language TEXT,
    language_notice TEXT,        -- non-blocking mismatch notice for the UI
    warnings TEXT                -- JSON list of warning strings
);

CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    start REAL NOT NULL,
    end REAL NOT NULL,
    text TEXT NOT NULL,
    speaker TEXT,                -- TEACHER or STUDENT, nullable until analyzed
    speaker_confidence REAL,
    speaker_source TEXT,         -- cluster, lexicon, choral, manual
    is_question INTEGER NOT NULL DEFAULT 0,
    features TEXT                -- JSON: f0, rms, duration, words, rate
);
CREATE INDEX IF NOT EXISTS idx_segments_job ON segments(job_id, start);

CREATE TABLE IF NOT EXISTS metrics (
    job_id TEXT NOT NULL REFERENCES jobs(id),
    name TEXT NOT NULL,
    value REAL,
    extra TEXT,                  -- JSON for non-scalar values (timeline etc.)
    PRIMARY KEY (job_id, name)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    ts REAL NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, id);

CREATE TABLE IF NOT EXISTS session_metadata (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id),
    data TEXT NOT NULL,          -- JSON of the SessionMetadata dataclass
    unmapped_keys TEXT,          -- JSON list of keys the alias map missed
    warnings TEXT                -- JSON list of parse/reconciliation warnings
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with WAL and row access by name."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


# --- jobs ---------------------------------------------------------------


def create_job(
    conn: sqlite3.Connection,
    original_filename: str,
    audio_path: str,
    language: str,
    model_size: str,
    student_count: int | None,
    photo_path: str | None = None,
) -> str:
    job_id = uuid.uuid4().hex
    now = time.time()
    conn.execute(
        """INSERT INTO jobs (id, status, created_at, updated_at,
               original_filename, audio_path, photo_path, language,
               model_size, student_count)
           VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, now, now, original_filename, audio_path, photo_path,
         language, model_size, student_count),
    )
    conn.commit()
    return job_id


def get_job(conn: sqlite3.Connection, job_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def update_job(conn: sqlite3.Connection, job_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    cols = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id)
    )
    conn.commit()


def set_status(conn: sqlite3.Connection, job_id: str, status: str) -> None:
    if status not in JOB_STATES:
        raise ValueError(f"unknown job state: {status}")
    update_job(conn, job_id, status=status)


def fail_job(conn: sqlite3.Connection, job_id: str, stage: str, error: str) -> None:
    update_job(conn, job_id, status="failed", error=error, error_stage=stage)


def add_warning(conn: sqlite3.Connection, job_id: str, warning: str) -> None:
    job = get_job(conn, job_id)
    if job is None:
        return
    warnings = json.loads(job["warnings"]) if job["warnings"] else []
    warnings.append(warning)
    update_job(conn, job_id, warnings=json.dumps(warnings))


def add_event(conn: sqlite3.Connection, job_id: str, message: str) -> None:
    """Append a human-readable activity line for the live processing feed."""
    conn.execute(
        "INSERT INTO events (job_id, ts, message) VALUES (?, ?, ?)",
        (job_id, time.time(), message),
    )
    conn.commit()


def get_events(
    conn: sqlite3.Connection, job_id: str, after_id: int = 0
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, ts, message FROM events WHERE job_id = ? AND id > ? ORDER BY id",
        (job_id, after_id),
    ).fetchall()
    return [dict(r) for r in rows]


def next_queued_job(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Oldest job that still needs work. Interrupted jobs (stuck in a
    processing state after a crash) are picked up again before queued ones."""
    row = conn.execute(
        """SELECT * FROM jobs
           WHERE status IN ('queued', 'preprocessing', 'transcribing', 'analyzing')
           ORDER BY created_at LIMIT 1"""
    ).fetchone()
    return dict(row) if row else None


# --- segments -------------------------------------------------------------


def insert_segments(
    conn: sqlite3.Connection, job_id: str, segments: Iterable[dict[str, Any]]
) -> None:
    conn.executemany(
        """INSERT INTO segments
               (job_id, start, end, text, speaker, speaker_confidence,
                speaker_source, is_question, features)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                job_id,
                s["start"],
                s["end"],
                s["text"],
                s.get("speaker"),
                s.get("speaker_confidence"),
                s.get("speaker_source"),
                int(s.get("is_question", False)),
                json.dumps(s["features"]) if s.get("features") else None,
            )
            for s in segments
        ],
    )
    conn.commit()


def get_segments(conn: sqlite3.Connection, job_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM segments WHERE job_id = ? ORDER BY start", (job_id,)
    ).fetchall()
    out = []
    for row in rows:
        seg = dict(row)
        seg["is_question"] = bool(seg["is_question"])
        seg["features"] = json.loads(seg["features"]) if seg["features"] else None
        out.append(seg)
    return out


def update_segment_labels(
    conn: sqlite3.Connection, job_id: str, updates: list[dict[str, Any]]
) -> None:
    """Apply speaker labels, e.g. from clustering or a manual UI flip."""
    conn.executemany(
        """UPDATE segments SET speaker = ?, speaker_confidence = ?,
               speaker_source = ?, is_question = ?
           WHERE id = ? AND job_id = ?""",
        [
            (
                u["speaker"],
                u.get("speaker_confidence"),
                u.get("speaker_source"),
                int(u.get("is_question", False)),
                u["id"],
                job_id,
            )
            for u in updates
        ],
    )
    conn.commit()


def delete_segments(conn: sqlite3.Connection, job_id: str) -> None:
    """Used when a crashed transcription stage restarts from scratch."""
    conn.execute("DELETE FROM segments WHERE job_id = ?", (job_id,))
    conn.commit()


# --- metrics ----------------------------------------------------------------


def save_metrics(
    conn: sqlite3.Connection, job_id: str, metrics: dict[str, Any]
) -> None:
    rows = []
    for name, value in metrics.items():
        if isinstance(value, (int, float)):
            rows.append((job_id, name, float(value), None))
        else:
            rows.append((job_id, name, None, json.dumps(value)))
    conn.executemany(
        """INSERT INTO metrics (job_id, name, value, extra) VALUES (?, ?, ?, ?)
           ON CONFLICT(job_id, name) DO UPDATE SET value=excluded.value,
           extra=excluded.extra""",
        rows,
    )
    conn.commit()


def get_metrics(conn: sqlite3.Connection, job_id: str) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT name, value, extra FROM metrics WHERE job_id = ?", (job_id,)
    ).fetchall()
    out: dict[str, Any] = {}
    for row in rows:
        out[row["name"]] = (
            json.loads(row["extra"]) if row["extra"] is not None else row["value"]
        )
    return out


# --- session metadata ---------------------------------------------------------


def save_session_metadata(
    conn: sqlite3.Connection,
    job_id: str,
    data: dict[str, Any],
    unmapped_keys: list[str],
    warnings: list[str],
) -> None:
    conn.execute(
        """INSERT INTO session_metadata (job_id, data, unmapped_keys, warnings)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(job_id) DO UPDATE SET data=excluded.data,
           unmapped_keys=excluded.unmapped_keys, warnings=excluded.warnings""",
        (job_id, json.dumps(data), json.dumps(unmapped_keys), json.dumps(warnings)),
    )
    conn.commit()


def get_session_metadata(
    conn: sqlite3.Connection, job_id: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT data, unmapped_keys, warnings FROM session_metadata WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "data": json.loads(row["data"]),
        "unmapped_keys": json.loads(row["unmapped_keys"] or "[]"),
        "warnings": json.loads(row["warnings"] or "[]"),
    }

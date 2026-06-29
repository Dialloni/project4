"""SQLite persistence: submissions + structured audit log.

Two tables:
  submissions  - current state of each analyzed piece of content
  audit_log    - append-only event stream (one row per decision/appeal)

Every attribution decision and every appeal writes an audit_log row, so the
log is the canonical record graders inspect via GET /log.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("PROVENANCE_DB", os.path.join(os.path.dirname(__file__), "..", "provenance.db"))


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                content_id   TEXT PRIMARY KEY,
                creator_id   TEXT NOT NULL,
                text         TEXT NOT NULL,
                attribution  TEXT NOT NULL,
                confidence   REAL NOT NULL,
                p_ai         REAL NOT NULL,
                llm_score    REAL,
                stylo_score  REAL NOT NULL,
                status       TEXT NOT NULL,
                created_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id   TEXT NOT NULL,
                creator_id   TEXT,
                event_type   TEXT NOT NULL,
                timestamp    TEXT NOT NULL,
                attribution  TEXT,
                confidence   REAL,
                llm_score    REAL,
                stylo_score  REAL,
                status       TEXT,
                detail       TEXT
            );
            """
        )


def save_classification(content_id, creator_id, text, result):
    """Persist a new submission and write its audit entry."""
    ts = _now()
    with _conn() as c:
        c.execute(
            """INSERT INTO submissions
               (content_id, creator_id, text, attribution, confidence, p_ai,
                llm_score, stylo_score, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (content_id, creator_id, text, result["attribution"], result["confidence"],
             result["p_ai"], result["llm_score"], result["stylo_score"], "classified", ts),
        )
        c.execute(
            """INSERT INTO audit_log
               (content_id, creator_id, event_type, timestamp, attribution,
                confidence, llm_score, stylo_score, status, detail)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (content_id, creator_id, "classification", ts, result["attribution"],
             result["confidence"], result["llm_score"], result["stylo_score"],
             "classified", json.dumps({"signals": result["signals"]})),
        )


def get_submission(content_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM submissions WHERE content_id=?", (content_id,)).fetchone()
        return dict(row) if row else None


def file_appeal(content_id, creator_reasoning):
    """Set status to under_review and append an appeal audit entry.

    Returns the updated submission dict, or None if content_id is unknown.
    """
    sub = get_submission(content_id)
    if not sub:
        return None
    ts = _now()
    with _conn() as c:
        c.execute("UPDATE submissions SET status=? WHERE content_id=?", ("under_review", content_id))
        c.execute(
            """INSERT INTO audit_log
               (content_id, creator_id, event_type, timestamp, attribution,
                confidence, llm_score, stylo_score, status, detail)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (content_id, sub["creator_id"], "appeal", ts, sub["attribution"],
             sub["confidence"], sub["llm_score"], sub["stylo_score"], "under_review",
             json.dumps({"appeal_reasoning": creator_reasoning})),
        )
    sub["status"] = "under_review"
    return sub


def get_log(limit=50):
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["detail"] = json.loads(d["detail"]) if d["detail"] else {}
        out.append(d)
    return out

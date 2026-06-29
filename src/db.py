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
                stylo_score  REAL,
                behavior_score REAL,
                content_type TEXT NOT NULL DEFAULT 'text',
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
            CREATE TABLE IF NOT EXISTS challenges (
                challenge_id TEXT PRIMARY KEY,
                creator_id   TEXT NOT NULL,
                phrase       TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                used         INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS certificates (
                content_id   TEXT PRIMARY KEY,
                cert_id      TEXT NOT NULL,
                creator_id   TEXT NOT NULL,
                issued_at    TEXT NOT NULL,
                method       TEXT NOT NULL,
                signature    TEXT NOT NULL
            );
            """
        )


def save_classification(content_id, creator_id, text, result, content_type="text"):
    """Persist a new submission and write its audit entry."""
    ts = _now()
    with _conn() as c:
        c.execute(
            """INSERT INTO submissions
               (content_id, creator_id, text, attribution, confidence, p_ai,
                llm_score, stylo_score, behavior_score, content_type, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (content_id, creator_id, text, result["attribution"], result["confidence"],
             result["p_ai"], result.get("llm_score"), result.get("stylo_score"),
             result.get("behavior_score"), content_type, "classified", ts),
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


# --- provenance certificate (stretch) --------------------------------------

def create_challenge(challenge_id, creator_id, phrase):
    with _conn() as c:
        c.execute(
            "INSERT INTO challenges (challenge_id, creator_id, phrase, created_at, used) VALUES (?,?,?,?,0)",
            (challenge_id, creator_id, phrase, _now()),
        )


def get_challenge(challenge_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM challenges WHERE challenge_id=?", (challenge_id,)).fetchone()
        return dict(row) if row else None


def mark_challenge_used(challenge_id):
    with _conn() as c:
        c.execute("UPDATE challenges SET used=1 WHERE challenge_id=?", (challenge_id,))


def save_certificate(content_id, cert_id, creator_id, issued_at, method, signature):
    """Persist a certificate, mark the submission verified, and audit it."""
    with _conn() as c:
        c.execute(
            """INSERT OR REPLACE INTO certificates
               (content_id, cert_id, creator_id, issued_at, method, signature)
               VALUES (?,?,?,?,?,?)""",
            (content_id, cert_id, creator_id, issued_at, method, signature),
        )
        c.execute("UPDATE submissions SET status='verified_human' WHERE content_id=?", (content_id,))
        c.execute(
            """INSERT INTO audit_log
               (content_id, creator_id, event_type, timestamp, status, detail)
               VALUES (?,?,?,?,?,?)""",
            (content_id, creator_id, "certificate_issued", issued_at, "verified_human",
             json.dumps({"cert_id": cert_id, "method": method})),
        )


def get_certificate(content_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM certificates WHERE content_id=?", (content_id,)).fetchone()
        return dict(row) if row else None


# --- analytics (stretch) ----------------------------------------------------

def get_analytics():
    """Aggregate metrics for the dashboard, computed live from the tables."""
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
        by_attr = dict(c.execute(
            "SELECT attribution, COUNT(*) FROM submissions GROUP BY attribution").fetchall())
        by_type = dict(c.execute(
            "SELECT content_type, COUNT(*) FROM submissions GROUP BY content_type").fetchall())
        appeals = c.execute(
            "SELECT COUNT(*) FROM audit_log WHERE event_type='appeal'").fetchone()[0]
        certs = c.execute("SELECT COUNT(*) FROM certificates").fetchone()[0]
        avg_conf = c.execute("SELECT AVG(confidence) FROM submissions").fetchone()[0]
        # signal disagreement: text rows where |llm - stylo| > 0.3
        disagree = c.execute(
            """SELECT COUNT(*) FROM submissions
               WHERE llm_score IS NOT NULL AND stylo_score IS NOT NULL
                 AND ABS(llm_score - stylo_score) > 0.3""").fetchone()[0]
        text_rows = c.execute(
            "SELECT COUNT(*) FROM submissions WHERE llm_score IS NOT NULL AND stylo_score IS NOT NULL").fetchone()[0]

    return {
        "total_submissions": total,
        "by_attribution": {k: by_attr.get(k, 0) for k in ("likely_ai", "uncertain", "likely_human")},
        "by_content_type": by_type,
        "appeals": appeals,
        "appeal_rate": round(appeals / total, 3) if total else 0,
        "certificates_issued": certs,
        "avg_confidence": round(avg_conf, 3) if avg_conf else 0,
        "signal_disagreements": disagree,
        "signal_disagreement_rate": round(disagree / text_rows, 3) if text_rows else 0,
    }

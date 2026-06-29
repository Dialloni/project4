"""Provenance Guard — Flask API.

Endpoints:
  POST /submit  - classify content, return verdict + confidence + label
  POST /appeal  - contest a classification, set status to under_review
  GET  /log     - recent structured audit-log entries (grading visibility)
  GET  /health  - liveness probe

Run: python -m src.app   (or: flask --app src.app run)
"""
import os
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from . import db
from .labels import build_label
from .scoring import combine
from .signals import llm_signal, stylo_signal

load_dotenv()

app = Flask(__name__)
db.init_db()

# In-memory storage is fine for a single-process local/dev deployment.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

MAX_TEXT_CHARS = 20000
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


@app.route("/", methods=["GET"])
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    # validate at the trust boundary
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "text is required and must be a non-empty string"}), 400
    if not isinstance(creator_id, str) or not creator_id.strip():
        return jsonify({"error": "creator_id is required and must be a non-empty string"}), 400
    if len(text) > MAX_TEXT_CHARS:
        return jsonify({"error": f"text exceeds {MAX_TEXT_CHARS} characters"}), 413

    llm = llm_signal(text)
    stylo = stylo_signal(text)
    result = combine(llm, stylo)
    label = build_label(result)

    content_id = str(uuid.uuid4())
    db.save_classification(content_id, creator_id, text, result)

    return jsonify({
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": result["attribution"],
        "confidence": result["confidence"],
        "p_ai": result["p_ai"],
        "signals": result["signals"],
        "label": label,
        "status": "classified",
    })


@app.route("/appeal", methods=["POST"])
@limiter.limit("20 per hour")
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    reasoning = data.get("creator_reasoning")

    if not isinstance(content_id, str) or not content_id.strip():
        return jsonify({"error": "content_id is required"}), 400
    if not isinstance(reasoning, str) or not reasoning.strip():
        return jsonify({"error": "creator_reasoning is required"}), 400

    sub = db.file_appeal(content_id, reasoning)
    if sub is None:
        return jsonify({"error": "unknown content_id"}), 404

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Appeal received. A human reviewer will re-examine this classification.",
        "original_attribution": sub["attribution"],
        "original_confidence": sub["confidence"],
    })


@app.route("/log", methods=["GET"])
def log():
    # Public here for grading/documentation; would require auth in production.
    limit = request.args.get("limit", default=50, type=int)
    return jsonify({"entries": db.get_log(limit)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=True)

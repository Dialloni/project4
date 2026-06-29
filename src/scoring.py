"""Combine 2–3 independent signals into one calibrated verdict + confidence.

Signals (each emits P(AI) in [0,1]):
  llm       - semantic  (Groq)            base weight 0.50
  stylo     - structural (stylometry)     base weight 0.25
  behavior  - input provenance (typed vs  base weight 0.25
              pasted, captured in browser)

Behavior is optional: API callers (curl) won't send it, so the scorer drops any
unavailable signal and renormalizes the remaining weights. With only llm+stylo
this reduces to the original 0.667/0.333 split.

Design choices (see planning.md):

* False-positive asymmetry: wrongly branding a human's work as AI is the worst
  outcome on a writing platform, so the bar to declare "likely AI" is higher
  (>=0.70) than the bar to declare "likely human" (<=0.40). The middle band is
  reported honestly as "uncertain" rather than forced to a side.

* confidence = certainty in the dominant attribution = max(p_ai, 1-p_ai),
  always in [0.5, 1.0]. This is what the label renders, so 0.51 and 0.95 produce
  visibly different labels.
"""

BASE_WEIGHTS = {"llm": 0.50, "stylo": 0.25, "behavior": 0.25}

AI_THRESHOLD = 0.70      # need strong evidence to accuse AI (protects humans)
HUMAN_THRESHOLD = 0.40   # below this -> likely human


def combine(llm, stylo, behavior=None):
    """llm/stylo/behavior: dicts from the signal functions (behavior optional).

    Returns a result dict consumed by the endpoint, label builder, and DB.
    """
    available = {"stylo": stylo["score"]}  # stylo always available
    if llm.get("available"):
        available["llm"] = llm["score"]
    if behavior and behavior.get("available"):
        available["behavior"] = behavior["score"]

    # weighted average over available signals, renormalized
    total_w = sum(BASE_WEIGHTS[k] for k in available)
    p_ai = sum(BASE_WEIGHTS[k] * v for k, v in available.items()) / total_w
    p_ai = round(p_ai, 4)

    if p_ai >= AI_THRESHOLD:
        attribution = "likely_ai"
    elif p_ai <= HUMAN_THRESHOLD:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

    confidence = round(max(p_ai, 1 - p_ai), 4)

    return {
        "attribution": attribution,
        "confidence": confidence,
        "p_ai": p_ai,
        "llm_score": available.get("llm"),
        "stylo_score": stylo["score"],
        "behavior_score": available.get("behavior"),
        "weights_used": {k: round(BASE_WEIGHTS[k] / total_w, 3) for k in available},
        "signals": {
            "llm": {"available": llm.get("available", False), "score": available.get("llm"),
                    "rationale": llm.get("rationale", "")},
            "stylometry": {"score": stylo["score"], "metrics": stylo["metrics"]},
            "behavior": (
                {"available": True, "score": behavior["score"], "metrics": behavior["metrics"],
                 "verdict": behavior["verdict"]}
                if behavior and behavior.get("available")
                else {"available": False, "score": None}
            ),
        },
    }

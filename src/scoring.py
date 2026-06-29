"""Combine the two signals into a single calibrated verdict + confidence.

Design choices (documented in planning.md / README):

* p_ai = weighted average of the two signals. The LLM carries more weight
  (0.65) than stylometry (0.35) because it reads meaning, not just surface
  statistics. If the LLM is unavailable, stylometry takes full weight.

* False-positive asymmetry: wrongly branding a human's work as AI is the worst
  outcome on a writing platform, so the bar to declare "likely AI" is higher
  (>=0.70) than the bar to declare "likely human" (<=0.40). The middle band is
  reported honestly as "uncertain" rather than forced to a side.

* confidence = certainty in the dominant attribution = max(p_ai, 1-p_ai),
  always in [0.5, 1.0]. This is what the transparency label renders, so 0.51
  and 0.95 produce visibly different labels.
"""

LLM_WEIGHT = 0.65
STYLO_WEIGHT = 0.35

AI_THRESHOLD = 0.70      # need strong evidence to accuse AI (protects humans)
HUMAN_THRESHOLD = 0.40   # below this -> likely human


def combine(llm, stylo):
    """llm: dict from llm_signal(); stylo: dict from stylo_signal().

    Returns a result dict consumed by the endpoint, label builder, and DB.
    """
    stylo_score = stylo["score"]
    if llm["available"]:
        llm_score = llm["score"]
        p_ai = LLM_WEIGHT * llm_score + STYLO_WEIGHT * stylo_score
    else:
        llm_score = None
        p_ai = stylo_score  # graceful degradation to single signal

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
        "llm_score": llm_score,
        "stylo_score": stylo_score,
        "signals": {
            "llm": {"available": llm["available"], "score": llm_score,
                    "rationale": llm.get("rationale", "")},
            "stylometry": {"score": stylo_score, "metrics": stylo["metrics"]},
        },
    }

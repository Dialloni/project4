"""Runnable check: scoring varies meaningfully and labels stay consistent.

Runs WITHOUT a Groq key (stylometry-only path) so it works in CI and offline.
  python -m tests.test_pipeline
"""
from src.labels import build_label
from src.scoring import combine
from src.signals import stylo_signal

AI_TEXT = (
    "Artificial intelligence represents a transformative paradigm shift in modern "
    "society. It is important to note that while the benefits of AI are numerous, it "
    "is equally essential to consider the ethical implications. Furthermore, "
    "stakeholders across various sectors must collaborate to ensure responsible "
    "deployment of these powerful technologies across the global landscape."
)
HUMAN_TEXT = (
    "ok so i finally tried that new ramen place downtown and honestly? underwhelming. "
    "the broth was fine but they put WAY too much sodium in it and i was thirsty for "
    "like three hours after. my friend got the spicy version and said it was better. "
    "probably won't go back unless someone drags me there"
)


def _score(text):
    stylo = stylo_signal(text)
    llm = {"available": False, "score": None, "rationale": "test-offline"}
    return combine(llm, stylo)


def main():
    ai = _score(AI_TEXT)
    human = _score(HUMAN_TEXT)

    print(f"AI sample    -> p_ai={ai['p_ai']:.3f} {ai['attribution']:13s} conf={ai['confidence']:.3f}")
    print(f"  {build_label(ai)['text']}")
    print(f"Human sample -> p_ai={human['p_ai']:.3f} {human['attribution']:13s} conf={human['confidence']:.3f}")
    print(f"  {build_label(human)['text']}")

    # core assertions: scoring discriminates, and confidence is well-formed
    assert ai["p_ai"] > human["p_ai"], "AI text should score higher p_ai than human text"
    assert ai["p_ai"] - human["p_ai"] > 0.15, "scores should differ meaningfully"
    for r in (ai, human):
        assert 0.5 <= r["confidence"] <= 1.0, "confidence must be in [0.5, 1.0]"
        assert r["attribution"] in {"likely_ai", "likely_human", "uncertain"}
    print("\nOK: scoring discriminates and confidence is well-formed.")


if __name__ == "__main__":
    main()

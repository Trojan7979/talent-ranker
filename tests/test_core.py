from talent_ranker.documents import chunk_resume
from talent_ranker.ranking import final_score, quality_multiplier, reciprocal_rank_fusion


def test_section_aware_chunking():
    text = "SUMMARY\nML engineer shipping search systems.\nEXPERIENCE\nBuilt hybrid retrieval. " * 30
    chunks = chunk_resume(text, target_words=20, overlap_words=5)
    assert len(chunks) > 2
    assert {c.section for c in chunks} >= {"summary", "experience"}
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_rrf_rewards_agreement():
    scores = reciprocal_rank_fusion(["a", "b"], ["b", "c"])
    assert scores["b"] > scores["a"]
    assert scores["b"] > scores["c"]


def test_impossible_skill_duration_is_penalized():
    clean, _ = quality_multiplier({"years_experience": 5, "max_claimed_skill_months": 48})
    suspect, concerns = quality_multiplier({"years_experience": 2, "max_claimed_skill_months": 90})
    assert suspect < clean
    assert concerns


def test_final_score_is_bounded():
    score, components, _ = final_score(0.03, 100, {})
    assert 0 <= score <= 1
    assert components["semantic"] <= 1

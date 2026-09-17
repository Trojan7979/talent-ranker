from talent_ranker.documents import chunk_resume, extract_evidence_units
from talent_ranker.ranking import final_score, quality_multiplier, reciprocal_rank_fusion


def test_section_aware_chunking():
    text = (
        "SUMMARY\nML engineer shipping search systems.\nEXPERIENCE\nBuilt hybrid retrieval. " * 30
    )
    chunks = chunk_resume(text, max_tokens=20, overlap_tokens=5)
    assert len(chunks) > 2
    assert {c.section for c in chunks} >= {"summary", "experience"}
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(chunk.parent_content for chunk in chunks)


def test_experience_chunks_retain_parent_context():
    text = (
        "EXPERIENCE\n"
        "ML Engineer | Example Corp | Jan 2022 - Present\n"
        "Built a production hybrid search system with measurable retrieval improvements."
    )
    chunks = chunk_resume(text, max_tokens=8, overlap_tokens=2)
    assert len(chunks) > 1
    assert all(chunk.section == "experience" for chunk in chunks)
    assert all("Example Corp" in chunk.parent_content for chunk in chunks)


def test_experience_entries_remain_separate_evidence_units():
    text = (
        "EXPERIENCE\n"
        "Senior ML Engineer\nExample Corp\nJan 2022 - Present\n"
        "Built production retrieval systems with measured improvements.\n"
        "Data Scientist\nPrevious Corp\nJun 2019 - Dec 2021\n"
        "Developed classification models and evaluation pipelines."
    )
    experience = [unit for unit in extract_evidence_units(text) if unit.section == "experience"]
    assert len(experience) == 2
    assert "Example Corp" in experience[0].content
    assert "Previous Corp" in experience[1].content


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

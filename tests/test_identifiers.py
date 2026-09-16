import pytest

from talent_ranker.identifiers import format_candidate_id, validate_candidate_id


def test_format_candidate_id_uses_four_digits() -> None:
    assert format_candidate_id(1) == "CAND_0001"
    assert format_candidate_id(9_000) == "CAND_9000"


def test_validate_candidate_id_normalizes_case_and_spacing() -> None:
    assert validate_candidate_id(" cand_0042 ") == "CAND_0042"


@pytest.mark.parametrize("candidate_id", ["CAND_0000", "CAND_9001", "CAND_0000002"])
def test_validate_candidate_id_rejects_out_of_scope_values(candidate_id: str) -> None:
    with pytest.raises(ValueError):
        validate_candidate_id(candidate_id)

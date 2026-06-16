from suite.graders.gaia import score_gaia


def test_gaia_accepts_unit_suffix_for_numeric_gold() -> None:
    result = score_gaia(
        gold_rows=[{"id": "gaia_x", "final_answer": "12", "level": 2}],
        answer_rows=[{"id": "gaia_x", "final_answer": "12 hours"}],
    )

    assert result["details"][0]["passed"] is True
    assert result["metrics"]["accuracy"]["passed"] == 1


def test_gaia_rejects_wrong_numeric_answer_with_unit() -> None:
    result = score_gaia(
        gold_rows=[{"id": "gaia_x", "final_answer": "12", "level": 2}],
        answer_rows=[{"id": "gaia_x", "final_answer": "13 hours"}],
    )

    assert result["details"][0]["passed"] is False
    assert result["metrics"]["accuracy"]["passed"] == 0

from core.evaluation_scorer import EvaluationScorer


def test_all_supported_scores_100():
    scorer = EvaluationScorer()
    assert scorer.section_quality(["supported"] * 5) == 100


def test_all_unsupported_scores_0():
    scorer = EvaluationScorer()
    assert scorer.section_quality(["unsupported"] * 5) == 0


def test_contradicted_penalises_below_50():
    scorer = EvaluationScorer()
    # 5 supported (+5.0), 5 contradicted (-5.0) → sum=0 → clamp(0/10)=0
    assert scorer.section_quality(["supported"] * 5 + ["contradicted"] * 5) == 0


def test_contradicted_reduces_score_below_pure_supported():
    scorer = EvaluationScorer()
    # 8 supported (+8), 1 overstated (+0.5), 1 contradicted (-1) → 7.5/10 = 75
    verdicts = ["supported"] * 8 + ["overstated", "contradicted"]
    assert scorer.section_quality(verdicts) == 75


def test_missing_citation_partial_credit():
    scorer = EvaluationScorer()
    # 10 missing_citation → 0.75 each → 7.5/10 = 75
    assert scorer.section_quality(["missing_citation"] * 10) == 75


def test_section_quality_clamps_at_0():
    scorer = EvaluationScorer()
    # More contradicted than supported → negative sum → clamped to 0
    verdicts = ["supported"] * 2 + ["contradicted"] * 10
    assert scorer.section_quality(verdicts) == 0


def test_section_quality_empty_returns_0():
    scorer = EvaluationScorer()
    assert scorer.section_quality([]) == 0


def test_report_quality_averages_sections():
    scorer = EvaluationScorer()
    assert scorer.report_quality([100, 50, 75]) == 75


def test_report_quality_empty_returns_0():
    scorer = EvaluationScorer()
    assert scorer.report_quality([]) == 0


def test_hallucination_rate_counts_unsupported_and_contradicted():
    scorer = EvaluationScorer()
    # 3 unsupported + 2 contradicted out of 10 = 50%
    verdicts = ["supported"] * 5 + ["unsupported"] * 3 + ["contradicted"] * 2
    assert scorer.hallucination_rate(verdicts) == 50


def test_hallucination_rate_zero_when_all_supported():
    scorer = EvaluationScorer()
    assert scorer.hallucination_rate(["supported"] * 8) == 0


def test_hallucination_rate_empty_returns_0():
    scorer = EvaluationScorer()
    assert scorer.hallucination_rate([]) == 0


def test_repair_needed_below_threshold():
    scorer = EvaluationScorer()
    assert scorer.repair_needed(["unsupported"] * 5 + ["supported"] * 5, 45) is True


def test_repair_needed_above_threshold_no_contradiction():
    scorer = EvaluationScorer()
    assert scorer.repair_needed(["supported"] * 10, 90) is False


def test_repair_needed_contradicted_overrides_good_score():
    scorer = EvaluationScorer()
    assert scorer.repair_needed(["supported"] * 9 + ["contradicted"], 85) is True

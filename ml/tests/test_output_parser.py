import pytest
import torch

from streamsense.data import taxonomy as tx
from streamsense.models.output_parser import extract_json_object, parse_output


@pytest.fixture
def tax(make_cfg) -> tx.Taxonomy:
    return tx.Taxonomy.from_config(make_cfg().taxonomy)


GOOD = (
    '{"quality_issue": true, "issues": [{"name": "x", "raw_term": "Blurry", "severity": 3,'
    ' "weather_related": false}], "severity": 3, "explanation": "soft", "confidence": 0.8,'
    ' "metadata": {}}'
)


def test_valid_output_is_normalized(tax):
    r = parse_output(GOOD, tax)
    assert not r.failed and r.repairs == []
    issue = r.output["issues"][0]
    assert issue["raw_term"] == "blur" and issue["name"] == "blur_lens_smear"
    assert r.output["severity"] == 3 and r.output["confidence"] == 0.8


def test_fences_and_surrounding_text_are_repaired(tax):
    r = parse_output(f"Sure!\n```json\n{GOOD}\n```\nDone.", tax)
    assert not r.failed
    assert {"stripped_code_fence", "dropped_leading_text", "dropped_trailing_text"} <= set(
        r.repairs
    )


def test_braces_inside_strings_do_not_confuse_extraction():
    block, _ = extract_json_object('{"explanation": "a } b", "x": 1} tail')
    assert block == '{"explanation": "a } b", "x": 1}'


def test_trailing_commas_and_python_literals(tax):
    r = parse_output('{"quality_issue": True, "issues": ["fog",], "severity": None,}', tax)
    assert not r.failed and "json_syntax_fixed" in r.repairs
    assert r.output["issues"][0]["weather_related"] and r.output["severity"] is None


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("no json here", "no_json_object"),
        ('{"quality_issue": "haze"}', "schema"),
        ('{"quality_issue": true, "severity": 9}', "schema"),
        ('{"quality_issue": true, "issues": "blur"}', "schema"),
        ('{"quality_issue": true', "no_json_object"),
        ("[1, 2]", "no_json_object"),
    ],
)
def test_failures_are_reported(tax, text, error):
    r = parse_output(text, tax)
    assert r.failed and r.error.startswith(error)


def test_negative_with_issues_is_cleared(tax):
    r = parse_output('{"quality_issue": false, "issues": ["blur"], "severity": 2}', tax)
    assert r.output["issues"] == [] and r.output["severity"] is None
    assert "negative_cleared_issues" in r.repairs


def test_string_values_and_bad_confidence(tax):
    r = parse_output('{"quality_issue": "true", "severity": "4", "confidence": 7}', tax)
    assert r.output["quality_issue"] and r.output["severity"] == 4
    assert r.output["confidence"] is None
    assert {"quality_issue_string_bool", "severity_string_number",
            "confidence_invalid_dropped"} <= set(r.repairs)  # fmt: skip


def test_unknown_terms_map_to_other(tax):
    r = parse_output('{"quality_issue": true, "issues": ["smudge"], "severity": 2}', tax)
    assert r.output["issues"][0]["name"] == "other"


def test_boolean_first_token_processor():
    from streamsense.models.vlm import BooleanFirstToken

    proc = BooleanFirstToken(true_ids=[1], false_ids=[2], prompt_len=3)
    scores = torch.tensor([[5.0, 0.0, 0.0, 1.0], [0.0, 0.0, 2.0, 0.0]])
    out = proc(torch.zeros(2, 3, dtype=torch.long), scores)
    assert torch.isinf(out[:, [0, 3]]).all() and torch.isfinite(out[:, [1, 2]]).all()
    assert proc.p_true[0] == pytest.approx(0.5) and proc.p_true[1] < 0.2
    later = torch.randn(2, 4)
    assert torch.equal(proc(torch.zeros(2, 4, dtype=torch.long), later), later)


def test_boolean_first_token_forced_decisions():
    from streamsense.models.vlm import BooleanFirstToken

    proc = BooleanFirstToken(true_ids=[1], false_ids=[2], prompt_len=3, forced=[False, True])
    scores = torch.tensor([[0.0, 5.0, 0.0, 0.0], [0.0, 0.0, 5.0, 0.0]])
    out = proc(torch.zeros(2, 3, dtype=torch.long), scores)
    assert out[0].argmax() == 2 and out[1].argmax() == 1  # decision overrides the argmax
    assert proc.p_true[0] > 0.9 and proc.p_true[1] < 0.1  # score is still unconstrained

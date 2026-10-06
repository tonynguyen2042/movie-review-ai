"""Unit tests for safe inline-JSON serialization."""

import json

from movie_review.ui.safe_json import json_for_script


def test_plain_payload_round_trips() -> None:
    """Ordinary data is unchanged apart from escaping."""
    data = {"job_id": "job_1", "total": 3, "tags": ["a", "b"], "ok": True}
    assert json.loads(json_for_script(data)) == data


def test_script_close_tag_is_neutralised() -> None:
    """A ``</script>`` payload cannot terminate the inline script element."""
    out = json_for_script({"name": "</script><script>alert(1)</script>"})
    assert "</script>" not in out
    assert "<script>" not in out
    assert "<" not in out
    assert json.loads(out)["name"] == "</script><script>alert(1)</script>"


def test_angle_and_ampersand_are_escaped() -> None:
    """HTML-significant characters become JSON unicode escapes."""
    out = json_for_script({"v": "<a href='x'>&</a>"})
    assert "<" not in out
    assert ">" not in out
    assert "&" not in out
    assert json.loads(out)["v"] == "<a href='x'>&</a>"


def test_line_separators_are_escaped() -> None:
    """U+2028/U+2029 are escaped so the payload stays valid in old engines."""
    out = json_for_script({"v": "a b c"})
    assert "\\u2028" in out
    assert "\\u2029" in out
    assert json.loads(out)["v"] == "a b c"


def test_output_is_valid_json_for_lists_and_scalars() -> None:
    """Non-dict payloads are handled."""
    assert json.loads(json_for_script([1, 2, 3])) == [1, 2, 3]
    assert json.loads(json_for_script("plain")) == "plain"
    assert json.loads(json_for_script(None)) is None


def test_dumps_equivalent_content() -> None:
    """Escaping changes only the unsafe characters, not the decoded value."""
    data = {"title": "A <b>Review</b>", "n": 5}
    assert json_for_script(data) != json.dumps(data)
    assert json.loads(json_for_script(data)) == json.loads(json.dumps(data))

"""T091 acceptance: character explorer loads and renders from movie-analysis.json.

Field names follow the canonical schema produced by
``movie_review.knowledge.analysis`` (``id``/``first_seen``/``last_seen``).
"""

import json
from pathlib import Path

from movie_review.artifacts import manager as artifacts
from movie_review.ui.character import CharacterExplorer


def _analysis() -> dict:
    return {
        "movie": {"id": "movie_x"},
        "scenes": [
            {"scene_id": "s1", "analysis": {"characters": ["Marina Vane"]}},
            {"scene_id": "s2", "analysis": {"characters": ["Marina"]}},
        ],
        "characters": [
            {
                "id": "char_000001",
                "name": "Marina Vane",
                "aliases": ["Marina"],
                "gender": "female",
                "first_seen": 12.0,
                "last_seen": 900.0,
                "confidence": 0.94,
            },
            {
                "id": "char_000002",
                "name": "The Captain",
                "aliases": [],
                "gender": "male",
                "first_seen": 300.0,
                "last_seen": 1200.0,
                "confidence": 0.5,
            },
        ],
        "events": [
            {"id": "ev1", "type": "DISCOVERY", "characters": ["char_000001"]},
        ],
        "relationships": [
            {
                "subject": "char_000001",
                "relation": "KNOWS",
                "object": "char_000002",
                "evidence": ["evidence_1"],
                "confidence": 0.8,
            },
        ],
    }


def _seed(tmp_path: Path, job_id: str = "job_x", doc: dict | None = None) -> Path:
    jobs_dir = tmp_path / "jobs"
    job_dir = jobs_dir / job_id
    job_dir.mkdir(parents=True)
    artifacts.write_json(job_dir / "movie-analysis.json", doc if doc is not None else _analysis())
    return jobs_dir


def test_character_explorer_from_movie_analysis(tmp_path: Path) -> None:
    """Characters, scenes, events, and relationships are assembled."""
    jobs_dir = _seed(tmp_path)
    data = CharacterExplorer(jobs_dir, "job_x").load()

    assert data["job_id"] == "job_x"
    assert data["total"] == 2

    marina = next(c for c in data["characters"] if c["id"] == "char_000001")
    assert marina["name"] == "Marina Vane"
    assert marina["aliases"] == ["Marina"]
    assert marina["gender"] == "female"
    assert marina["first_seen"] == 12.0
    assert marina["last_seen"] == 900.0
    assert marina["confidence"] == 0.94
    # enriched from scenes (matched by name and alias)
    assert marina["scenes"] == ["s1", "s2"]
    assert marina["scene_count"] == 2
    # enriched from events
    assert marina["events"] == ["ev1"]

    captain = next(c for c in data["characters"] if c["id"] == "char_000002")
    assert captain["confidence"] == 0.5
    assert captain["scenes"] == []


def test_character_explorer_relationships(tmp_path: Path) -> None:
    """Relationships are attached to both endpoints with evidence."""
    jobs_dir = _seed(tmp_path)
    data = CharacterExplorer(jobs_dir, "job_x").load()

    marina = next(c for c in data["characters"] if c["id"] == "char_000001")
    captain = next(c for c in data["characters"] if c["id"] == "char_000002")

    assert len(marina["relationships"]) == 1
    rel = marina["relationships"][0]
    assert rel["relation"] == "KNOWS"
    assert rel["target"] == "char_000002"
    assert rel["evidence"] == ["evidence_1"]
    assert rel["confidence"] == 0.8

    assert len(captain["relationships"]) == 1
    assert captain["relationships"][0]["target"] == "char_000001"


def test_character_explorer_json_export(tmp_path: Path) -> None:
    """JSON export round-trips the loaded structure."""
    jobs_dir = _seed(tmp_path)
    payload = json.loads(CharacterExplorer(jobs_dir, "job_x").to_json())
    assert payload["job_id"] == "job_x"
    assert payload["total"] == 2


def test_character_explorer_html_export(tmp_path: Path) -> None:
    """HTML export renders the sidebar list and embeds the data.

    This is the regression test for the missing ``_render_char_list``
    method, which made ``to_html()`` raise AttributeError.
    """
    jobs_dir = _seed(tmp_path)
    html = CharacterExplorer(jobs_dir, "job_x").to_html()

    assert "Character Explorer" in html
    assert "job_x" in html
    assert 'class="char-item"' in html
    assert 'data-id="char_000001"' in html
    assert "selectCharacter('char_000001')" in html
    assert "Marina Vane" in html
    assert "2 characters" in html
    assert "data = " in html


def test_character_explorer_html_renders_aliases_and_confidence(tmp_path: Path) -> None:
    """Aliases and the percentage confidence appear in the sidebar."""
    jobs_dir = _seed(tmp_path)
    html = CharacterExplorer(jobs_dir, "job_x").to_html()

    assert "(Marina)" in html
    assert "94%" in html
    assert "50%" in html


def test_character_explorer_html_escapes_content(tmp_path: Path) -> None:
    """Names and aliases are HTML-escaped (no injection into markup)."""
    doc = _analysis()
    doc["characters"][0]["name"] = '<img src=x onerror="alert(1)">'
    doc["characters"][0]["aliases"] = ["<b>bad</b>"]
    jobs_dir = _seed(tmp_path, doc=doc)

    html = CharacterExplorer(jobs_dir, "job_x").to_html()
    rendered = _rendered_list(html)

    assert "<img src=x" not in rendered
    assert "&lt;img" in rendered
    assert "<b>bad</b>" not in rendered
    assert "&lt;b&gt;bad" in rendered


def test_character_explorer_empty(tmp_path: Path) -> None:
    """No artifact yields an empty but well-formed structure."""
    jobs_dir = tmp_path / "jobs"
    (jobs_dir / "job_none").mkdir(parents=True)

    data = CharacterExplorer(jobs_dir, "job_none").load()
    assert data["job_id"] == "job_none"
    assert data["total"] == 0
    assert data["characters"] == []


def _rendered_list(html: str) -> str:
    """Extract the server-rendered character list region.

    The client-side template inside ``<script>`` also contains
    ``char-item`` markup, so assertions about server output must look only
    at the pre-rendered region.
    """
    start = html.index('<div class="char-list" id="charList">')
    end = html.index('<div class="char-detail"', start)
    return html[start:end]


def test_character_explorer_empty_html_does_not_crash(tmp_path: Path) -> None:
    """Empty input still renders, with an empty-state message."""
    jobs_dir = tmp_path / "jobs"
    (jobs_dir / "job_none").mkdir(parents=True)

    html = CharacterExplorer(jobs_dir, "job_none").to_html()
    assert "No characters found" in html
    assert 'class="char-item"' not in _rendered_list(html)


def test_character_explorer_script_payload_cannot_break_out(tmp_path: Path) -> None:
    """A ``</script>`` in model text cannot terminate the inline script block.

    ``json.dumps`` alone leaves ``</script>`` intact, which would let
    VLM-produced names execute as JavaScript.
    """
    doc = _analysis()
    doc["characters"][0]["name"] = "</script><script>alert(1)</script>"
    jobs_dir = _seed(tmp_path, doc=doc)

    html = CharacterExplorer(jobs_dir, "job_x").to_html()

    # the only </script> in the document is the real closing tag
    assert html.count("</script>") == 1
    assert "<script>alert(1)</script>" not in html
    assert "\\u003c/script\\u003e" in html
    # and the payload is still recoverable as data
    assert "alert(1)" in html


def test_character_explorer_empty_character_list(tmp_path: Path) -> None:
    """A document with no characters renders the empty state."""
    jobs_dir = _seed(tmp_path, doc={"movie": {"id": "m"}, "characters": []})
    html = CharacterExplorer(jobs_dir, "job_x").to_html()
    assert "No characters found" in html
    assert "0 characters" in html

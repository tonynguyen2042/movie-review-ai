"""Golden movie fixtures (T078).

Small deterministic ``movie-analysis.json``-shaped payloads with known
characters, events, and evidence. No media, no models — evaluators score
predictions against these fixtures in unit tests.
"""

from __future__ import annotations

from typing import Any


def golden_analysis(movie_id: str = "golden-01") -> dict[str, Any]:
    """Return a minimal canonical analysis document."""
    return {
        "movie": {"id": movie_id, "title": "Golden Test"},
        "scenes": [
            {"scene_id": "s01", "start": 0.0, "end": 60.0},
            {"scene_id": "s02", "start": 60.0, "end": 120.0},
        ],
        "transcript": [
            {"segment_id": "t01", "start": 5.0, "end": 9.0, "text": "We must leave now."},
        ],
        "speakers": [{"speaker": "spk1", "character_id": "c_ana", "confidence": 0.9}],
        "characters": [
            {"id": "c_ana", "name": "Ana"},
            {"id": "c_ben", "name": "Ben"},
        ],
        "locations": [{"id": "l_harbor", "name": "Harbor"}],
        "events": [
            {
                "id": "e_escape",
                "type": "escape",
                "timestamp": 55.0,
                "characters": ["c_ana", "c_ben"],
                "description": "Ana and Ben escape by boat.",
            },
            {
                "id": "e_betrayal",
                "type": "betrayal",
                "timestamp": 100.0,
                "characters": ["c_ben"],
                "description": "Ben betrays Ana.",
            },
        ],
        "relationships": [
            {"subject": "c_ben", "relation": "BETRAYS", "object": "c_ana"},
        ],
        "evidence": [
            {"id": "ev1", "type": "DIALOGUE", "source_id": "t01"},
            {"id": "ev2", "type": "VISUAL", "source_id": "s01"},
        ],
        "claims": [],
        "story_arcs": [{"id": "arc1", "events": ["e_escape", "e_betrayal"]}],
        "themes": [{"name": "loyalty"}],
        "twists": [{"event_id": "e_betrayal", "description": "Ben was against Ana."}],
        "timeline": [
            {"event_id": "e_escape", "timestamp": 55.0},
            {"event_id": "e_betrayal", "timestamp": 100.0},
        ],
    }


def golden_claims() -> list[dict[str, Any]]:
    """Hand-checked review claims with verdicts for the golden movie."""
    return [
        {
            "claim_id": "cl1",
            "text": "Ana and Ben escape by boat.",
            "type": "PLOT_FACT",
            "evidence": ["ev1", "ev2"],
            "verdict": "SUPPORTED",
        },
        {
            "claim_id": "cl2",
            "text": "Ana dies in the harbor.",
            "type": "PLOT_FACT",
            "evidence": [],
            "verdict": "INSUFFICIENT_EVIDENCE",
        },
    ]

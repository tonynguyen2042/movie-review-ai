"""Shared unit-test fixtures.

Only fixtures that genuinely span modules live here. The vision stage builds an
analysis proxy before it samples frames, and generate_proxy really runs ffmpeg
and ffprobe; a stub returning the *source* path keeps those tests exercising
sampling behaviour rather than transcoding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from movie_review.media.proxy import ProxyResult


@pytest.fixture
def stub_analysis_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace generate_proxy with a no-op that echoes the source path back.

    Returning the source rather than a fabricated proxy keeps the downstream
    assertions about frame counts, ordering and caching exactly as they were
    before the proxy was introduced. Tests that care about proxy behaviour
    should stub ffmpeg/ffprobe and call generate_proxy directly.
    """

    def _stub(source: str | Path, **_kwargs: Any) -> ProxyResult:
        return ProxyResult(path=Path(source), width=1280, height=720, cache_hit=True)

    monkeypatch.setattr("movie_review.media.proxy.generate_proxy", _stub)
    # The orchestrator imports the name inside the stage function, so the module
    # attribute is the only binding that matters at call time.
    monkeypatch.setattr("movie_review.pipeline.orchestrator.generate_proxy", _stub, raising=False)

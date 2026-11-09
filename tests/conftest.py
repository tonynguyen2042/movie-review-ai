"""The fixtures the whole test suite shares.

Only fixtures that genuinely span modules live here. The vision stage
builds an analysis proxy before it samples frames, and generate_proxy
really runs ffmpeg and ffprobe; a stub returning the *source* path keeps
those tests exercising sampling behaviour rather than transcoding.

A fixture that one test file needs, and no other, stays in that file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from movie_review.config.settings import set_config_path
from movie_review.media.proxy import ProxyResult
from movie_review.storage.database import bootstrap, connect


@pytest.fixture(autouse=True)
def isolated_config_path() -> Generator[None]:
    """Clear the process-wide ``--config`` override between tests.

    The CLI startup callback stores the flag on the settings module, and
    tests run in one process; without this, a test that invokes the CLI with
    ``--config`` would leak the path into every later ``load_settings()``.
    """
    set_config_path(None)
    yield
    set_config_path(None)


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


@pytest.fixture
def db(tmp_path: Path) -> Generator[sqlite3.Connection]:
    """A fresh, empty job database.

    The schema is bootstrapped, so the tables exist and there are no rows.
    A test that needs a job to hang its rows on asks for ``seeded_db``.
    """
    path = bootstrap(tmp_path / "jobs" / "test.db")
    assert path.is_file()
    conn = connect(path)
    yield conn
    conn.close()

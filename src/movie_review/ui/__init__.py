"""Optional UI package (Phase 11)."""

from movie_review.ui.character import CharacterExplorer
from movie_review.ui.dashboard import JobDashboard
from movie_review.ui.graph import StoryGraph
from movie_review.ui.qc_report import QualityReportUI
from movie_review.ui.safe_json import json_for_script
from movie_review.ui.script_editor import ScriptEditor
from movie_review.ui.timeline import MovieTimeline
from movie_review.ui.timeline_editor import VisualTimelineEditor

__all__ = [
    "CharacterExplorer",
    "JobDashboard",
    "MovieTimeline",
    "QualityReportUI",
    "ScriptEditor",
    "StoryGraph",
    "VisualTimelineEditor",
    "json_for_script",
]

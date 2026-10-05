"""Domain contracts: validated Pydantic models only (no infra imports)."""

from movie_review.domain.artifact import Artifact
from movie_review.domain.character import Character
from movie_review.domain.claim import Claim
from movie_review.domain.diarization import DiarizedSegment
from movie_review.domain.enums import ClaimStatus, ClaimType, EvidenceType, JobStatus
from movie_review.domain.event import Event, EventType
from movie_review.domain.evidence import Evidence
from movie_review.domain.graph import Relationship, RelationType, StoryGraph
from movie_review.domain.job import Job
from movie_review.domain.location import Location
from movie_review.domain.mention import CharacterMention
from movie_review.domain.movie import Movie, MovieMetadata
from movie_review.domain.review import (
    OutlineSection,
    ReviewParagraph,
    ReviewPlan,
    ReviewScript,
    ReviewSection,
)
from movie_review.domain.scene import Scene
from movie_review.domain.scene_analysis import SceneAnalysis
from movie_review.domain.story import StoryArc, StoryElement, Theme, Twist
from movie_review.domain.transcript import TranscriptSegment
from movie_review.domain.tts import SpeechAudio, TTSRequest

__all__ = [
    "Artifact",
    "Character",
    "CharacterMention",
    "Claim",
    "ClaimStatus",
    "ClaimType",
    "DiarizedSegment",
    "Event",
    "EventType",
    "Evidence",
    "EvidenceType",
    "Job",
    "JobStatus",
    "Location",
    "Movie",
    "MovieMetadata",
    "OutlineSection",
    "RelationType",
    "Relationship",
    "ReviewParagraph",
    "ReviewPlan",
    "ReviewScript",
    "ReviewSection",
    "Scene",
    "SceneAnalysis",
    "StoryArc",
    "StoryElement",
    "StoryGraph",
    "Theme",
    "SpeechAudio",
    "TTSRequest",
    "TranscriptSegment",
    "Twist",
]

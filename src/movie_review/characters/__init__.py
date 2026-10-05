"""Character discovery and linking (T028 discovery, T029 linking)."""

from movie_review.characters.discovery import DiscoveryResult, discover_characters, save_discovery
from movie_review.characters.linking import SpeakerLink, link_speakers, save_links

__all__ = [
    "DiscoveryResult",
    "SpeakerLink",
    "discover_characters",
    "link_speakers",
    "save_discovery",
    "save_links",
]

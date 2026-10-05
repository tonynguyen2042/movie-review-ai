"""Text-to-speech ports and adapters (T051 port, T052 adapter)."""

from movie_review.tts.port import TTSError, TTSPort, TTSUnavailableError

__all__ = ["TTSError", "TTSPort", "TTSUnavailableError"]

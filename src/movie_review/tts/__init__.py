"""Text-to-speech ports and adapters (T051 port, T052 adapter)."""

from movie_review.tts.port import TTSError, TTSPort, TTSUnavailableError
from movie_review.tts.qwen_tts import QwenTTSAdapter

__all__ = ["QwenTTSAdapter", "TTSError", "TTSPort", "TTSUnavailableError"]

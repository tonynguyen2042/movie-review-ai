"""T053 acceptance: chunk planning, splitting, and file synthesis."""

import wave
from pathlib import Path

from movie_review.domain import (
    ReviewParagraph,
    ReviewScript,
    ReviewSection,
    SpeechAudio,
    TTSRequest,
)
from movie_review.tts.chunks import (
    plan_chunks,
    split_sentences,
    synthesize_chunk,
    synthesize_chunks,
    write_wav,
)
from movie_review.tts.port import TTSPort


def _paragraph__chunks(paragraph_id: str, text: str) -> ReviewParagraph:
    return ReviewParagraph(
        id=paragraph_id, text=text, target_seconds=12, claims=[], visual_intent="shot"
    )


def _script__chunks() -> ReviewScript:
    long_text = " ".join(f"Sentence number {n} ends here." for n in range(60))
    return ReviewScript(
        sections=[
            ReviewSection(
                id="sec_01",
                type="hook",
                paragraphs=[
                    _paragraph__chunks("p1", "Short hook text here."),
                    _paragraph__chunks("p2", long_text),
                ],
            )
        ]
    )


def test_split_sentences() -> None:
    assert split_sentences("Hello world. How are you? Fine! Indeed… yes.") == [
        "Hello world.",
        "How are you?",
        "Fine!",
        "Indeed…",
        "yes.",
    ]
    assert split_sentences("  ") == []


def test_plan_chunks_ids_and_split() -> None:
    chunks = plan_chunks(_script__chunks(), voice="Ryan", emotion="dramatic")
    # The id is derived from the content, not from the position.
    assert chunks[0].chunk_id.startswith("tts_")
    assert chunks[0].paragraph_id == "p1"
    assert chunks[0].voice == "Ryan"
    assert chunks[0].emotion == "dramatic"
    assert len(chunks) > 2
    assert all(chunk.text.strip() for chunk in chunks[1:])


def test_plan_no_split_at_boundary() -> None:
    text = " ".join(f"w{n}" for n in range(150))
    script = ReviewScript(
        sections=[ReviewSection(id="s", type="hook", paragraphs=[_paragraph__chunks("p", text)])]
    )
    assert len(plan_chunks(script, voice="v")) == 1


class _FakeTTS(TTSPort):
    def __init__(self) -> None:
        self.unloaded = False

    def synthesize(self, request: TTSRequest) -> SpeechAudio:
        frames = int(len(request.text) * 100)
        return SpeechAudio(
            duration_seconds=frames / 16000, sample_rate=16000, audio=b"\x00" * frames * 2
        )

    def unload(self) -> None:
        self.unloaded = True


def test_synthesize_writes_valid_wav(tmp_path: Path) -> None:
    port = _FakeTTS()
    chunks = plan_chunks(_script__chunks(), voice="Ryan")[:2]
    results = synthesize_chunks(chunks, port, tmp_path / "jobs", "job_1")
    assert port.unloaded is True
    for result in results:
        assert result.path.is_file()
        with wave.open(str(result.path), "rb") as wav:
            assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
            assert wav.getnframes() > 0
    assert results[0].path.name == f"{results[0].chunk.chunk_id}.wav"


def test_synthesize_single_chunk_retry(tmp_path: Path) -> None:
    port = _FakeTTS()
    [chunk] = plan_chunks(_script__chunks(), voice="Ryan", emotion="sad")[:1]
    result = synthesize_chunk(chunk, port, tmp_path / "jobs", "job_1")
    assert result.chunk.emotion == "sad"
    assert result.duration_seconds >= 0.0


def test_write_wav_round_trip(tmp_path: Path) -> None:
    audio = SpeechAudio(duration_seconds=0.5, sample_rate=16000, audio=b"\x01" * 16000)
    path = write_wav(tmp_path / "a.wav", audio)
    assert path.stat().st_size == 44 + 16000

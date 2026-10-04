"""T008 acceptance: cache identity, safe lookup, invalidation."""

from pathlib import Path

from movie_review.cache.keys import CacheSpec, cache_key
from movie_review.cache.manager import CacheManager


def _spec(**overrides: object) -> CacheSpec:
    base: dict[str, object] = {
        "stage": "vision",
        "stage_version": "v1",
        "input_hash": "in",
        "dependency_hashes": {"frame": "f"},
        "model_id": "Qwen3-VL",
        "model_version": "1.0",
        "prompt_version": "scene_analysis:v1",
        "generation_config": {"temperature": 0.4},
    }
    base.update(overrides)
    return CacheSpec.model_validate(base)


def test_key_deterministic_and_order_independent() -> None:
    first = cache_key(_spec())
    second = cache_key(
        CacheSpec(
            generation_config={"temperature": 0.4},
            prompt_version="scene_analysis:v1",
            model_version="1.0",
            model_id="Qwen3-VL",
            dependency_hashes={"frame": "f"},
            input_hash="in",
            stage_version="v1",
            stage="vision",
        )
    )
    assert first == second
    assert len(first) == 64


def test_any_change_misses() -> None:
    baseline = cache_key(_spec())
    variants = [
        _spec(stage="other"),
        _spec(stage_version="v2"),
        _spec(input_hash="other"),
        _spec(dependency_hashes={"frame": "g"}),
        _spec(model_id="Other"),
        _spec(model_version="2.0"),
        _spec(prompt_version="scene_analysis:v2"),
        _spec(generation_config={"temperature": 0.9}),
    ]
    for variant in variants:
        assert cache_key(variant) != baseline


def test_store_lookup_round_trip(tmp_path: Path) -> None:
    manager = CacheManager(tmp_path / "cache")
    key = cache_key(_spec())
    assert manager.lookup(key) is None
    stored = manager.store(key, b"payload")
    assert stored.is_file()
    assert manager.lookup(key) == stored
    assert stored.read_bytes() == b"payload"


def test_json_round_trip_and_reuse(tmp_path: Path) -> None:
    first = CacheManager(tmp_path / "cache")
    second = CacheManager(tmp_path / "cache")
    key = cache_key(_spec())
    first.store_json(key, {"events": [1, 2]})
    assert second.lookup_json(key) == {"events": [1, 2]}


def test_tampered_payload_is_miss_and_cleaned(tmp_path: Path) -> None:
    manager = CacheManager(tmp_path / "cache")
    key = cache_key(_spec())
    stored = manager.store(key, b"payload")
    stored.write_bytes(b"tampered")
    assert manager.lookup(key) is None
    assert not stored.exists()
    # A later store starts clean and hits again.
    manager.store(key, b"payload")
    assert manager.lookup(key) is not None


def test_tampered_sidecar_is_miss(tmp_path: Path) -> None:
    manager = CacheManager(tmp_path / "cache")
    key = cache_key(_spec())
    manager.store(key, b"payload")
    (tmp_path / "cache" / f"{key}.meta.json").write_text("not json", encoding="utf-8")
    assert manager.lookup(key) is None


def test_invalidate(tmp_path: Path) -> None:
    manager = CacheManager(tmp_path / "cache")
    key = cache_key(_spec())
    assert manager.invalidate(key) is False
    manager.store(key, b"payload")
    assert manager.invalidate(key) is True
    assert manager.lookup(key) is None
    assert list((tmp_path / "cache").iterdir()) == []

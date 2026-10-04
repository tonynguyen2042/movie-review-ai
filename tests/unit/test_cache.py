"""T008 acceptance: cache identity, safe lookup, invalidation."""

from movie_review.cache.keys import CacheSpec, cache_key


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

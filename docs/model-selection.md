# Choosing the models

Five slots, four profiles, and a benchmark. This document says which is
which and how to measure before you commit.

---

## The slots

| Slot | What it does | Adapters |
|---|---|---|
| `asr` | transcribes the dialogue | `whisper_mlx`, `openai_compat` |
| `vision` | describes each scene's frames | `qwen_vl`, `openai_compat` |
| `reasoning` | the events, the arcs, the themes, the twists, the script | `qwen`, `openai_compat` |
| `critic` | the second pass over the finished script | `qwen`, `openai_compat` |
| `tts` | speaks the narration | `qwen_tts`, `openai_compat` |
| `translation` | translates the script when the languages differ | `qwen`, `openai_compat` |

The critic and the translation are **optional**: a profile can leave them
disabled, and a disabled slot costs nothing.

---

## The profiles

The profiles live in the `profiles` section of
[`config/config.yaml`](../config/config.yaml). Select one with
`models.profile` or `--profile`.

### `fast`

| Slot | Model |
|---|---|
| asr | `whisper-large-v3-turbo` |
| vision | `Qwen3-VL-small` |
| reasoning | `Qwen3.5-9B` |
| critic | `Qwen3.5-9B` (disabled) |
| tts | `Qwen3-TTS-0.6B` |

The smallest set. Use it to try the tool, to check the configuration, or on
a machine that cannot hold the bigger models.

### `balanced`

| Slot | Model |
|---|---|
| asr | `whisper-large-v3-turbo` |
| vision | `Qwen3-VL` |
| reasoning | `Qwen3.5-27B` |
| critic | `Qwen3.5-122B-A10B` (disabled) |
| tts | `Qwen3-TTS-12Hz-1.7B` |

The default. The 27B reasoning model is the one that writes the script, and
the script is the product.

### `quality`

| Slot | Model |
|---|---|
| asr | `whisper-large-v3-turbo` |
| vision | `Qwen3-VL-large` |
| reasoning | `Qwen3.5-27B` |
| critic | `Qwen3.5-122B-A10B` (**enabled**) |
| tts | `Qwen3-TTS-12Hz-1.7B` |

The same writer, a bigger vision model, and the second pass enabled: the
critic reads the finished script and reports its coherence, its hook, its
pacing and its unsupported claims.

The critic runs **once, at the end**, on the script — not per scene. A
122B model on every scene would cost more than the rest of the pipeline.

### `remote`

Every slot points at an OpenAI-compatible endpoint. Use it when the models
live on another machine — vLLM, `faster-whisper-server`, llama.cpp, LM
Studio, Ollama, TGI.

```bash
uv run movie-review process movie.mkv --profile remote
```

The remote profile ships with placeholder addresses. Change them in
`config/config.yaml` before you use it.

**Remote means the movie leaves the machine.** `privacy.cloud_ai` gates
it: with the default `false`, a remote model is refused. The policy
travels on the model spec, so an adapter cannot be built that ignores it.

---

## Measuring before you choose

README §56 says the exact model sizes "SHALL be benchmarked on the target
Mac rather than hard-coded". So measure them.

```bash
# one slot: load time, throughput, peak memory
uv run movie-review benchmark --mode model --slot reasoning

# the whole pipeline, stage by stage
uv run movie-review benchmark --mode pipeline --movie ./reference.mkv
```

Or through the scripts:

```bash
python scripts/benchmark_models.py --slot vision --movie ./reference.mkv
python scripts/benchmark_pipeline.py --movie ./reference.mkv
```

Use a **short reference movie** — ten to fifteen minutes. A full-length
movie takes hours to benchmark and tells you no more.

The report is JSON:

```json
{
  "mode": "pipeline",
  "total_seconds": 812.4,
  "slowest": { "stage": "vision", "seconds": 411.8, "success": true },
  "stages": [ ... ]
}
```

The slowest stage is where the time goes. If it is `vision`, a smaller
vision model buys more than a faster one does.

---

## Memory

The target is Apple Silicon with 128 GB of unified memory. The models are
loaded one at a time and released when their stage is done, so the peak is
the largest single model rather than the sum.

When a model does not fit, the run detects the out-of-memory condition,
releases the model, clears the cache, reduces the workload and retries:

```text
OOM detection → model release → cache cleanup → reduced workload → retry
```

The reduced workload is a smaller sampling budget: fewer frames per scene,
a shorter script. The result is a shorter review, not a failed run.

To measure the memory yourself:

```bash
python scripts/benchmark_models.py --slot vision --movie ./reference.mkv
```

The report carries `peak_memory_mb`.

---

## Writing your own profile

Add it to the `profiles` section of `config/config.yaml`:

```yaml
profiles:
  mine:
    asr:
      model: whisper-large-v3-turbo
    vision:
      model: Qwen3-VL
      precision: 4bit
    reasoning:
      model: Qwen3.5-27B
      precision: 4bit
    tts:
      model: Qwen3-TTS-12Hz-1.7B
```

Then `--profile mine`. The name appears in `movie-review --help`, because
the CLI reads the catalogue rather than hard-coding a list.

### Pointing a slot at a different runtime

```yaml
    reasoning:
      model: Qwen3.5-27B
      backend: openai_compatible
      base_url: http://192.168.1.144:8000/v1
      timeout_seconds: 120
      api_key_env: MY_API_KEY
```

The key comes from the **environment**, never from the file. A token in a
tracked YAML file is a leak.

### Retries on a slot

A remote slot retries a failed request on its own: 429s, 5xx, timeouts and
dropped connections. Three keys decide how hard it tries, and they exist
because hosts differ — a whisper.cpp box that answers in two seconds and a
vLLM engine that needs a minute to reload after a crash do not want the same
schedule.

```yaml
    vision:
      model: Qwen3-VL
      backend: openai_compatible
      base_url: http://192.168.1.144:8000/v1
      timeout_seconds: 300
      attempts: 4            # total attempts: the first try plus three retries
      backoff_seconds: 5     # 5 s, 10 s, 20 s between them
      max_backoff_seconds: 30
```

Unset, the slot uses `attempts: 3`, `backoff_seconds: 0.5` and
`max_backoff_seconds: 30` — about 1.5 s of patience, which is fine for a blip
and useless for an engine that is coming back up. A 4xx is never retried: the
request itself is at fault, and repeating it only wastes the server's time.

`attempts` counts requests, not retries. A 5xx that outlives the schedule is
reported as "unavailable", so the stage-level retry gets a second, cheaper
chance — the per-scene cache means a retried stage does not redo the scenes it
already analysed.

---

## What changes when you switch models

Switching the reasoning model invalidates the cached answers it produced:
the model is part of the cache identity. Switching the prompt invalidates
the answers that prompt produced: the prompt version is part of it too.

So a new model does not silently serve the old model's output — it does
the work again. That is the point of a content-addressed cache.

```bash
# redo the work with the new model
uv run movie-review process movie.mkv --profile quality --from-stage events --force
```

---

## The generation config

Every model slot carries a sampling config:

```yaml
    reasoning:
      model: Qwen3.5-27B
      generation:
        seed: 0
        temperature: 0.4
        top_p: 0.95
```

The sampling is part of the cache identity. Two runs with the same prompt
and a different temperature are two different answers, and they do not
share a cache entry.

`--deterministic` pins the seed to `0`, the temperature to `0` and the
top-p to `1` for every slot at once.

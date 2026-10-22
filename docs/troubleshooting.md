# Troubleshooting

What to do when something fails. Every message below is one the tool
actually prints.

Start here:

```bash
uv run movie-review inspect job_20261006_001     # the job record
uv run movie-review validate job_20261006_001    # are the artifacts intact?
uv run movie-review process movie.mkv --verbose  # the debug log
```

The job record carries `status`, `error`, `failed_stage` and `retry_count`.
The error names the stage that failed and why.

---

## The model is unavailable

```text
ASR model unavailable: whisper-large-v3-turbo: mlx-whisper is not installed
TTS model unavailable: Qwen3-TTS-12Hz-1.7B: mlx-audio is not installed
```

The local runtime is not installed, or you are not on Apple Silicon.

The local adapters need `mlx-whisper` (ASR), `mlx-vlm` (vision),
`mlx-lm` (reasoning) and `mlx-audio` (TTS). They are Apple-silicon only.

**What to do:**

- On a non-Apple machine, use the `remote` profile with OpenAI-compatible
  endpoints.
- Or install the missing package.

```bash
uv run movie-review process movie.mkv --profile remote
```

---

## The remote model is refused

```text
Model ... may not be used while privacy.cloud_ai is off
```

A remote model would send movie content off the machine, and
`privacy.cloud_ai` is `false` by default. That is the local-first promise
being kept.

**What to do:** turn it on only if you mean it.

```yaml
privacy:
  cloud_ai: true
```

Or use `MOVIE_REVIEW_PRIVACY__CLOUD_AI=true`.

---

## FFmpeg is missing or fails

```text
The ffmpeg/ffprobe binary is not installed or not on PATH.
Cannot extract audio from movie.mp4: ffmpeg failed: ...
```

The media tooling is FFmpeg. It is not bundled.

**What to do:** install FFmpeg, and make sure both `ffmpeg` and `ffprobe`
are on the PATH.

```bash
# macOS
brew install ffmpeg
# Debian/Ubuntu
sudo apt install ffmpeg
# Windows
winget install Gyan.FFmpeg
```

If they are installed but somewhere unusual, name them explicitly:

```yaml
media:
  ffmpeg: /opt/homebrew/bin/ffmpeg
  ffprobe: /opt/homebrew/bin/ffprobe
```

### The proxy fails with "width not divisible by 2"

```text
Cannot generate proxy for AI.mp4: ffmpeg failed: [libx264] width not divisible
by 2 (853x480)
```

`media.proxy.max_width` and `max_height` describe a **box**, not a size: FFmpeg
fits the source into it and scales each side on its own, so a 16:9 film in a
854x480 box wants 853 px and `libx264` (with `yuv420p`) refuses an odd side.
The scale filter now rounds both sides to an even number, so 854x480 produces
854x480 or 852x480 and encodes. If you see this message, the build predates that
fix: pick an even pair such as 852x480, or update.

---

## The source-footage controls refuse the edit

```text
Source ratio 0.512 exceeds limit 0.350
Source footage 512.0s exceeds limit 420.0s
```

The review asked for more source footage than the controls allow. The
controls are in `config/default.yaml`:

```yaml
source_video:
  max_clip_seconds: 8.0
  preferred_clip_seconds: 3.0
  max_source_ratio: 0.35
  max_total_seconds: 420.0
```

The ratio is the source footage as a share of the movie's length: the
review may not use more than a third of the film. That is a product
control, **not a legal guarantee** — no fixed clip duration or percentage
is automatically safe to publish.

**What to do:** lower `preferred_clip_seconds`, or raise the limits if you
have the rights to the footage.

---

## The job stopped at a stage

```text
Job job_20261006_001 failed at 'vision': cannot reach
http://gpu:8000/v1/chat/completions: connection refused. Re-run the pipeline to try again.
```

The job failed and the stage that ran next refused to continue. The message
names the stage that failed and repeats the error it recorded; the job row
holds the same pair as `failed_stage` and `error`.

**What to do:** look at the job record, then resume it.

```bash
uv run movie-review inspect job_20261006_001
uv run movie-review resume job_20261006_001
```

`resume` picks up from the recorded checkpoint and skips the stages that
already completed. `retry` runs the failed stage again.

---

## The quality gate sent it to review

```text
status=NEEDS_REVIEW
```

The gate ran and the review did not pass. The report says why:

```bash
uv run movie-review inspect job_20261006_001
cat data/jobs/job_20261006_001/qc/quality-report.json
```

The gates are the evidence coverage, the timeline consistency, the
character consistency, the duration accuracy and the visual coherence. The
commonest failure is the duration: a script that came out much shorter or
longer than the target.

**What to do:** read the report, then either fix the cause or redo the
stage.

```bash
uv run movie-review process movie.mkv --from-stage review --force
```

---

## Out of memory

The run detects the condition, releases the model, clears the cache,
reduces the workload and retries. The result is a shorter review, not a
failed run.

**What to do:** if it happens on every run, use a smaller profile.

```bash
uv run movie-review process movie.mkv --profile fast
```

The peak is the largest single model, not the sum of them — the models are
loaded one at a time. Measure yours:

```bash
python scripts/benchmark_models.py --slot vision --movie ./reference.mkv
```

---

## The remote server answers 500

```text
RemoteUnavailableError: HTTP 500 from http://192.168.1.144:8000/v1/chat/completions:
{"object": "error", "message": "..."}
```

The request was well formed and the host failed to serve it. A 500, a 503 and
a 429 are retried, so a message that reaches the operator means the slot spent
its whole budget first — `attempts`, `backoff_seconds` and
`max_backoff_seconds` per slot in `config/models.yaml`.

The body after the URL is the server's own explanation, quoted up to 300
characters. It is the first thing to read:

- an engine or CUDA failure: the server restarted its model; give the slot a
  longer `backoff_seconds` and more `attempts` so it can wait the restart out
- a context-length error: the request is too large for the model; lower
  `max_tokens` or sample fewer frames per scene
- a 4xx never reaches this message: it is the request's own fault and is not
  retried

**What to do:** read the quoted body, fix the cause, then re-run. Scenes that
were already analysed are cached, so the re-run does not pay for them again.

---

## The remote server is not answering

```text
RemoteUnavailableError: cannot reach http://192.168.1.144:8000/v1
```

**What to do:**

- check the server is up and the address is right in `config/models.yaml`
- check the timeout is long enough for the model to load
  (`timeout_seconds` per slot)
- check the network

---

## The disk is full

A feature-length run leaves hundreds of megabytes of frames behind unless
you keep them, and the cache grows without bound.

**What to do:**

```bash
python scripts/cleanup_cache.py --dry-run     # see what would go
python scripts/cleanup_cache.py --older-than 7d --frames
```

Or keep the frames in the first place and skip the cleanup:

```bash
uv run movie-review process movie.mkv --keep-intermediates
```

---

## The arguments are wrong

```text
Invalid value for '--from-stage': 'scnes' is not one of [...]
Give --from-stage or --stage-from, not both.
```

The stage names are checked before the job is created, so a typo is a
usage error rather than a stray job.

The names are:

```text
ingest  scenes  transcript  vision  characters  diarization
locations  events  arcs  themes  twists  story
review  verify  review-translate
tts-chunks  tts-concat  tts-reconcile
render-manifest  subtitles  render  quality
```

`movie-review stages` prints the same list.

---

## The artifacts do not match the database

```text
job_id=job_20261006_001 status=COMPLETED valid=False
```

A recorded artifact is missing, or its hash does not match what was
recorded. Something outside the tool changed the files.

**What to do:** find out what changed.

```bash
uv run movie-review validate job_20261006_001
```

The report lists what is missing, what is corrupt and what names an unsafe
path. A job whose artifacts are damaged can be redone:

```bash
uv run movie-review process movie.mkv --from-stage story --force
```

---

## Nothing happens and no output appears

The CLI prints JSON logs to stderr and the progress to stdout. If the
progress is missing entirely, check that progress is enabled:

```bash
uv run movie-review process movie.mkv --verbose
```

The pipeline emits a heartbeat every ten seconds while a stage runs, so a
long stage shows a line rather than silence.

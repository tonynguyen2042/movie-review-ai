# Getting Started — movie-review-ai

A step-by-step guide for **running** the tool. If you want to *contribute* code, see [`AGENTS.md`](../AGENTS.md) instead.

Every command and output below was captured by running the tool on `master`, not recalled. Where something is not finished, this guide says so plainly rather than implying it works.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Install](#2-install)
3. [Verify the install](#3-verify-the-install)
4. [Configure](#4-configure)
5. [Submit a movie](#5-submit-a-movie)
6. [Pipeline stages](#6-pipeline-stages)
7. [Inspect, validate, resume, retry](#7-inspect-validate-resume-retry)
8. [The job dashboard](#8-the-job-dashboard)
9. [Where your data lives](#9-where-your-data-lives)
10. [What does not work yet](#10-what-does-not-work-yet)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. What you need

| Requirement | Notes |
|---|---|
| **Apple Silicon Mac** | The bundled `fast`/`balanced`/`quality` profiles load MLX weights, which need Apple hardware. Other platforms can install, run the CLI, and use a [`remote` model profile](#remote-models). |
| **Python 3.12+** | Check with `python --version`. |
| **FFmpeg + FFprobe** | Video I/O. Must be on your `PATH`. |
| **Disk space** | Frames, audio, and caches add up. Budget several GB per movie. |
| **A movie file** | Any format FFmpeg can read (`.mp4`, `.mkv`, `.mov`). |

```bash
python --version      # expect 3.12 or newer
ffmpeg -version       # must be found
ffprobe -version      # must be found
```

If `ffmpeg` or `ffprobe` is missing:

```bash
# macOS
brew install ffmpeg

# Windows (winget)
winget install Gyan.FFmpeg

# Debian/Ubuntu
sudo apt install ffmpeg
```

---

## 2. Install

We use [`uv`](https://docs.astral.sh/uv/) for fast, reproducible installs.

```bash
# 1. Install uv (skip if you already have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# 2. Clone the repository
git clone https://github.com/tonynguyen2042/movie-review-ai.git
cd movie-review-ai

# 3. Create the environment and install
uv sync --extra dev

# 4. Confirm the CLI entry point exists
uv run movie-review version
```

```
0.1.0
```

---

## 3. Verify the install

```bash
uv run movie-review --help
```

```text
 Usage: movie-review [OPTIONS] COMMAND [ARGS]...

 Local-first movie-to-review pipeline.

+- Options -------------------------------------------------------------------+
| --verbose                     Enable debug logging.                         |
| --install-completion          Install completion for the current shell.     |
| --show-completion             Show completion for the current shell, to     |
|                               copy it or customize the installation.        |
| --help                        Show this message and exit.                   |
+-----------------------------------------------------------------------------+
+- Commands ------------------------------------------------------------------+
| process    Accept a movie, create a job, and optionally run the full        |
|            pipeline.                                                        |
| inspect    Print a job record as JSON.                                      |
| validate   Check a job record is well-formed and validate its artifacts.    |
| resume     Resume an interrupted job from its last checkpoint.              |
| retry      Retry a failed job or specific stage.                            |
| stages     List available pipeline stages in execution order (T086).        |
| version    Print the package version.                                       |
| dashboard  Start the web job dashboard (T089).                              |
+-----------------------------------------------------------------------------+
```

Confirm the environment is healthy:

```bash
uv run pytest -q
```

On `master` this currently reports **811 passed**. The number grows as work lands — treat any *failure*, not the count, as the real signal. Run it once before you rely on the tool, so a later failure is clearly yours.

---

## 4. Configure

Configuration lives in [`config/default.yaml`](../config/default.yaml), loaded automatically. You do not need a config flag for normal use.

### Precedence

Highest first:

1. Explicit CLI options
2. `MOVIE_REVIEW_*` environment variables
3. `config/default.yaml`
4. Built-in defaults

Environment variables use the prefix `MOVIE_REVIEW_`, and `__` separates nested keys:

```bash
# Windows PowerShell
$env:MOVIE_REVIEW_PATHS__DATA_DIR = "D:\media-review\data"

# bash / zsh
export MOVIE_REVIEW_MODELS__PROFILE=quality
```

### Key settings

| Setting | Default | What it means |
|---|---|---|
| `models.profile` | `balanced` | Model profile: `fast`, `balanced`, `quality`, or `remote`. Selects the model set from `config/models.yaml`. |
| `runtime.backend` | `mlx` | Local MLX runtime. |
| `paths.data_dir` | `data` | Where the job database and artifacts are written. |
| `paths.output_dir` | `data/output` | Where finished videos are written. |
| `pipeline.review.target_duration_minutes` | `20` | Target review length. |
| `pipeline.review.target_wpm` | `150` | Narration words per minute. |
| `source_video.max_clip_seconds` | `8.0` | Longest single source clip used. |
| `source_video.max_source_ratio` | `0.35` | Cap on source footage as a share of runtime. |
| `logging.level` | `INFO` | Use `DEBUG` when troubleshooting. |
| `logging.json_output` | `true` | Machine-readable log lines. Set `false` for human-readable output. |
| `privacy.cloud_ai` | `false` | Keep everything local. Leave this `false`. |
| `media.ffmpeg` / `media.ffprobe` | `ffmpeg` / `ffprobe` | Absolute paths if not on `PATH`. |

### About `source_video` limits

These are **product controls, not legal guarantees.** They bound how much source footage the tool uses per output. They do not make any clip duration or percentage automatically safe to publish, and they are not legal advice. You are responsible for what you upload.

### Remote models

The default profiles load MLX weights locally, which needs Apple Silicon. To run models on another host behind OpenAI-compatible endpoints — vLLM, `faster-whisper-server`, llama.cpp, LM Studio, Ollama, TGI — use the shipped `remote` profile:

```bash
# select it
$env:MOVIE_REVIEW_MODELS__PROFILE = "remote"
```

Then edit the `remote:` block in [`config/models.yaml`](../config/models.yaml) and set each `base_url`. Slots are independent, so you can keep one model local and run the rest remotely.

Two things to get right:

- **Credentials:** `api_key_env` takes the *name* of an environment variable, never the secret itself, so tokens stay out of version control. Leave it unset for a LAN server needing no auth.
- **TTS format:** ask the server for `wav`. Duration is measured from the returned bytes, and `mp3` is rejected rather than guessed — a wrong duration would silently corrupt subtitle timing.

The `remote` profile in `config/models.yaml` ships with placeholder hostnames (`gpu-box.local`). Edit it before use.

---

## 5. Submit a movie

```bash
uv run movie-review process ./my-movie.mp4 \
  --language en \
  --target-language en \
  --duration 20m \
  --style youtube \
  --profile balanced
```

### Options

| Option | Default | Description |
|---|---|---|
| `MOVIE` | required | Path to the input movie. |
| `--language` | `en` | Source language: the movie's dialogue, and the language the review is written in. Given to ASR so it does not have to be detected. |
| `--target-language` | = `--language` | Language the narration is spoken in. Omit it and nothing is translated. |
| `--duration` | `20m` | Target length, e.g. `20m` or `15`. |
| `--style` | `youtube` | Review style profile. |
| `--profile` | from config | Model profile: `fast`, `balanced`, `quality`, or `remote`. Overrides `config/default.yaml` and `MOVIE_REVIEW_MODELS__PROFILE` for this run. |
| `--spoilers` | `full` | Spoiler level. |
| `--output` | `./output` | Output directory. |
| `--db-path` | `<data_dir>/jobs.db` | Use a specific jobs database. |
| `--stage-from` | — | Start from this stage. See [Pipeline stages](#6-pipeline-stages). |
| `--stage-to` | — | Stop after this stage. |
| `--no-run` | off | Create the job record only, do not run the pipeline. |

`--verbose` goes **before** the subcommand: `movie-review --verbose process ...`.

### What actually happens

`process` creates the job and then runs the pipeline. The first line is the job ID you need for everything else:

```text
job_id=job_20261006_001 status=CREATED
```

The pipeline then reports each stage as it starts, so you can see it working:

```text
  -> ingest (stage 1/18) ...
  ingest: OK (14s, stage 1/18)
  -> scenes (stage 2/18) ...
  ... scenes still running (10s)
  scenes: OK (1m02s, stage 2/18)
  -> vision (stage 3/18) ...
  vision [############------------]  50%   frame 180/360 (2m10s)
  vision [########################] 100%   frame 360/360 (4m05s)
  vision [########################] 100%   scene 210/420 (48m12s)
  vision: OK (52m30s, stage 3/18)
```

Every line starting with `->` means that stage has just started; the `stage N/18` counter is your position in the run. A `... still running` line repeats every 10 seconds while a stage is still working — a single stage such as transcription or rendering can run for many minutes with no output of its own, and that heartbeat is what tells you it is alive rather than hung.

A progress bar like `vision [####----] 50%` appears for stages that can divide their work up front, currently frame sampling and visual scene analysis. Both count items — frames and scenes — so the percentage is real rather than an estimate. Progress lines are throttled to one every 2 seconds: a long film reports once per scene, and printing all of them would scroll the start lines and results off the screen.

Stages whose work cannot be divided report no bar. Transcription, TTS and rendering are each a single long call, and inventing a percentage that advances on its own would be worse than saying nothing — for those, the 10-second heartbeat and the elapsed time are the signal.

### Speaking in another language

`--language` is the source: the movie's dialogue, and the language the review is written in. `--target-language` is what the narration is spoken and subtitled in. Omit it and the two are the same, so nothing is translated and no extra model calls are made:

```bash
# Vietnamese movie, English narration
uv run movie-review process ./phim.mp4 --language vi --target-language en

# No target: narration stays in the movie's own language
uv run movie-review process ./phim.mp4 --language vi
```

Translation runs in its own `review-translate` stage, after the script is written and before any audio exists, so chunking, synthesis, subtitles and the quality gate all see one language and cannot disagree with each other. The translated script goes to `review/review-script.<lang>.json` and the source is left untouched, so changing the target later re-translates from the original rather than from the previous translation.

Each paragraph is cached on its own text, so a retry re-translates only what is missing. Names and `INSUFFICIENT_EVIDENCE` markers must survive translation intact — a model that drops the marker turns "we cannot support this" into a confident sentence, and the paragraph is rejected rather than published.

Translation has its own model slot in `config/models.yaml`, so it can be a different size, quantisation or host than the reasoning model:

```yaml
translation:
  model: Qwen3.5-9B
  backend: openai_compatible
  base_url: http://gpu-box.local:8000/v1
```

A profile that omits the slot borrows `reasoning`, which is what it did before the slot existed. The paragraph cache is keyed on the translation model, so pointing it at a different checkpoint re-translates rather than reusing the previous model's prose.

When a stage fails, the run stops there and exits non-zero:

```text
  -> ingest ...
  ingest: FAILED (0s)
    error: ffprobe failed: ... moov atom not found
```

**The job ID goes to stdout; progress goes to stderr.** That keeps stdout parseable, so you can capture just the ID:

```bash
JOB=$(uv run movie-review process ./my-movie.mp4 2>/dev/null | cut -d= -f2 | cut -d' ' -f1)
```

Progress lines are also suppressed automatically when stderr is not a terminal, so redirected logs stay clean.

`inspect` shows why:

```json
{
  "created_at": "2026-10-06T04:25:04.665031Z",
  "error": "ffprobe failed: [mov,mp4,m4a,...] moov atom not found\n...: Invalid data found when processing input",
  "failed_stage": "ingest",
  "input_file": "./my-movie.mp4",
  "job_id": "job_20261006_001",
  "retry_count": 0,
  "status": "FAILED",
  "updated_at": "2026-10-06T04:25:04.866968Z"
}
```

Everything except the `job_id=` line goes to stderr: structured JSON logs, stage progress, and errors. That leaves stdout holding only the job ID, so you can pipe it into another command.

**Save the `job_...` value.** Every other command needs it.

### Queue without running

```bash
uv run movie-review process ./my-movie.mp4 --no-run
```

```text
job_id=job_20261006_002 status=CREATED
Pipeline execution skipped (--no-run). Use 'resume' to start.
```

---

## 6. Pipeline stages

```bash
uv run movie-review stages
```

```text
  ingest: Ingest movie metadata
  scenes: Detect scenes
  transcript: Transcribe dialogue
  vision: Visual scene analysis
  characters: Discover and link characters
  locations: Extract locations
  events: Extract story events
  arcs: Extract story arcs
  themes: Extract themes
  twists: Detect twists
  story: Build movie-analysis.json
  review: Write review script
  review-translate: Translate script to the target language
  tts-chunks: Plan and synthesize TTS chunks
  tts-concat: Concatenate narration
  tts-reconcile: Reconcile narration duration
  render-manifest: Build render manifest
  render: Render final video
  quality: Run quality gate
```

Run a range instead of the whole pipeline:

```bash
# just transcription
uv run movie-review process ./my-movie.mp4 --stage-from transcript --stage-to transcript

# rebuild the review script onward, reusing cached analysis
uv run movie-review process ./my-movie.mp4 --stage-from review
```

Stage names are validated up front. An unknown name is rejected as a usage error and exits `2` — no job record is created, so a typo cannot leave a stray job behind:

```bash
$ uv run movie-review process ./my-movie.mp4 --stage-from nope
Invalid value for '--stage-from': 'nope' is not one of 'ingest', 'scenes',
'transcript', 'vision', 'characters', 'locations', 'events', 'arcs', 'themes',
'twists', 'story', 'review', 'review-translate', 'tts-chunks', 'tts-concat',
'tts-reconcile', 'render-manifest', 'render', 'quality'
$ echo $?
2
```

Stages are **idempotent**: re-running one overwrites its artifacts rather than duplicating them, and completed work is reused through the cache. That is what makes `--stage-from` safe to re-run.

---

## 7. Inspect, validate, resume, retry

### Inspect

```bash
uv run movie-review inspect job_20261006_001
```

Prints the whole job record as JSON — the quickest way to see status, `error`, `failed_stage`, and `retry_count`.

### Validate

```bash
uv run movie-review validate job_20261006_001
```

```text
job_id=job_20261006_001 status=FAILED valid=True
```

`valid=True` means the job record is well-formed and its artifacts are intact. It does **not** mean the review succeeded — a job that failed cleanly can still be valid. Exit code is `1` when validation fails.

### Resume

```bash
uv run movie-review resume job_20261006_001
```

Restarts a job from its recorded checkpoint, skipping stages already recorded as complete. It reports progress the same way `process` does:

```text
  -> scenes ...
  scenes: OK (412ms)
  -> transcript ...
  transcript: OK (1m52s)
```

Resume works from any non-terminal status. See [What does not work yet](#10-what-does-not-work-yet) for the `FAILED` case.

### Retry

```bash
uv run movie-review retry job_20261006_001
uv run movie-review retry job_20261006_001 --stage quality
```

Retries a bounded number of times with backoff, then surfaces the last error instead of looping forever. `--stage` targets one stage rather than the recorded failure point. Each attempt reports its own progress line, so a retry loop is visible rather than a long silence.

### Debug logging

```bash
uv run movie-review --verbose inspect job_20261006_001
```

---

## 8. The job dashboard

```bash
uv run movie-review dashboard --open-browser
```

Serves a local web view of jobs and their status. Options:

| Option | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Host to bind to. Loopback by default. |
| `--port` | `8080` | Port to listen on. |
| `--db-path` | `<data_dir>/jobs.db` | Jobs database to read. |
| `--open-browser` / `--no-open-browser` | `--no-open-browser` | Open a browser on start. |

Endpoints: `/` (the page), `/api/status`, `/api/jobs`, and `/api/jobs/<job_id>`.

> If the job list looks empty, you almost certainly started a job with a custom `--db-path` and did not pass the same one to `dashboard`. The dashboard reads only the database it is given.

It binds to loopback by default. If you change `--host` to expose it beyond your machine, understand that this dashboard has no authentication — do not bind it to a public interface.

The other six viewers (timeline, characters, story graph, script editor, visual timeline editor, QC report) are Python classes that generate standalone HTML via `to_html()`. They are not served over HTTP; import them from your own code.

---

## 9. Where your data lives

```text
data/
├── jobs.db              # SQLite job database
├── cache/               # Stage cache, keyed by input + model + prompt version
└── jobs/
    └── <job_id>/        # Per-job artifacts
        ├── media/  scenes/  frames/  transcript/  diarization/
        ├── vision/  characters/  story/  review/
        └── tts/  render/  qc/  logs/
```

Artifact paths are deterministic and validated against path traversal, so a job ID cannot escape its own directory. Files under `data/` are git-ignored — your media never enters version control.

Cache entries are keyed by input hash plus the model, prompt, and stage versions that produced them. Changing a prompt in `config/prompts/` invalidates the AI artifacts that depended on it rather than silently reusing stale ones.

---

## 10. What does not work yet

Stated plainly, because a guide that implies these work is worse than one that omits them.

### `resume` and `retry` on a `FAILED` job

**`FAILED` is currently terminal.** Nothing moves a job back out of it, and every stage refuses to run against a `FAILED` job. So `retry` re-runs the stage, the stage rejects the status, and the retry exhausts:

```text
$ uv run movie-review retry job_20261006_001
Retrying stage: ingest
Retry exhausted for ingest: Stage ingest failed: Job job_20261006_001 failed; ...
```

This is a real limitation, not a usage error on your part. Until `FAILED` becomes re-enterable, **the way to re-run a failed job is to submit it again** with `--stage-from` set to the stage that failed:

```bash
uv run movie-review process ./my-movie.mp4 --stage-from ingest
```

`resume` does work correctly for jobs in any non-terminal status — that path is the intended one.

### AI stages need real models

Nothing in the test suite exercises a real model or a real FFmpeg encode. The pipeline is exercised with mocks, so an end-to-end run against a real movie with real weights has not been validated. Expect to hit rough edges on a first genuine run.

### Not yet wired to the CLI

Analyzing and rendering are reachable as Python APIs but have no dedicated CLI command. Publishing now has one - `movie-review publish` - but it is opt-in by design: it previews the title, description and tags and stops unless you pass `--confirm`. Nothing it generates ever uploads on its own.

## 10a. Publishing a review

Once a job has rendered a video, `movie-review publish` generates the packaging for it and can upload it.

Start with the platforms the host can actually reach:

```console
$ movie-review publish-platforms
Supported platforms:
  youtube: unavailable -- No publishing backend could be loaded on this host.
  facebook: unavailable -- MOVIE_REVIEW_FACEBOOK_PAGE_ID is not set.
  tiktok: unavailable -- TikTok Content Posting API requires an app that has passed TikTok's developer review. Uploads from an unapproved app are refused by TikTok.
```

Generate and preview the metadata without uploading anything:

```console
$ movie-review publish job_20261007_001 --platform youtube --profile remote
Generated metadata (model=qwen3.5-27b, prompt=publishing_metadata:v1, cache_hit=False)

Video   : data/jobs/job_20261007_001/render/review.mp4
Platform: youtube  privacy=unlisted
Title   : This review argues the letter is the whole film

Description:
A review of the office scenes and what the letter changes.

Tags    : movie review, drama, analysis

Preview only. Re-run with --confirm to upload.
```

Nothing leaves the machine until you add `--confirm`. To edit the packaging before it goes public:

```console
$ movie-review publish job_20261007_001 --title "Your own title" --confirm
```

### Credentials

Credentials come from the environment, never from a config file - a token in a tracked YAML file is a leak.

| Variable | Needed for |
|---|---|
| `MOVIE_REVIEW_FACEBOOK_PAGE_ID` | Facebook Page target |
| `MOVIE_REVIEW_FACEBOOK_TOKEN` | Facebook Page access token |
| `MOVIE_REVIEW_TIKTOK_TOKEN` | TikTok creator access token |

YouTube uses the standard Google client credentials (`~/.gd.json` or the path in `GOOGLE_APPLICATION_CREDENTIALS`).

### What the metadata generator may and may not say

The title, description and tags are written by the reasoning model, constrained by the narration. The model may write about the review and offer opinion. It may not assert anything about the film that the narration does not state - no invented dialogue, scenes, relationships, deaths or chronology - and it may not publish `INSUFFICIENT_EVIDENCE`, which is a status marker for an unsupported claim rather than a selling point.

If the model puts the marker in a title, the run fails rather than publishing it, so a human decides what happens. `movie-review publish` then exists to make that decision easy: read the title, override it if it is wrong, and upload.

If the generated title is wrong or misses, `--title` and `--description` override it.

### Platform differences worth knowing

- **Facebook Page** - Page videos cannot be published unlisted or private per upload; audience is a Page-level setting. Uploading with `--privacy unlisted` is refused with an explanation rather than silently published as public. Reels and Groups are not supported.
- **TikTok** - requires an app that has passed TikTok's developer review. The adapter is written to the documented API but has never been run against a live endpoint.
- **YouTube** - the only adapter whose call shape is exercised against a real client.

### Copyright

`movie-review publish` makes no claim that any clip duration or percentage is legally safe. That determination depends on the actual use and your jurisdiction.

---

## 11. Troubleshooting

### `command not found: movie-review`

Do not call it directly. Use `uv run movie-review ...` from the repository root, or activate the environment:

```bash
# macOS/Linux
source .venv/bin/activate
movie-review version

# Windows PowerShell
.venv\Scripts\Activate.ps1
movie-review version
```

### `Unknown job: ...`

The ID is wrong, or the job is in a different database. Pass `--db-path` if you used a custom one when creating the job.

Every job command reports this the same way and exits `2` — as a usage error, not a traceback.

### `Input file not found`

`process` requires an existing file. Relative paths resolve from your current directory.

### `Cannot find ffmpeg` / `ffprobe not found`

Install FFmpeg (see [Step 1](#1-what-you-need)), or set absolute paths in `config/default.yaml`:

```yaml
media:
  ffmpeg: /opt/homebrew/bin/ffmpeg
  ffprobe: /opt/homebrew/bin/ffprobe
```

### `ffprobe failed: ... moov atom not found`

The file is not a complete, readable video — often a truncated download, a `.part` file, or a renamed non-video. `process` does not validate the file before recording it, so this surfaces at the `ingest` stage.

### Log lines look noisy

JSON logging is intentional and machine-readable. For human-readable output:

```yaml
logging:
  json_output: false
```

### The dashboard shows no jobs

Pass the same `--db-path` you used to create them, or start it without `--db-path` to read the default `<data_dir>/jobs.db`.

### Tests fail after a pull

```bash
uv sync --extra dev
uv run pytest -q
```

---

## See also

- [`README.md`](../README.md) — full product and architecture specification
- [`AGENTS.md`](../AGENTS.md) — contribution workflow and task rules
- [`config/default.yaml`](../config/default.yaml) — all settings with comments
- [`config/models.yaml`](../config/models.yaml) — model profiles, including `remote`

If a step here does not match what you see, that is a bug in the guide or the tool. Open an issue.
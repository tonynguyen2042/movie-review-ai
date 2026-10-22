# The pipeline

Twenty-three stages, in a fixed order, each one writing its own artifacts
and each one idempotent.

---

## The shape of a stage

Every stage follows the same sequence:

```text
validate input → cache lookup → execute → validate output → persist → metrics → complete
```

**Validate input** — refuse the work early rather than half way through it.
A stage that cannot do its job says so before it starts.

**Cache lookup** — the cache key is built from the input hash, the model,
the prompt version, the stage version and the generation config. A hit is
the same answer the last run gave, so the stage skips the expensive part.

**Validate output** — every AI output is checked against its published
JSON Schema before it is persisted. See [schemas.md](schemas.md).

**Persist** — the artifact file is the record of record; the database row
is the queryable copy. Both are written.

**Metrics** — the stage's duration and what it did are logged as JSON.

**Complete** — the job advances to the next state, if this stage owns the
transition.

---

## The state machine

```text
CREATED
  ↓
INGESTING
  ↓
MEDIA_READY
  ↓
SCENES_READY
  ↓
TRANSCRIPT_READY
  ↓
VISUAL_ANALYSIS_READY
  ↓
CHARACTERS_READY
  ↓
EVENTS_READY
  ↓
STORY_READY
  ↓
REVIEW_PLAN_READY
  ↓
SCRIPT_READY
  ↓
SCRIPT_VERIFIED
  ↓
AUDIO_READY
  ↓
EDIT_PLAN_READY
  ↓
RENDERED
  ↓
QUALITY_CHECKED
  ↓
COMPLETED  ──or──►  NEEDS_REVIEW
```

A failure goes to `FAILED`, which records the stage, the error and the
retry count. `resume` picks the job up from its recovery point; `retry`
runs the failed stage again.

Every stage checks the job's status before it advances it, so a stage that
runs out of order does not move the job backwards.

---

## The stages

### 1. `ingest` — read the movie

Probes the file with `ffprobe` and writes `media/media.json`: the duration,
the fps, the resolution, the codecs, the streams and the file's hash.

The hash is the film's identity. Everything downstream keys on it.

### 2. `scenes` — find the scenes

Detects the scene boundaries and writes `scenes/scenes.json`. The detector
is `adaptive` by default; the thresholds are in `config/default.yaml`.

### 3. `transcript` — hear the dialogue

Extracts the dialogue audio, transcribes it, and writes
`transcript/transcript.json`, plus `transcript.srt` and `transcript.vtt`.

### 4. `vision` — see the scenes

Samples frames from each scene, sends them to the vision model, and writes
`vision/vision.json`: the location, the characters, the actions, the
objects and the emotions of each scene.

The sampling is adaptive: a short scene gets three frames, a medium scene
six, a long scene twelve.

### 5. `characters` — name the people

Collects the characters from the visual analyses and the spoken names, and
writes the roster and the mentions.

### 6. `diarization` — who is speaking

Attributes each transcript line to a speaker. Turn it off with
`pipeline.diarization: false` if the speaker-to-character linking is not
needed.

### 7. `locations` — where it happens

Extracts the locations and writes `locations/locations.json`.

### 8. `events` — what changes

Extracts the story events: the moments where the story's state changes.
Writes `events/events.json`.

### 9. `arcs` — the shape of the story

Maps the events onto the classical structure — setup, confrontation,
resolution — and writes `story/story-arcs.json`.

### 10. `themes` — what it is about

Finds the themes the events express, and writes `story/themes.json`.

### 11. `twists` — what you did not see coming

Finds the twists and the events that foreshadowed them, and writes
`story/twists.json`.

### 12. `story` — assemble the knowledge base

Puts the events, the characters, the locations, the relationships, the
arcs, the themes and the twists into one document:
`movie-analysis.json`. This is the file everything downstream reads.

### 13. `review` — write the script

Plans the sections, then writes each one, and writes
`review/review-script.json`. Every paragraph carries the claims it makes
and the visual intent behind it.

### 14. `verify` — check the claims

Takes the script's claims and checks each one against the evidence. A
claim the evidence does not support is either removed or marked
`INSUFFICIENT_EVIDENCE`; the writer never invents a plot fact.

Writes `verify/script-verification.json`.

### 15. `review-translate` — speak another language

Translates the script if the target language is not the source language.
Skipped entirely when they are the same.

### 16. `tts-chunks` — plan and speak

Splits the script into chunks, synthesizes each one, and writes the WAVs
and `tts/narration.json`.

The chunk identity comes from the **text**, not from its position, so
editing one paragraph does not invalidate the audio of the others.

### 17. `tts-concat` — join the audio

Concatenates the chunks into `tts/narration.wav`.

### 18. `tts-reconcile` — match the narration to the plan

Adjusts the narration's timing so it fits the planned duration, and
rewrites the script's timings to match.

### 19. `render-manifest` — plan the edit

Chooses the source footage for each paragraph and writes
`render/render-manifest.json`: the exact source window, the timeline
position and the duration of every segment.

Two controls bound the source footage:

| Control | Default | What it bounds |
|---|---|---|
| `source_video.max_clip_seconds` | `8.0` | the longest single clip |
| `source_video.max_source_ratio` | `0.35` | the source as a share of the movie |
| `source_video.max_total_seconds` | `420.0` | the source in total |

**These are product controls, not legal guarantees.** No fixed clip
duration or percentage is automatically safe to publish.

### 20. `subtitles` — write the sidecar

Writes `render/review.srt`.

### 21. `render` — cut the video

Cuts the clips, mixes in the narration and the music, and writes
`render/review.mp4`.

### 22. `quality` — the gate

Measures the review against the gates and writes `qc/quality-report.json`.
The job ends `COMPLETED` or `NEEDS_REVIEW`.

The gates are:

| Gate | What it checks |
|---|---|
| evidence coverage | every claim has evidence |
| timeline consistency | the events are in the movie's timeline |
| character consistency | the characters are the ones the story has |
| duration accuracy | the narration is the length it was asked for |
| visual coherence | the footage matches the narration |

### 23. `export` — the output set

Writes the finished set to `paths.output_dir`: the video, the narration,
the script as Markdown, and the manifest.

---

## The pause before a model stage

Ten of the stages call a model. Before each one the pipeline asks the
operator to confirm, because a single machine cannot hold every model at
once: whisper, the vision model, the reasoner and the TTS model compete for
the same memory, and a run that swaps them has to stop long enough to load
the next one.

```bash
uv run movie-review process movie.mkv            # ask before each model stage
uv run movie-review process movie.mkv --auto-accept   # ask nothing
```

The block names what to load, not what the prompt says: the model, the
URL and the port are the three things the operator acts on.

```text
-- vision needs a model ----------------------------------------
   model: Qwen3-VL (openai_compatible)
   slot : vision
   url  : http://192.168.1.144:8000/v1
   port : 8000
   Continue? [Y/n]
```

The pipeline does not prompt; it takes a callback
(`run_pipeline(..., on_model_stage=...)`) and calls it with a `ModelCall`.
The CLI supplies the interactive one. A test, the dashboard or the desktop
app passes nothing, and the run never blocks on a prompt nobody can answer.

Declining raises `ModelStageDeclined` before the stage starts: no progress
line, no retry, no artifact, and the job stays where the previous stage
left it. `resume` then continues at exactly that stage.

Translation is skipped when the narration is in the source language, and
the critic is skipped when the profile does not enable it — there is no
model call, so there is no pause.

---

## Running part of it

```bash
# one stage
uv run movie-review process movie.mkv --from-stage events --to-stage story

# the older names work too
uv run movie-review process movie.mkv --stage-from events --stage-to story
```

Giving both names is a usage error rather than a silent preference, so you
always know which one was used.

## Redoing the work

```bash
uv run movie-review process movie.mkv --from-stage story --force
```

`--force` removes the recorded artifacts of the stages it re-runs. It does
not remove the job record and it does not touch the other stages.

The cache is content-addressed, so a stage whose inputs have not changed
still answers from the cache — which is the same answer, not a stale one.
A prompt change, a model change or a generation-config change is a
different cache key, and the work is genuinely redone.

## Keeping the intermediates

```bash
uv run movie-review process movie.mkv --keep-intermediates
```

Without it, the sampled frames are deleted when the job finishes. A
feature-length run leaves hundreds of megabytes of JPEG frames behind
otherwise. The frames' manifest is kept either way: it is the record of
what was sampled.

## Making a run reproducible

```bash
uv run movie-review process movie.mkv --deterministic
```

The seed, the temperature and the top-p are pinned for every model slot.
The sampling is part of the cache identity, so a pinned run and an ordinary
one do not share answers.

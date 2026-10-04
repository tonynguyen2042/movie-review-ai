# Specification — movie-review-ai

**Version:** 1.1

## 1. Product Goal

Convert a full-length movie into an approximately 20-minute YouTube-style movie review with:

- coherent narrative
- accurate plot facts
- character continuity
- evidence traceability
- synchronized narration
- selected movie footage
- subtitles
- final quality validation

Primary CLI:

```bash
movie-review process ./movie.mp4 \
  --language en \
  --duration 20m \
  --style youtube \
  --quality balanced
```

## 2. Functional Requirements

### FR-001 — Ingest

Validate:

- input existence
- readable media
- SHA-256
- duration
- resolution
- FPS
- codecs
- streams

### FR-002 — Scene Detection

Produce stable scene IDs and timestamps.

### FR-003 — Frame Sampling

Support keyframe and adaptive sampling.

### FR-004 — ASR

Produce timestamped dialogue.

Default target:

```text
Whisper large-v3-turbo
```

### FR-005 — Diarization

Associate speech segments with speakers where feasible.

### FR-006 — Visual Understanding

Use a VLM to extract:

- characters
- actions
- objects
- locations
- emotions
- scene importance
- uncertainty

Default family:

```text
Qwen3-VL
```

### FR-007 — Character Discovery

Discover major/minor characters.

### FR-008 — Character Linking

Link visual identities, speakers, names, dialogue, co-occurrence, and reasoning evidence.

### FR-009 — Event Extraction

Extract events such as:

- discovery
- conflict
- decision
- betrayal
- revelation
- death
- escape
- capture
- investigation
- climax
- resolution

### FR-010 — Evidence Registry

Evidence types:

```text
DIALOGUE
VISUAL
AUDIO
SCENE
EVENT
CHARACTER
TIMELINE
```

### FR-011 — Movie Knowledge Base

Canonical representation must contain, where available:

- metadata
- scenes
- transcript
- speakers
- characters
- locations
- events
- relationships
- evidence
- story arcs
- themes
- twists
- timeline

Canonical export:

```text
movie-analysis.json
```

### FR-012 — Story Graph

Support relationships including:

```text
PARTICIPATES_IN
DISCOVERS
KNOWS
SUSPECTS
BETRAYS
KILLS
CAUSES
PRECEDES
FORESHADOWS
REVEALS
```

### FR-013 — Review Planning

Generate a structured review plan before prose generation.

### FR-014 — Review Script

Default:

```text
20 minutes
150 WPM
≈ 3000 words
```

The duration controller must adjust the script to the configured target.

### FR-015 — Review Styles

Initial styles:

- youtube
- documentary
- funny
- serious

Style profile controls:

- tone
- humor
- suspense
- analysis depth
- plot detail
- pacing
- spoilers
- hook

### FR-016 — Claim Tracking

Classify claims as:

```text
PLOT_FACT
CHARACTER_FACT
TIMELINE_FACT
DIALOGUE_REFERENCE
INTERPRETATION
OPINION
THEME
```

### FR-017 — Fact Checking

Statuses:

```text
SUPPORTED
PARTIALLY_SUPPORTED
CONTRADICTED
INSUFFICIENT_EVIDENCE
```

Contradicted major claims must be repaired or removed.

### FR-018 — Continuity

Check:

- character state
- alive/dead state
- locations
- object ownership
- relationships
- chronology
- flashbacks
- flash-forwards

### FR-019 — TTS

Default target:

```text
Qwen3-TTS 1.7B
```

TTS must be chunked and retryable.

### FR-020 — Visual Planning

Preferred selection order:

```text
direct evidence
→ reaction
→ location/context
→ object
→ establishing shot
→ generic atmosphere
```

### FR-021 — Rendering

Default:

```text
1080p
30 FPS
H.264
AAC
```

Include:

- movie clips
- narration
- music
- subtitles
- transitions

### FR-022 — Subtitles

Subtitles must derive from actual narration timing.

### FR-023 — Quality Control

Validate:

- output integrity
- duration
- evidence coverage
- timeline
- characters
- claims
- TTS
- visual alignment

### FR-024 — Resume

Interrupted jobs must resume from the last valid artifact/stage.

### FR-025 — Caching

Equivalent inputs/configurations must reuse valid artifacts.

### FR-026 — Model Abstraction

Models must be accessed through adapters/ports.

### FR-027 — Privacy

Movie data remains local by default.

### FR-028 — CLI

Support:

```text
process
inspect
analyze
scenes
transcript
story
script
render
validate
resume
retry
benchmark
```

## 3. Non-Functional Requirements

### NFR-001 Reliability

Stages must be restartable and idempotent.

### NFR-002 Observability

Structured JSON logs must include:

- job_id
- stage
- event
- duration
- status
- error where applicable

### NFR-003 Reproducibility

Record:

- model
- runtime
- prompt version
- config
- input hash
- output hash

### NFR-004 Performance

Initial balanced-mode target:

```text
< 8 hours for a 2-hour 1080p movie
```

This is a target, not a correctness requirement.

### NFR-005 Memory

The target machine is Apple Silicon with 128 GB unified memory.

The pipeline must support sequential model residency and OOM recovery.

### NFR-006 Testability

Tests must run without downloading/loading large AI models.

## 4. Acceptance Criteria

1. Ingest CLI works.
2. Scene IDs are stable.
3. Transcript has timestamps.
4. Major characters are identified.
5. Major events are identified.
6. Evidence is attached to important claims.
7. Story outline is coherent.
8. Generated review reaches configured target duration.
9. Unsupported major claims are below 2% on the golden set.
10. Evidence coverage is at least 90%.
11. Timeline consistency is at least 95%.
12. Injected stage failure can be recovered.
13. Cache reuse works.
14. Final video passes integrity validation.
15. Every implementation task is isolated on a task branch.
16. Every meaningful task milestone has a Git commit.
17. A task cannot be marked `[x]` while tests fail.
18. Completed tasks automatically produce a PR targeting `master` when PR tooling is available.

## 5. Out of Scope

- automatic YouTube upload in core V1
- monetization
- copyright dispute automation
- mandatory cloud AI
- distributed inference
- AI movie generation/remakes
- UI before CLI stability
- mandatory vector DB

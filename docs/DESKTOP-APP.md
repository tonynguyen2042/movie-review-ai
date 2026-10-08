# Desktop App

An Electron GUI for the `movie-review` CLI (task T111).

The app is a front end, not a second implementation. It builds the same command
line you would type, spawns the CLI as a child process, and renders what the CLI
prints. Every pipeline decision — stage order, defaults, validation, failure
handling — stays in `movie_review`.

```
┌───────────────┐   ipcRenderer.invoke    ┌──────────────────┐   spawn    ┌────────────────┐
│   renderer    │ ──────────────────────► │  Electron main   │ ─────────► │ movie-review   │
│  (no Node)    │ ◄────────────────────── │ argv + tracking  │ ◄───────── │  (Python CLI)  │
└───────────────┘   run:entry/progress   └──────────────────┘  stdout/   └────────────────┘
                                                     │          stderr
                                                     ▼
                                            desktop_bridge.py
                                     (YAML + pydantic validation)
```

## Requirements

| Requirement | Why |
| --- | --- |
| Node.js 20+ | Only to build and run the app shell. |
| `uv` on `PATH` | The app runs the pipeline with `uv run movie-review`. |
| The repo checkout | `config/`, `data/` and `pyproject.toml` are read from it. |
| `ffmpeg` / `ffprobe` | Required by the pipeline itself, not by the app. |

On macOS the pipeline needs Apple Silicon for the MLX path, or a `remote` model
profile. The app itself is platform-agnostic.

## Running it

```bash
cd desktop
npm install     # once
npm start
```

The window title bar shows the repo root it is driving. If `uv` is missing, the
app still opens: browsing jobs and editing configuration keep working, and the
Run tab explains that starting a pipeline is unavailable.

### Without uv

Set the command that runs the CLI instead:

```bash
# macOS / Linux
MOVIE_REVIEW_DESKTOP_RUNNER="python -m movie_review.cli.app" npm start

# Windows PowerShell
$env:MOVIE_REVIEW_DESKTOP_RUNNER = "python -m movie_review.cli.app"
npm start
```

The bridge script is invoked with the same executable minus the CLI-specific
arguments, so this override works for both the pipeline and the config editor.

## The four tabs

### Run

Pick a command, fill in what it needs, press **Start**.

| Command | Needs | Notes |
| --- | --- | --- |
| `process` | a movie file | Every `process` option is exposed. |
| `resume` | a job id | Continues from the last checkpoint. |
| `retry` | a job id | Optionally one `--stage`. |
| `publish` | a job id | **Upload now** is off by default, which makes it a preview. |
| `validate` | a job id | Checks the job's recorded artifacts. |

The command preview under the form is the literal argv that will be spawned. It
is there so nothing is hidden: if the preview is wrong, the run is wrong.

An untouched field is not sent at all, so a form left alone produces exactly the
CLI's own defaults. That matters — sending `--duration 20m` forever would mean a
change to the CLI default could never take effect. Each field shows its CLI
default in the label.

`--profile` is a dropdown rather than a text box: the set of profiles is closed,
and a typo there fails when the job is created, minutes after you committed to a
run.

### Progress and log

* The **Progress** card lists all 19 stages. A green dot is a stage that
  succeeded, red is the stage that failed, pulsing blue is the stage running now.
* The thin bar is the current stage's `WorkProgress` fraction. Stages that cannot
  divide their work (transcription, rendering) show an empty bar and rely on the
  heartbeat lines instead.
* The **Log** shows both streams the CLI writes: the JSON records from
  `utils.logging`, and the human progress lines from `cli.app`. Anything else —
  an ffmpeg complaint the pipeline never wrapped — is passed through rather than
  dropped, because it is usually the reason a run failed.

**Stop** sends `SIGINT` first so the CLI closes its reporter and leaves the job
resumable, then takes down the whole process tree (the CLI's own `ffmpeg`
children included). A run you stopped is reported as *cancelled*, not *failed* —
a red failure indicator for a deliberate stop is how a user learns to ignore it.

Closing the window mid-run asks first, for the same reason.

> **Platform difference in how Stop is delivered.** On macOS and Linux the child
> gets `SIGINT`, so the CLI prints `Interrupted. Job state is preserved; use
> 'resume' to continue.` and exits 130. On Windows a spawned child has no
> console, so `SIGINT` cannot be delivered at all and the app falls back to
> `taskkill /T /F`: the process tree dies without printing that line. The job is
> resumable either way, because a hard kill leaves it at its last committed
> status rather than at `FAILED` — which is exactly the state `resume` and
> `retry` are built for.

### Jobs

Reads `jobs.db` directly through the bridge, so it lists what the pipeline
recorded: status, the stage that failed, and the error text. Clicking a row fills
the job id for the current command, which is how `resume`, `retry` and `publish`
get their argument.

**Open output folder** resolves `<data_dir>/jobs/<job_id>`, the same layout the
CLI uses.

### Models

Edits `config/models.yaml`: pick a profile, then edit any slot
(`asr`, `vision`, `reasoning`, `critic`, `translation`, `tts`) and any field
(`model`, `precision`, `backend`, `base_url`, `endpoint_path`, `api_key_env`,
`timeout_seconds`, `max_tokens`, `enabled`).

Blanking a field removes it from the file rather than writing an empty string, so
the `ModelSpec` defaults apply again.

### Settings

Edits `config/default.yaml`, rendering the nested structure as dotted paths
(`pipeline.review.target_wpm`). Values are parsed back to their YAML type — a
field holding `150` stays a number, one holding `true` stays a boolean.

## How a config save is kept safe

Saving from either editor does three things, in this order:

1. **Validates** the candidate through the project's own `AppSettings` and
   `ModelSpec` via `load_settings`. For `models.yaml` it additionally expands
   *every* profile the file declares, not only the active one — a broken `remote`
   profile should not wait days to be discovered.
2. **Backs up** the current file to `<name>.bak.<timestamp>` beside it.
3. **Writes** the file, and only then.

A value the pipeline cannot load is refused with the validator's own message and
nothing is written. A config file that fails to load breaks every later CLI
invocation, including the one you would use to repair it.

The candidate is validated from a scratch file **inside the real `config/`**
directory, because `load_settings` derives `models.yaml` from the directory of
`default.yaml`. Validating in a temp directory would check it against the wrong
models file — which is precisely the mistake worth preventing.

> Writing re-serialises the YAML, so **comments in `config/default.yaml` and
> `config/models.yaml` are not preserved**. The current files carry substantial
> commentary. Keep a copy outside the app if you want to keep it; the `.bak`
> file is the previous version with its comments intact.

## Packaging

```bash
cd desktop
npm run dist     # dmg (macOS, arm64 + x64) and nsis (Windows, x64)
npm run pack     # unpacked build, faster, for a smoke test
```

The Python side is deliberately **not** bundled. The app shells out to
`uv run movie-review` in a checkout, so a packaged build runs the pipeline the
user has configured rather than a frozen copy that drifts from `config/` and
`config/prompts/`. The cost is that a packaged app needs the repo and `uv`
present — the same requirement as running the CLI. Signing is left unset; an
unsigned build is the honest artefact for local use.

## Progress over a pipe

The CLI silences its stage lines when stderr is not a terminal
(`_progress_enabled()` → `sys.stderr.isatty()`). A spawned child always has a
pipe there, so the app would show nothing at all for hours.

The CLI therefore honours `MOVIE_REVIEW_PROGRESS`:

| Value | Effect |
| --- | --- |
| `1`, `true`, `yes`, `on` | Force progress on, terminal or not. |
| `0`, `false`, `no`, `off` | Force progress off, even in a terminal. |
| anything else, or unset | Keep the automatic tty test. |

The app sets it to `1`. You can set it yourself when running the CLI directly.

## Tests

```bash
cd desktop
npm test                              # 59 tests, no display needed
npx electron test/e2e-run.js          # drives a real pipeline run through the window
npx electron test/e2e-stop.js         # stops a real run mid-flight
npx electron test/screenshot.js       # writes screenshot-*.png for each tab
```

`npm test` covers the three pure modules (`argv.js`, `line-parser.js`,
`python-runner.js`), the Python bridge end to end through `uv`, and the parser
against line samples copied from `cli/app.py`.

`test/e2e-run.js` is the acceptance test that unit tests cannot replace: it
generates a six-second clip with ffmpeg, clicks **Start**, waits for the verdict,
and asserts that the stage lines arrived over the pipe and that both stages are
marked done. It is limited to `ingest` and `scenes` so it needs no model weights
and finishes in seconds.

`test/e2e-stop.js` generates a ten-minute clip so `scenes` is still working,
confirms the process really is in flight, clicks **Stop**, and asserts the child
is gone and the verdict reads *cancelled* rather than *failed*.

If a CLI output format changes, the parser tests fail on purpose. Update the
pattern in step with the CLI rather than loosening it until the test passes.

## Troubleshooting

**The window opens but Start does nothing.** Check for the `uv not found`
warning, or run `uv --version` in the same shell.

**The log fills with usage text.** The runner override is malformed. It must be
the executable followed by its arguments, e.g.
`MOVIE_REVIEW_DESKTOP_RUNNER="python -m movie_review.cli.app"`.

**A config save is refused.** Read the error: it is the pydantic message, naming
the field and the constraint. Nothing was written, and the previous file is
untouched.

**Progress bars sit at 0%.** Only stages that can divide their work report a
fraction — visual analysis and frame sampling. Transcription, TTS and rendering
report nothing of their own; the `... stage still running` heartbeat is the
liveness signal there.

## Copyright

The app makes no claim that any clip duration or percentage is automatically
legally safe. That determination depends on actual use and jurisdiction. Nothing
in this app contacts a network service unless you start a `remote` model profile
or confirm a `publish`.

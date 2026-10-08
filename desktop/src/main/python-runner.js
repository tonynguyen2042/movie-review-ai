'use strict';

/**
 * Spawn and supervise `movie-review` CLI processes.
 *
 * Every pipeline action the desktop app can take is a CLI invocation, so this is
 * the only place that knows how to start, watch and stop one. Two decisions are
 * worth stating up front:
 *
 *   - Progress is forced on with MOVIE_REVIEW_PROGRESS. The CLI silences its
 *     stage lines when stderr is not a terminal, and a spawned child always has
 *     a pipe there. Without the override the window would sit empty for hours.
 *
 *   - Stop kills the whole process tree, not just the child. The CLI spawns
 *     ffmpeg; killing only the parent would leave an encoder running, still
 *     holding the output file, after the UI has declared the run cancelled.
 */

const { spawn, spawnSync } = require('node:child_process');
const path = require('node:path');
const { EventEmitter } = require('node:events');

/** Repo root, three levels up from desktop/src/main. */
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const BRIDGE = path.join('desktop', 'scripts', 'desktop_bridge.py');

/**
 * Override for the command prefix, for a machine without uv.
 *
 * Format is the executable followed by any leading arguments, e.g.
 * `python -m movie_review.cli.app`. Kept as an env var rather than a setting
 * file so a broken environment can still be overridden without editing the repo.
 */
const RUNNER_ENV_VAR = 'MOVIE_REVIEW_DESKTOP_RUNNER';

const DEFAULT_RUNNER = { command: 'uv', prefix: ['run', 'movie-review'] };

function resolveRunner() {
  const override = process.env[RUNNER_ENV_VAR];
  if (override && override.trim()) {
    const parts = override.trim().split(/\s+/);
    return { command: parts[0], prefix: parts.slice(1) };
  }
  return DEFAULT_RUNNER;
}

/**
 * The prefix that runs a plain Python script rather than the CLI.
 *
 * `uv run movie-review python script.py` is not a thing -- `movie-review` is a
 * Typer app with no `python` subcommand -- so the bridge needs `uv run python`.
 * The leading arguments before the CLI itself are what both invocations share
 * (`run` for uv, nothing for a bare `python -m movie_review.cli.app` override),
 * so they are taken as-is and the CLI-specific tail is dropped.
 */
function resolvePythonPrefix() {
  const runner = resolveRunner();
  const shared = [];
  for (const part of runner.prefix) {
    if (part.startsWith('-') || part === 'movie-review') break;
    shared.push(part);
  }
  return { command: runner.command, prefix: shared };
}

/** True when `uv` is on PATH. Reported to the user rather than crashing the app. */
function runnerAvailable() {
  const { command } = resolveRunner();
  if (command !== 'uv') return true;
  const probe = spawnSync(command, ['--version'], { stdio: 'ignore', shell: false });
  return !probe.error && probe.status === 0;
}

function baseEnv() {
  return {
    ...process.env,
    MOVIE_REVIEW_PROGRESS: '1',
    PYTHONUNBUFFERED: '1',
    // Colour codes would end up verbatim in the log pane; the UI has its own
    // styling and escape sequences only corrupt it.
    NO_COLOR: '1',
    FORCE_COLOR: '0',
  };
}

function splitLines(emit) {
  return (chunk) => {
    const text = chunk.toString('utf8');
    for (const line of text.split(/\r?\n/)) emit(line);
  };
}

/**
 * A single supervised CLI invocation.
 *
 * Emits: `line` (raw text), `error` (spawn failure), `exit` ({code, signal}).
 */
class PipelineProcess extends EventEmitter {
  constructor({ argv, command = 'process', cwd = REPO_ROOT, env = baseEnv() }) {
    super();
    this.argv = argv;
    this.command = command;
    this.cwd = cwd;
    this.env = env;
    this.child = null;
    this.stopping = false;
  }

  get pid() {
    return this.child ? this.child.pid : null;
  }

  start() {
    const runner = resolveRunner();
    const args = [...runner.prefix, this.command, ...this.argv];
    this.displayArgs = [runner.command, ...args];

    this.child = spawn(runner.command, args, {
      cwd: this.cwd,
      env: this.env,
      // A process group of its own, so stop() can take the ffmpeg children with
      // it. On Windows this is ignored and taskkill does the job instead.
      detached: process.platform !== 'win32',
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    this.child.stdout.setEncoding('utf8');
    this.child.stderr.setEncoding('utf8');
    this.child.stdout.on('data', splitLines((line) => this.emit('line', line, 'stdout')));
    this.child.stderr.on('data', splitLines((line) => this.emit('line', line, 'stderr')));

    this.child.on('error', (error) => this.emit('error', error));
    this.child.on('close', (code, signal) => {
      this.emit('exit', { code, signal, stopping: this.stopping });
    });
    return this;
  }

  /**
   * Ask the CLI to stop, then the whole process group.
   *
   * SIGINT first because the CLI handles KeyboardInterrupt: it closes the
   * progress reporter and leaves the job resumable. The hard kill after a grace
   * period is the fallback for a stage wedged in a C extension that never
   * returns to the interpreter.
   */
  stop(graceMs = 5000) {
    if (!this.child || this.stopping) return false;
    this.stopping = true;
    const child = this.child;

    try {
      child.kill('SIGINT');
    } catch {
      // Already gone; the close handler will still fire.
    }

    if (process.platform === 'win32') {
      // No SIGINT delivery on Windows; taskkill /T reaches the ffmpeg children.
      spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
    } else {
      try {
        process.kill(-child.pid, 'SIGTERM');
      } catch {
        try {
          process.kill(-child.pid, 'SIGKILL');
        } catch {
          // Group already gone.
        }
      }
    }

    setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) {
        try {
          child.kill('SIGKILL');
        } catch {
          // Nothing left to kill.
        }
      }
    }, graceMs).unref();

    return true;
  }
}

/**
 * Run a bridge subcommand and resolve with its parsed JSON.
 *
 * The bridge always answers with JSON, so a rejection is a resolved value with
 * `ok: false` rather than a thrown error -- the UI has to show the message, and
 * an exception would lose it.
 */
function runBridge(args, options = {}) {
  const runner = resolvePythonPrefix();
  const full = [...runner.prefix, BRIDGE, ...args];
  return new Promise((resolve) => {
    const child = spawn(runner.command, full, {
      cwd: options.cwd || REPO_ROOT,
      env: baseEnv(),
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    child.stdout.setEncoding('utf8');
    child.stderr.setEncoding('utf8');
    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });
    child.on('error', (error) => resolve({ ok: false, errors: [error.message] }));
    child.on('close', (code) => {
      let payload;
      try {
        payload = JSON.parse(stdout.trim());
      } catch {
        resolve({
          ok: false,
          errors: [
            `Bridge exited ${code} without JSON.`,
            stderr.trim() || stdout.trim() || '(no output)',
          ],
        });
        return;
      }
      if (code !== 0 && payload.ok !== false) {
        payload.ok = false;
        payload.errors = [...(payload.errors || []), `exit ${code}`];
      }
      resolve(payload);
    });
  });
}

module.exports = {
  PipelineProcess,
  runBridge,
  runnerAvailable,
  resolveRunner,
  resolvePythonPrefix,
  baseEnv,
  REPO_ROOT,
  RUNNER_ENV_VAR,
};

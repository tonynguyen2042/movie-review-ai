'use strict';

/**
 * How the desktop app builds the command line it spawns.
 *
 * The bridge tests cover the far side of these invocations. These cover the
 * construction, because the failure they guard against is silent: a wrong prefix
 * makes the CLI print usage text and exit 2, which reaches the window as a
 * refused request rather than as a crash.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const {
  resolveRunner,
  resolvePythonPrefix,
  runnerAvailable,
  REPO_ROOT,
  RUNNER_ENV_VAR,
} = require('../src/main/python-runner');

/** Run `fn` with a temporary value for the runner override. */
function withRunner(value, fn) {
  const previous = process.env[RUNNER_ENV_VAR];
  if (value === undefined) delete process.env[RUNNER_ENV_VAR];
  else process.env[RUNNER_ENV_VAR] = value;
  try {
    return fn();
  } finally {
    if (previous === undefined) delete process.env[RUNNER_ENV_VAR];
    else process.env[RUNNER_ENV_VAR] = previous;
  }
}

test('the repo root resolves to the checkout, not the desktop folder', () => {
  // config/ and data/ are looked up relative to this, so an off-by-one here
  // would validate a different config than the CLI runs with. Checking for the
  // files that actually matter beats comparing directory names, which pass by
  // coincidence on some machines and fail on others.
  const fs = require('node:fs');
  assert.notEqual(path.basename(REPO_ROOT), 'desktop');
  assert.ok(fs.existsSync(path.join(REPO_ROOT, 'pyproject.toml')), 'pyproject.toml must be found');
  assert.ok(
    fs.existsSync(path.join(REPO_ROOT, 'config', 'config.yaml')),
    'config/config.yaml must be found',
  );
});

test('the default runner is uv running the installed CLI', () => {
  withRunner(undefined, () => {
    assert.deepEqual(resolveRunner(), { command: 'uv', prefix: ['run', 'movie-review'] });
  });
});

test('the bridge runs as a plain script, never as a CLI subcommand', () => {
  withRunner(undefined, () => {
    const runner = resolvePythonPrefix();
    // `uv run movie-review <script>` is a usage error: Typer would report
    // "No such command 'desktop_bridge.py'".
    assert.deepEqual(runner, { command: 'uv', prefix: ['run'] });
    assert.ok(!runner.prefix.includes('movie-review'));
  });
});

test('a runner override is honoured for the CLI', () => {
  withRunner('python -m movie_review.cli.app', () => {
    assert.deepEqual(resolveRunner(), {
      command: 'python',
      prefix: ['-m', 'movie_review.cli.app'],
    });
  });
});

test('a runner override still yields a usable script prefix', () => {
  withRunner('python -m movie_review.cli.app', () => {
    // The `-m module` tail belongs to the CLI only; the bridge is a file path.
    assert.deepEqual(resolvePythonPrefix(), { command: 'python', prefix: [] });
  });
});

test('a bare executable override needs no prefix at all', () => {
  withRunner('python3', () => {
    assert.deepEqual(resolvePythonPrefix(), { command: 'python3', prefix: [] });
  });
});

test('an empty override falls back to the default', () => {
  withRunner('   ', () => {
    assert.deepEqual(resolveRunner(), { command: 'uv', prefix: ['run', 'movie-review'] });
  });
});

test('uv is detected on this machine, which is what the app requires', () => {
  // Not a claim that uv exists everywhere: it states that this checkout can run
  // the desktop app, and fails loudly on a machine that cannot.
  assert.equal(runnerAvailable(), true);
});

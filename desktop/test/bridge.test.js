'use strict';

/**
 * Smoke test for the Python bridge, as the desktop app actually invokes it.
 *
 * `npm test` covers the pure modules; this one proves the wiring. It spawns the
 * bridge exactly the way `python-runner.js` does, through `uv run`, and fails
 * loudly on any non-zero exit or unparseable output. A green unit suite with a
 * broken spawn path is the failure mode worth spending one slow test on.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const BRIDGE = path.join('desktop', 'scripts', 'desktop_bridge.py');

/** Run the bridge the way the app does. Skips rather than fails without uv. */
function runBridge(args, { timeoutMs = 180000 } = {}) {
  const { spawnSync } = require('node:child_process');
  const probe = spawnSync('uv', ['--version'], { encoding: 'utf8', shell: false });
  if (probe.error || probe.status !== 0) return { skipped: true };

  const result = spawnSync('uv', ['run', 'python', BRIDGE, ...args], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    timeout: timeoutMs,
    shell: false,
    env: { ...process.env, NO_COLOR: '1' },
  });
  return {
    skipped: false,
    status: result.status,
    stdout: result.stdout || '',
    stderr: result.stderr || '',
  };
}

function parsed(run) {
  try {
    return JSON.parse(run.stdout.trim());
  } catch (error) {
    assert.fail(`bridge printed no JSON: ${error.message}\n${run.stderr || run.stdout}`);
  }
}

test('stages returns the full pipeline sequence', { timeout: 240000 }, () => {
  const run = runBridge(['stages']);
  if (run.skipped) return;

  assert.equal(run.status, 0, run.stderr);
  const payload = parsed(run);
  assert.equal(payload.ok, true);
  // The ends are pinned; the count is not. The exact sequence is pinned by
  // tests/unit/test_desktop_bridge.py, next to the code that defines it, so
  // a new stage does not break a test in another language.
  assert.ok(payload.stages.length >= 19, `too few stages: ${payload.stages.length}`);
  assert.equal(payload.stages[0][0], 'ingest');
  assert.equal(payload.stages.at(-1)[0], 'quality');
});

test('settings:read returns the config file and the profile catalog', { timeout: 240000 }, () => {
  const run = runBridge(['settings:read']);
  if (run.skipped) return;

  assert.equal(run.status, 0, run.stderr);
  const payload = parsed(run);
  assert.equal(payload.ok, true);
  assert.ok(Array.isArray(payload.profiles) && payload.profiles.length > 0);
  assert.ok(payload.paths.config.endsWith('config.yaml'));
  assert.ok(payload.config);
  // The catalog the app renders comes from the same document it edits.
  assert.ok(payload.config.profiles);
});

test('jobs:list returns rows, or an empty list on a fresh database', { timeout: 240000 }, () => {
  const run = runBridge(['jobs:list', '--limit', '5']);
  if (run.skipped) return;

  assert.equal(run.status, 0, run.stderr);
  const payload = parsed(run);
  assert.equal(payload.ok, true);
  assert.ok(Array.isArray(payload.jobs));
});

test('a rejected write exits 2 with an explanation and no stack trace', { timeout: 240000 }, () => {
  const run = runBridge([
    'settings:write',
    '--payload',
    JSON.stringify({}),
  ]);
  if (run.skipped) return;

  assert.equal(run.status, 2);
  const payload = parsed(run);
  assert.equal(payload.ok, false);
  assert.ok(payload.errors.length > 0);
  assert.ok(!run.stdout.includes('Traceback'), 'the GUI must not receive a traceback');
});

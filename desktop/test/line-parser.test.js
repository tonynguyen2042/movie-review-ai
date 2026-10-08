'use strict';

/**
 * The parser's job is to understand the CLI's real output, not a prettified
 * version of it.
 *
 * The line samples below are copied from `cli/app.py` and
 * `utils/logging.py`. If one of these tests fails after a CLI change, the fix is
 * to update the pattern in step with the CLI -- not to loosen the pattern until
 * the test passes, which would hide the format change instead of following it.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { parseLine, ProgressTracker, elapsedToSeconds, percentFromBar } = require('../src/main/line-parser');

const STAGES = [
  ['ingest', 'Ingest movie metadata'],
  ['scenes', 'Detect scenes'],
  ['transcript', 'Transcribe dialogue'],
  ['vision', 'Visual scene analysis'],
];

/* ------------------------------------------------------------ JSON log lines */

test('a JSON log line becomes a structured entry', () => {
  const entry = parseLine(
    JSON.stringify({
      timestamp: '2026-10-08T01:02:03+00:00',
      level: 'INFO',
      logger: 'movie_review.pipeline',
      message: 'stage.completed',
      event: 'stage.completed',
      status: 'ok',
      stage: 'scenes',
      job_id: 'job_1',
      duration_ms: 1234,
    }),
  );

  assert.equal(entry.kind, 'log');
  assert.equal(entry.level, 'INFO');
  assert.equal(entry.event, 'stage.completed');
  assert.equal(entry.stage, 'scenes');
  assert.equal(entry.jobId, 'job_1');
  assert.equal(entry.durationMs, 1234);
});

test('a JSON line with a traceback keeps the error text', () => {
  const entry = parseLine(
    JSON.stringify({ level: 'ERROR', message: 'boom', error: 'Traceback (most recent call last):' }),
  );

  assert.equal(entry.kind, 'log');
  assert.match(entry.error, /Traceback/);
});

test('a failed stage event survives with its error', () => {
  const entry = parseLine(
    JSON.stringify({
      level: 'ERROR',
      message: 'stage.failed',
      event: 'stage.failed',
      status: 'error',
      stage: 'vision',
      error: 'HTTP 500 from the reasoning server',
    }),
  );

  assert.equal(entry.event, 'stage.failed');
  assert.equal(entry.error, 'HTTP 500 from the reasoning server');
});

test('a JSON array is text, not a log record', () => {
  assert.equal(parseLine('[1, 2, 3]').kind, 'text');
});

test('malformed JSON is text rather than a crash', () => {
  assert.equal(parseLine('{"broken": ').kind, 'text');
});

/* ------------------------------------------------------------- stage lines */

test('a stage start reports the stage and its position', () => {
  const entry = parseLine('  -> vision (stage 4/19) ...');

  assert.equal(entry.kind, 'stage-start');
  assert.equal(entry.stage, 'vision');
  assert.equal(entry.index, 4);
  assert.equal(entry.total, 19);
});

test('a stage verdict reports success and elapsed time', () => {
  const entry = parseLine('  scenes: OK (1m03s, stage 2/19)');

  assert.equal(entry.kind, 'stage-end');
  assert.equal(entry.stage, 'scenes');
  assert.equal(entry.ok, true);
  assert.equal(entry.verdict, 'OK');
  assert.equal(entry.elapsedSeconds, 63);
});

test('a failed stage verdict is not reported as success', () => {
  const entry = parseLine('  vision: FAILED (2m11s, stage 4/19)');

  assert.equal(entry.ok, false);
  assert.equal(entry.elapsedSeconds, 131);
});

test('an in-stage bar reports percent, label and elapsed time', () => {
  const entry = parseLine('  vision [########--------]  33%  scene 12/48 (1m03s)');

  assert.equal(entry.kind, 'work');
  assert.equal(entry.stage, 'vision');
  assert.equal(entry.percent, 33);
  assert.equal(entry.label, 'scene 12/48');
  assert.equal(entry.elapsedSeconds, 63);
});

test('the printed number and the bar are reported separately because they disagree', () => {
  // `_format_bar` rounds the fraction independently of `WorkProgress.percent`, so
  // the real output does pair a 33% number with a 40%-wide bar. The UI shows the
  // number; a test that demanded they match would fail on real runs.
  const entry = parseLine('  vision [########--------]  33%  scene 12/48 (1m03s)');

  assert.equal(entry.percent, 33);
  assert.equal(entry.barPercent, 50);
});

test('a bar with no label still parses', () => {
  const entry = parseLine('  render [##########----------]  50% (12s)');

  assert.equal(entry.kind, 'work');
  assert.equal(entry.percent, 50);
  assert.equal(entry.label, '');
});

test('a liveness heartbeat is recognised so silence is visibly temporary', () => {
  const entry = parseLine('    ... transcript still running (3m05s)');

  assert.equal(entry.kind, 'heartbeat');
  assert.equal(entry.stage, 'transcript');
  assert.equal(entry.elapsedSeconds, 185);
});

test('an indented error line is lifted out of the log', () => {
  const entry = parseLine('    error: scene_000138: HTTP 500 from the server');

  assert.equal(entry.kind, 'error');
  assert.match(entry.message, /HTTP 500/);
});

test('the job acceptance line yields the job id and status', () => {
  const entry = parseLine('job_id=job_20261008_001 status=CREATED');

  assert.equal(entry.kind, 'job');
  assert.equal(entry.jobId, 'job_20261008_001');
  assert.equal(entry.status, 'CREATED');
});

test('the retry banner names the stage being retried', () => {
  assert.equal(parseLine('Retrying stage: vision').kind, 'retrying');
});

test('unrecognised output is passed through, never dropped', () => {
  const entry = parseLine("ffmpeg: [mov,mp4] moov atom not found");

  assert.equal(entry.kind, 'text');
  assert.match(entry.text, /moov atom/);
});

test('a blank line is distinguished from real text', () => {
  assert.equal(parseLine('   ').kind, 'blank');
});

test('a carriage return from a Windows pipe is stripped', () => {
  const entry = parseLine('  scenes: OK (1m03s, stage 2/19)\r');

  assert.equal(entry.kind, 'stage-end');
});

/* ------------------------------------------------------------------ helpers */

test('elapsed parsing handles seconds and minutes', () => {
  assert.equal(elapsedToSeconds('9s'), 9);
  assert.equal(elapsedToSeconds('3m05s'), 185);
  assert.equal(elapsedToSeconds('nonsense'), null);
  assert.equal(elapsedToSeconds(''), null);
});

test('bar percentage survives an empty bar', () => {
  assert.equal(percentFromBar(''), null);
  assert.equal(percentFromBar('####'), 100);
  assert.equal(percentFromBar('----'), 0);
});

/* ------------------------------------------------------------------ tracker */

test('the tracker follows a whole run from start to finish', () => {
  const tracker = new ProgressTracker(STAGES);
  [
    '  -> ingest (stage 1/4) ...',
    '  ingest: OK (2s, stage 1/4)',
    '  -> scenes (stage 2/4) ...',
    '  scenes [########--]  50%  clip 3/10 (5s)',
  ].forEach((line) => tracker.apply(parseLine(line)));

  const snapshot = tracker.snapshot();
  assert.equal(snapshot.current, 'scenes');
  assert.equal(snapshot.percent, 50);
  assert.deepEqual(snapshot.completed, ['ingest']);
  assert.equal(snapshot.stages[0].state, 'done');
  assert.equal(snapshot.stages[1].state, 'running');
  assert.equal(snapshot.stages[2].state, 'pending');
});

test('the overall fraction advances as stages complete', () => {
  const tracker = new ProgressTracker(STAGES);
  const start = tracker.overallFraction;

  tracker.apply(parseLine('  -> ingest (stage 1/4) ...'));
  tracker.apply(parseLine('  ingest: OK (2s, stage 1/4)'));

  assert.ok(start < tracker.overallFraction);
});

test('a finished stage marks its bar complete', () => {
  const tracker = new ProgressTracker(STAGES);
  tracker.apply(parseLine('  -> vision (stage 4/4) ...'));
  tracker.apply(parseLine('  vision: OK (9m, stage 4/4)'));

  const snapshot = tracker.snapshot();
  assert.equal(snapshot.percent, 100);
  assert.equal(snapshot.current, null);
  // Only vision of the four stages is done; a resume run starts part-way, so a
  // completion is per-stage rather than "the whole sequence ran".
  assert.equal(snapshot.overallFraction, 0.25);
});

test('a failure records the stage and never reaches completion', () => {
  const tracker = new ProgressTracker(STAGES);
  tracker.apply(parseLine('  -> vision (stage 4/4) ...'));
  tracker.apply(parseLine('  vision: FAILED (2m11s, stage 4/4)'));

  const snapshot = tracker.snapshot();
  assert.equal(snapshot.failed.stage, 'vision');
  assert.equal(snapshot.stages[3].state, 'failed');
  assert.ok(snapshot.overallFraction < 1);
});

test('work reported for a stage that already ended does not move the bar', () => {
  const tracker = new ProgressTracker(STAGES);
  tracker.apply(parseLine('  -> ingest (stage 1/4) ...'));
  tracker.apply(parseLine('  ingest: OK (2s, stage 1/4)'));
  // The last bar of a stage often arrives just before its verdict.
  tracker.apply(parseLine('  ingest [###-]  40%  (2s)'));

  assert.equal(tracker.snapshot().percent, 100);
});

test('a heartbeat leaves the progress untouched', () => {
  const tracker = new ProgressTracker(STAGES);
  tracker.apply(parseLine('  -> transcript (stage 3/4) ...'));
  tracker.apply(parseLine('    ... transcript still running (1m05s)'));

  const snapshot = tracker.snapshot();
  assert.equal(snapshot.current, 'transcript');
  assert.equal(snapshot.percent, 0);
});

test('reset clears everything for the next run', () => {
  const tracker = new ProgressTracker(STAGES);
  tracker.apply(parseLine('  -> ingest (stage 1/4) ...'));
  tracker.apply(parseLine('  ingest: OK (2s, stage 1/4)'));

  tracker.reset();

  const snapshot = tracker.snapshot();
  assert.deepEqual(snapshot.completed, []);
  assert.equal(snapshot.current, null);
  assert.equal(snapshot.overallFraction, 0);
});

test('a tracker with no stages does not divide by zero', () => {
  const tracker = new ProgressTracker([]);

  assert.equal(tracker.overallFraction, 0);
  assert.deepEqual(tracker.snapshot().stages, []);
});

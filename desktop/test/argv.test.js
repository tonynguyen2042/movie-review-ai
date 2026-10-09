'use strict';

/**
 * The argv the desktop app builds must be the argv a user would have typed.
 *
 * Each test pins one decision: which flags exist, when they are emitted, and --
 * for `--confirm` -- when they deliberately are not.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { buildArgv, previewCommand, describeCommand, COMMAND_FIELDS } = require('../src/main/argv');

test('process puts the movie first, as a positional argument', () => {
  const { argv, problems } = buildArgv('process', {}, { movie: '/movies/a.mkv' });

  assert.deepEqual(problems, []);
  assert.equal(argv[0], '/movies/a.mkv');
});

test('process refuses to build without a movie', () => {
  const { argv, problems } = buildArgv('process', {}, { movie: '   ' });

  assert.deepEqual(argv, []);
  assert.match(problems[0], /movie file/i);
});

test('an untouched form emits only the positional, so CLI defaults stay in force', () => {
  const { argv } = buildArgv('process', {}, { movie: 'a.mkv' });

  assert.deepEqual(argv, ['a.mkv']);
});

test('every process option maps to its CLI flag', () => {
  const values = {
    language: 'ja',
    targetLanguage: 'en',
    duration: '8m',
    style: 'documentary',
    profile: 'quality',
    spoilers: 'light',
    output: './out',
    dbPath: './data/jobs.db',
    stageFrom: 'vision',
    stageTo: 'render',
  };

  const { argv } = buildArgv('process', values, { movie: 'a.mkv' });

  assert.deepEqual(argv, [
    'a.mkv',
    '--language', 'ja',
    '--target-language', 'en',
    '--duration', '8m',
    '--style', 'documentary',
    '--profile', 'quality',
    '--spoilers', 'light',
    '--output', './out',
    '--db-path', './data/jobs.db',
    '--stage-from', 'vision',
    '--stage-to', 'render',
  ]);
});

test('blank optional fields are dropped rather than sent as empty strings', () => {
  const { argv } = buildArgv(
    'process',
    { language: '  ', duration: '8m', stageTo: null },
    { movie: 'a.mkv' },
  );

  assert.deepEqual(argv, ['a.mkv', '--duration', '8m']);
});

test('values are trimmed, because a pasted path usually carries whitespace', () => {
  const { argv } = buildArgv('process', { output: '  ./out  ' }, { movie: ' a.mkv ' });

  assert.deepEqual(argv, ['a.mkv', '--output', './out']);
});

test('a movie path with spaces stays one argument', () => {
  const { argv } = buildArgv('process', {}, { movie: 'C:\\My Movies\\a b.mkv' });

  assert.equal(argv.length, 1);
  assert.equal(argv[0], 'C:\\My Movies\\a b.mkv');
});

test('--no-run is emitted only when switched on', () => {
  assert.deepEqual(buildArgv('process', { noRun: false }, { movie: 'a.mkv' }).argv, ['a.mkv']);
  assert.deepEqual(buildArgv('process', { noRun: true }, { movie: 'a.mkv' }).argv, [
    'a.mkv',
    '--no-run',
  ]);
});

test('resume and retry put the job id before their flags', () => {
  const resume = buildArgv('resume', { language: 'en' }, { jobId: 'job_1' });
  const retry = buildArgv('retry', { stage: 'vision' }, { jobId: 'job_1' });

  assert.deepEqual(resume.argv, ['job_1', '--language', 'en']);
  assert.deepEqual(retry.argv, ['job_1', '--stage', 'vision']);
});

test('a job command without a job id reports a problem instead of building', () => {
  const { argv, problems } = buildArgv('resume', {}, {});

  assert.deepEqual(argv, []);
  assert.match(problems[0], /job/i);
});

test('publish omits --confirm by default so a preview cannot become an upload', () => {
  const { argv } = buildArgv(
    'publish',
    { platform: 'youtube', publishNow: false },
    { jobId: 'job_1' },
  );

  assert.ok(!argv.includes('--confirm'));
});

test('publish sends --confirm only when the checkbox is on', () => {
  const { argv } = buildArgv('publish', { publishNow: true }, { jobId: 'job_1' });

  assert.ok(argv.includes('--confirm'));
});

test('validate carries only the job id and db path', () => {
  const { argv } = buildArgv('validate', { dbPath: 'x.db', language: 'en' }, { jobId: 'job_1' });

  assert.deepEqual(argv, ['job_1', '--db-path', 'x.db']);
});

test('an unknown command is refused rather than guessed at', () => {
  const { argv, problems } = buildArgv('teleport', {});

  assert.deepEqual(argv, []);
  assert.match(problems[0], /Unknown command/);
});

test('preview renders the literal command line', () => {
  const preview = previewCommand('process', { duration: '8m' }, { movie: 'a.mkv' });

  assert.equal(preview, 'movie-review process a.mkv --duration 8m');
});

test('preview is null when the command cannot be built', () => {
  assert.equal(previewCommand('process', {}, {}), null);
});

test('describeCommand reports each option with its CLI default', () => {
  const spec = describeCommand('process');
  const duration = spec.fields.find((f) => f.key === 'duration');

  assert.equal(duration.flag, '--duration');
  assert.equal(duration.cliDefault, '20m');
  assert.equal(spec.fields.find((f) => f.key === 'profile').cliDefault, null);
  assert.equal(spec.switches[0].flag, '--no-run');
});

test('describeCommand returns null for a command it does not know', () => {
  assert.equal(describeCommand('teleport'), null);
});

test('every declared field has a --flag, so the form cannot drift from the CLI', () => {
  for (const [command, spec] of Object.entries(COMMAND_FIELDS)) {
    for (const field of spec.fields) {
      assert.match(field.flag, /^--[a-z-]+$/, `${command}.${field.key}`);
    }
    for (const sw of spec.switches) {
      assert.match(sw.flag, /^--[a-z-]+$/, `${command}.${sw.key}`);
    }
  }
});

'use strict';

/**
 * Build the argv for a `movie-review` invocation from the desktop form.
 *
 * The app never re-implements the CLI: it builds the argument list a user would
 * have typed, so every option, default and validation rule stays owned by
 * `movie_review.cli.app`. This module is the single place that decides which
 * form fields become flags, which is why it is a pure function with no Electron
 * or filesystem dependency -- it is directly unit-testable.
 *
 * A flag is emitted only when the user actually changed it, so an untouched form
 * produces exactly the command line the CLI's own defaults would produce. That
 * matters beyond tidiness: passing `--duration 20m` explicitly is fine, but
 * passing every field forever means a new CLI default can never take effect.
 */

/** Options of `movie-review process`, with the CLI defaults for reference. */
const PROCESS_FIELDS = [
  { key: 'language', flag: '--language', type: 'string', cliDefault: 'en' },
  { key: 'targetLanguage', flag: '--target-language', type: 'string' },
  { key: 'duration', flag: '--duration', type: 'string', cliDefault: '20m' },
  { key: 'style', flag: '--style', type: 'string', cliDefault: 'youtube' },
  { key: 'profile', flag: '--profile', type: 'string' },
  { key: 'spoilers', flag: '--spoilers', type: 'string', cliDefault: 'full' },
  { key: 'output', flag: '--output', type: 'string', cliDefault: './output' },
  { key: 'dbPath', flag: '--db-path', type: 'string' },
  { key: 'stageFrom', flag: '--stage-from', type: 'string' },
  { key: 'stageTo', flag: '--stage-to', type: 'string' },
];

/** Boolean switches of `process`, all defaulting to off. */
const PROCESS_SWITCHES = [{ key: 'noRun', flag: '--no-run' }];

const RESUME_FIELDS = [
  { key: 'language', flag: '--language', type: 'string', cliDefault: 'en' },
  { key: 'targetLanguage', flag: '--target-language', type: 'string' },
  { key: 'profile', flag: '--profile', type: 'string' },
  { key: 'dbPath', flag: '--db-path', type: 'string' },
];

const RETRY_FIELDS = [
  ...RESUME_FIELDS,
  { key: 'stage', flag: '--stage', type: 'string' },
];

const PUBLISH_FIELDS = [
  { key: 'platform', flag: '--platform', type: 'string', cliDefault: 'youtube' },
  { key: 'profile', flag: '--profile', type: 'string' },
  { key: 'dbPath', flag: '--db-path', type: 'string' },
  { key: 'language', flag: '--language', type: 'string', cliDefault: 'en' },
  { key: 'privacy', flag: '--privacy', type: 'string', cliDefault: 'unlisted' },
  { key: 'title', flag: '--title', type: 'string' },
  { key: 'description', flag: '--description', type: 'string' },
];

const VALIDATE_FIELDS = [{ key: 'dbPath', flag: '--db-path', type: 'string' }];

/** Field layout per supported command, used to render the form. */
const COMMAND_FIELDS = {
  process: { fields: PROCESS_FIELDS, switches: PROCESS_SWITCHES },
  resume: { fields: RESUME_FIELDS, switches: [] },
  retry: { fields: RETRY_FIELDS, switches: [] },
  publish: { fields: PUBLISH_FIELDS, switches: [{ key: 'confirm', flag: '--confirm' }] },
  validate: { fields: VALIDATE_FIELDS, switches: [] },
};

/** Commands that need a job id before their flags. */
const JOB_COMMANDS = new Set(['resume', 'retry', 'publish', 'validate', 'inspect']);

function isBlank(value) {
  return value === undefined || value === null || String(value).trim() === '';
}

function asBool(value) {
  return value === true || value === 'true' || value === 1 || value === '1';
}

function pushField(argv, field, values) {
  const value = values[field.key];
  if (isBlank(value)) return;
  argv.push(field.flag, String(value).trim());
}

/**
 * Build argv for a command.
 *
 * @param {string} command one of process/resume/retry/publish
 * @param {object} values form field values
 * @param {object} [options]
 * @param {string} [options.movie] the movie path, required by `process`
 * @param {string} [options.jobId] the job id, required by the job commands
 * @returns {{argv: string[], problems: string[]}} argv plus anything that blocks it
 */
function buildArgv(command, values = {}, options = {}) {
  const spec = COMMAND_FIELDS[command];
  if (!spec) {
    return { argv: [], problems: [`Unknown command "${command}".`] };
  }

  const argv = [];
  const problems = [];
  const form = values || {};

  if (command === 'process') {
    if (isBlank(options.movie)) {
      problems.push('Choose a movie file first.');
    } else {
      // Trimmed like every other value: the file dialog and a drag-and-drop both
      // hand back a clean path, but a pasted one often carries whitespace, and
      // ffmpeg reports a missing file rather than a padded path.
      argv.push(String(options.movie).trim());
    }
  }

  if (JOB_COMMANDS.has(command)) {
    if (isBlank(options.jobId)) {
      problems.push('Choose a job first.');
    } else {
      argv.push(String(options.jobId).trim());
    }
  }

  for (const field of spec.fields) {
    pushField(argv, field, form);
  }
  for (const sw of spec.switches) {
    if (asBool(form[sw.key])) argv.push(sw.flag);
  }

  // --confirm is the one flag whose absence is the safe default: without it the
  // CLI only previews. Emitting it from a checkbox that is on by default would
  // publish a video the user never saw.
  if (command === 'publish' && asBool(form.publishNow) === true) {
    argv.push('--confirm');
  }

  return { argv, problems };
}

/** The literal command line to display, for the preview above the Start button. */
function previewCommand(command, values, options) {
  const { argv, problems } = buildArgv(command, values, options);
  if (problems.length) return null;
  return ['movie-review', command, ...argv].join(' ');
}

/** Field metadata for the renderer, including each option's CLI default. */
function describeCommand(command) {
  const spec = COMMAND_FIELDS[command];
  if (!spec) return null;
  return {
    fields: spec.fields.map((f) => ({
      key: f.key,
      flag: f.flag,
      type: f.type || 'string',
      cliDefault: f.cliDefault === undefined ? null : f.cliDefault,
    })),
    switches: spec.switches.map((s) => ({ key: s.key, flag: s.flag })),
  };
}

module.exports = { buildArgv, previewCommand, describeCommand, COMMAND_FIELDS };

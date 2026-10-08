'use strict';

/**
 * Turn one line of CLI output into a structured entry the UI can render.
 *
 * The CLI writes two different things to stderr and the desktop app has to
 * understand both, because neither alone answers "is this run healthy?":
 *
 *   1. One-line JSON from `utils.logging.JsonFormatter` -- level, logger, event,
 *      status, stage, duration. This is the record of what the pipeline decided.
 *   2. Human progress lines from `cli.app._ProgressReporter` -- stage starts,
 *      stage verdicts, in-stage bars and liveness heartbeats. These exist so a
 *      multi-hour run never looks hung, and they are the only signal that
 *      arrives while a single stage is working.
 *
 * Anything else is passed through as text rather than dropped: an ffmpeg
 * complaint the pipeline never wrapped in a log record is still the reason a run
 * failed, and hiding it would leave the user with a red bar and no explanation.
 *
 * The patterns mirror `cli/app.py` exactly. If the CLI's format changes, these
 * regexes are the thing that must change with it, which is why they live in one
 * tested module instead of being spread through the renderer.
 */

/** `  -> vision (stage 4/19) ...` */
const STAGE_START = /^\s*->\s+(\S+)\s+\(stage\s+(\d+)\/(\d+)\)\s*\.\.\.\s*$/;
/** `  vision: OK (1m03s, stage 4/19)` and the FAILED variant. */
const STAGE_END = /^\s*(\S+):\s+(OK|FAILED)\s+\(([^,]+),\s*stage\s+(\d+)\/(\d+)\)\s*$/;
/** `  vision [########--------]  42%  scene 12/48 (1m03s)` */
const WORK = /^\s*(\S+)\s+\[([#-]+)\]\s+(\d{1,3})%(?:\s+(.*?))?\s*\(([^)]+)\)\s*$/;
/** `    ... transcript still running (3m05s)` */
const HEARTBEAT = /^\s*\.\.\.\s+(\S+)\s+still running\s+\(([^)]+)\)\s*$/;
/** `    error: some message` */
const ERROR = /^\s*error:\s*(.+)$/;
/** `job_id=job_20261008_001 status=CREATED` */
const JOB = /^job_id=(\S+)\s+status=(\S+)\s*$/;
/** `Retrying stage: vision` */
const RETRYING = /^Retrying stage:\s*(\S+)\s*$/;

function tryJson(line) {
  const trimmed = line.trim();
  if (!trimmed.startsWith('{') || !trimmed.endsWith('}')) return null;
  try {
    const value = JSON.parse(trimmed);
    // A JSON array or scalar is not a log record; `{"a":1}` is.
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
    return value;
  } catch {
    return null;
  }
}

function elapsedToSeconds(text) {
  if (!text) return null;
  const match = /^(\d+)m(\d{2})s$/.exec(text.trim());
  if (match) return Number(match[1]) * 60 + Number(match[2]);
  const seconds = /^(\d+)s$/.exec(text.trim());
  return seconds ? Number(seconds[1]) : null;
}

function percentFromBar(bar) {
  if (typeof bar !== 'string' || bar.length === 0) return null;
  const filled = bar.split('').filter((c) => c === '#').length;
  return Math.round((filled / bar.length) * 100);
}

/**
 * Classify one output line.
 *
 * @param {string} line
 * @param {'stdout'|'stderr'} [stream] which stream it arrived on
 * @returns {object} an entry with a `kind` the renderer switches on
 */
function parseLine(line, stream = 'stderr') {
  const text = String(line).replace(/\r$/, '');

  const record = tryJson(text);
  if (record) {
    return {
      kind: 'log',
      stream,
      level: record.level || 'INFO',
      logger: record.logger || 'movie_review',
      message: record.message || '',
      event: record.event || null,
      status: record.status || null,
      stage: record.stage || null,
      jobId: record.job_id || null,
      durationMs: record.duration_ms === undefined ? null : record.duration_ms,
      error: record.error || null,
      raw: text,
    };
  }

  let match = STAGE_START.exec(text);
  if (match) {
    return {
      kind: 'stage-start',
      stage: match[1],
      index: Number(match[2]),
      total: Number(match[3]),
    };
  }

  match = STAGE_END.exec(text);
  if (match) {
    return {
      kind: 'stage-end',
      stage: match[1],
      ok: match[2] === 'OK',
      verdict: match[2],
      elapsed: match[3],
      elapsedSeconds: elapsedToSeconds(match[3]),
      index: Number(match[4]),
      total: Number(match[5]),
    };
  }

  match = WORK.exec(text);
  if (match) {
    const label = match[4] ? match[4].trim() : '';
    return {
      kind: 'work',
      stage: match[1],
      bar: match[2],
      // Prefer the printed percentage: the bar is the CLI's own rounded view of
      // the same fraction, and either can be trusted, but the number is what
      // the user was shown.
      percent: Number(match[3]),
      barPercent: percentFromBar(match[2]),
      label,
      elapsed: match[5],
      elapsedSeconds: elapsedToSeconds(match[5]),
    };
  }

  match = HEARTBEAT.exec(text);
  if (match) {
    return {
      kind: 'heartbeat',
      stage: match[1],
      elapsed: match[2],
      elapsedSeconds: elapsedToSeconds(match[2]),
    };
  }

  match = ERROR.exec(text);
  if (match) {
    return { kind: 'error', message: match[1].trim() };
  }

  match = JOB.exec(text);
  if (match) {
    return { kind: 'job', jobId: match[1], status: match[2] };
  }

  match = RETRYING.exec(text);
  if (match) {
    return { kind: 'retrying', stage: match[1] };
  }

  if (text.trim() === '') return { kind: 'blank', stream };
  return { kind: 'text', stream, text };
}

/**
 * A progress tracker fed by parsed lines.
 *
 * Holds the derived view the window needs -- which stage is running, how far
 * along it is, which stages are done -- so the renderer never has to fold the
 * whole log again on every line. Pure and testable on its own.
 */
class ProgressTracker {
  constructor(stages) {
    this.stages = Array.isArray(stages) ? stages.map((s) => s[0]) : [];
    this.reset();
  }

  reset() {
    this.current = null;
    this.percent = 0;
    this.label = '';
    this.completed = [];
    this.failed = null;
  }

  stageState(name) {
    if (this.failed && this.failed.stage === name) return 'failed';
    if (this.current === name) return 'running';
    if (this.completed.includes(name)) return 'done';
    return 'pending';
  }

  /** Apply one parsed entry and return the tracker when something changed. */
  apply(entry) {
    if (!entry) return this;
    if (entry.kind === 'stage-start') {
      this.current = entry.stage;
      this.percent = 0;
      this.label = '';
      return this;
    }
    if (entry.kind === 'work') {
      // Work reported for a stage that is no longer current would move a bar
      // that is not on screen; the pipeline emits it just before the verdict,
      // and the last bar is often 100% of a stage already marked done.
      if (entry.stage !== this.current) return this;
      this.percent = entry.percent;
      this.label = entry.label || '';
      return this;
    }
    if (entry.kind === 'stage-end') {
      if (!this.completed.includes(entry.stage)) this.completed.push(entry.stage);
      this.percent = entry.ok ? 100 : this.percent;
      if (!entry.ok) this.failed = { stage: entry.stage, elapsed: entry.elapsed };
      this.current = null;
      this.label = '';
      return this;
    }
    if (entry.kind === 'job' && entry.status === 'FAILED') {
      this.failed = this.failed || { stage: null, elapsed: null };
    }
    return this;
  }

  /** Fraction of the whole sequence finished, for the overall bar. */
  get overallFraction() {
    const total = this.stages.length || 1;
    let done = this.completed.length;
    if (this.current) {
      done += this.percent > 0 ? Math.min(this.percent, 99) / 100 : 0.5;
    }
    if (this.failed) done = Math.min(done, total - 0.5);
    return Math.max(0, Math.min(1, done / total));
  }

  snapshot() {
    return {
      stages: this.stages.map((name, index) => ({
        name,
        index: index + 1,
        state: this.stageState(name),
      })),
      current: this.current,
      percent: this.percent,
      label: this.label,
      completed: [...this.completed],
      failed: this.failed,
      overallFraction: this.overallFraction,
    };
  }
}

module.exports = { parseLine, ProgressTracker, elapsedToSeconds, percentFromBar };

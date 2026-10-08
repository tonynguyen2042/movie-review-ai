'use strict';

/**
 * Renderer logic (T111).
 *
 * Holds no pipeline knowledge. It renders what the main process reports, collects
 * form values, and asks the main process to act. Anything that decides *what* a
 * run does lives in `argv.js` on the other side of the bridge, so the window can
 * be reloaded without changing a single command line.
 */

const api = window.desktop;

const el = (id) => document.getElementById(id);
const state = {
  stages: [],
  jobs: [],
  selectedJob: null,
  settings: null,
  modelsDraft: null,
  modelsProfile: null,
  running: false,
};

/* ------------------------------------------------------------------ chrome */

function banner(message, kind) {
  const node = el('banner');
  if (!message) {
    node.hidden = true;
    node.textContent = '';
    return;
  }
  node.hidden = false;
  node.textContent = message;
  node.className = `banner${kind === 'ok' ? ' is-ok' : ''}`;
}

function quiet(message) {
  banner(message, 'ok');
  setTimeout(() => banner(null), 4000);
}

document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('is-active'));
    document.querySelectorAll('.panel').forEach((p) => p.classList.remove('is-active'));
    tab.classList.add('is-active');
    document.querySelector(`[data-panel="${tab.dataset.tab}"]`).classList.add('is-active');
    if (tab.dataset.tab === 'jobs') loadJobs();
    if (tab.dataset.tab === 'settings') loadSettings();
    if (tab.dataset.tab === 'models') loadModels();
  });
});

/* --------------------------------------------------------------------- run */

function currentCommand() {
  return el('command').value;
}

function collectValues() {
  const values = {};
  document.querySelectorAll('#dynamic-fields [name]').forEach((input) => {
    values[input.name] = input.type === 'checkbox' ? input.checked : input.value;
  });
  // `publish` keeps --confirm behind its own checkbox rather than the generic
  // switch list, because publishing is the one irreversible action here.
  if (currentCommand() === 'publish') {
    values.publishNow = el('confirm-now') ? el('confirm-now').checked : false;
  }
  return values;
}

function collectOptions() {
  return {
    movie: el('movie').value.trim(),
    jobId: el('jobId').value.trim(),
  };
}

function profileSelect() {
  const select = document.createElement('select');
  const blank = document.createElement('option');
  // Empty means "let config/default.yaml choose", which is the common case and
  // must stay distinguishable from an explicit choice.
  blank.value = '';
  blank.textContent = '(from config/default.yaml)';
  select.append(blank);
  ((state.settings && state.settings.profiles) || []).forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.append(option);
  });
  return select;
}

async function renderFields() {
  const command = currentCommand();
  const spec = await api.describeCommand(command);
  const host = el('dynamic-fields');
  host.textContent = '';

  el('movie-field').hidden = command !== 'process';
  el('job-field').hidden = command === 'process';

  if (spec && spec.fields) {
    spec.fields.forEach((field) => {
      const wrapper = document.createElement('label');
      wrapper.className = 'field';
      const caption = document.createElement('span');
      // The CLI default is shown next to the field so it is always clear what
      // "left empty" means -- an invisible default is how a run silently uses a
      // 20-minute review instead of the 8 the user asked for.
      caption.textContent = field.cliDefault
        ? `${field.flag} (CLI default: ${field.cliDefault})`
        : field.flag;

      // The profile is a closed set, so it is a dropdown: a typo there fails at
      // job creation, minutes after the user committed to a run.
      const input =
        field.key === 'profile'
          ? profileSelect()
          : Object.assign(document.createElement('input'), {
              type: 'text',
              placeholder: field.cliDefault || '',
            });
      input.name = field.key;
      input.addEventListener('input', updatePreview);
      input.addEventListener('change', updatePreview);
      wrapper.append(caption, input);
      host.append(wrapper);
    });
  }

  if (command === 'publish') {
    const wrapper = document.createElement('label');
    wrapper.className = 'checkbox';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.id = 'confirm-now';
    const label = document.createElement('span');
    label.innerHTML =
      'Upload now <span class="flag">--confirm</span> — off means preview only';
    input.addEventListener('change', updatePreview);
    wrapper.append(input, label);
    host.append(wrapper);
  }

  updatePreview();
}

async function updatePreview() {
  const command = currentCommand();
  if (command === 'validate') {
    el('preview').textContent = `movie-review validate ${collectOptions().jobId}`;
    el('preview').classList.remove('is-problem');
    return;
  }
  const result = await api.run.preview(command, collectValues(), collectOptions());
  if (result.problems.length) {
    el('preview').textContent = result.problems.join(' ');
    el('preview').classList.add('is-problem');
  } else {
    el('preview').textContent = result.preview;
    el('preview').classList.remove('is-problem');
  }
}

el('command').addEventListener('change', renderFields);
el('movie').addEventListener('input', updatePreview);
el('jobId').addEventListener('input', updatePreview);

el('pick-movie').addEventListener('click', async () => {
  const result = await api.dialog.pickMovie();
  if (result.ok && result.path) {
    el('movie').value = result.path;
    updatePreview();
  }
});

el('pick-job').addEventListener('click', () => {
  document.querySelector('[data-tab="jobs"]').click();
  quiet('Pick a row in Jobs; it fills the job id for this command.');
});

async function startRun(command) {
  banner(null);
  const result = await api.run.start(command, collectValues(), collectOptions());
  if (!result.ok) {
    banner(result.errors.join('\n'));
    return;
  }
  state.running = true;
  el('start').disabled = true;
  el('stop').disabled = false;
  el('run-hint').textContent = `Running: ${result.argv.join(' ')}`;
}

el('start').addEventListener('click', () => startRun(currentCommand()));

el('validate').addEventListener('click', async () => {
  const jobId = collectOptions().jobId;
  if (!jobId) {
    banner('Choose a job first.');
    return;
  }
  startRun('validate');
});

el('stop').addEventListener('click', async () => {
  const result = await api.run.stop();
  if (!result.ok) banner(result.errors.join('\n'));
});

api.run.onBeforeClose(async () => {
  if (!state.running) {
    window.__forceQuit = true;
    window.close();
    return;
  }
  const leave = window.confirm(
    'A run is still in progress. Stop it and quit?\n\nThe job stays resumable from the Jobs tab.',
  );
  if (!leave) return;
  await api.run.stop();
  state.running = false;
  window.__forceQuit = true;
  window.close();
});

/* --------------------------------------------------------------------- log */

function stamp() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
}

function describe(entry) {
  switch (entry.kind) {
    case 'log': {
      // `log_event` records the event name as the message and puts the useful
      // detail in sibling fields, so showing only the message would print a
      // column of "stage.completed" with no idea which stage.
      const parts = [entry.message];
      if (entry.stage) parts.push(`[${entry.stage}]`);
      if (entry.durationMs !== null && entry.durationMs !== undefined) {
        parts.push(`(${entry.durationMs}ms)`);
      }
      if (entry.jobId) parts.push(`job=${entry.jobId}`);
      if (entry.error) parts.push(`\n${entry.error}`);
      return { cls: `is-ERROR level-${entry.level}`, level: entry.level, text: parts.join(' ') };
    }
    case 'stage-start':
      return { cls: 'is-stage-start', level: 'stage', text: `-> ${entry.stage} (${entry.index}/${entry.total})` };
    case 'stage-end':
      return {
        cls: entry.ok ? 'is-stage-end' : 'is-error',
        level: entry.verdict,
        text: `${entry.stage}: ${entry.verdict} (${entry.elapsed})`,
      };
    case 'work':
      return {
        cls: 'is-work',
        level: 'work',
        text: `${entry.stage} ${entry.bar} ${String(entry.percent).padStart(3)}%${entry.label ? `  ${entry.label}` : ''} (${entry.elapsed})`,
      };
    case 'heartbeat':
      return { cls: 'is-heartbeat', level: 'beat', text: `... ${entry.stage} still running (${entry.elapsed})` };
    case 'error':
      return { cls: 'is-error', level: 'error', text: entry.message };
    case 'job':
      return { cls: 'is-job', level: 'job', text: `${entry.jobId} status=${entry.status}` };
    case 'retrying':
      return { cls: 'is-retrying', level: 'retry', text: `retrying stage: ${entry.stage}` };
    case 'verdict':
      return {
        cls: `is-verdict-${entry.verdict === 'succeeded' ? 'ok' : entry.verdict === 'cancelled' ? 'cancelled' : 'bad'}`,
        level: entry.verdict,
        text:
          entry.verdict === 'succeeded'
            ? 'run finished successfully'
            : entry.verdict === 'cancelled'
              ? 'run cancelled — the job can be resumed'
              : `run failed (exit ${entry.exitCode})${entry.failedStage ? ` at ${entry.failedStage}` : ''}`,
      };
    default:
      return { cls: `is-${entry.kind}`, level: '', text: entry.text || '' };
  }
}

function appendEntry(entry) {
  const log = el('log');
  const info = describe(entry);
  const line = document.createElement('div');
  line.className = `line ${info.cls}`;
  const time = document.createElement('span');
  time.className = 'time';
  time.textContent = stamp();
  const level = document.createElement('span');
  level.className = 'level';
  level.textContent = info.level;
  const body = document.createElement('span');
  body.className = 'body';
  body.textContent = info.text;
  line.append(time, level, body);
  log.append(line);
  if (el('autoscroll').checked) log.scrollTop = log.scrollHeight;
}

el('clear-log').addEventListener('click', () => {
  el('log').textContent = '';
});

api.run.onReset(({ stages }) => {
  el('log').textContent = '';
  // `stages` arrives as [name, title] pairs from STAGE_SEQUENCE; the list needs
  // the name on its own.
  state.stages = stages || [];
  renderStages(state.stages.map((stage) => ({ name: stage[0], state: 'pending' })));
  setOverall(0, 'starting');
});

api.run.onEntry(appendEntry);

api.run.onProgress((snapshot) => {
  renderStages(snapshot.stages);
  setOverall(snapshot.overallFraction, describeOverall(snapshot));
  if (snapshot.current) {
    el('stage-now').textContent = snapshot.current;
    el('stage-fill').style.width = `${snapshot.percent}%`;
    el('stage-label').textContent =
      `${snapshot.percent}%${snapshot.label ? ` · ${snapshot.label}` : ''}`;
  } else if (snapshot.failed) {
    el('stage-now').textContent = `failed at ${snapshot.failed.stage}`;
    el('stage-fill').style.width = '100%';
    el('stage-fill').classList.add('is-bad');
    el('stage-label').textContent = snapshot.failed.elapsed || '';
  }
});

api.run.onFinished(({ verdict, exitCode, snapshot }) => {
  state.running = false;
  el('start').disabled = false;
  el('stop').disabled = true;
  el('stage-fill').classList.remove('is-bad');
  // Leaving the last stage's name on screen reads as "still running", which is
  // exactly the wrong impression at the moment the run has ended.
  if (snapshot && snapshot.failed) {
    el('stage-now').textContent = `failed at ${snapshot.failed.stage}`;
  } else {
    el('stage-now').textContent = verdict === 'cancelled' ? 'run cancelled' : 'run finished';
  }
  el('stage-label').textContent = '';
  if (verdict === 'failed') {
    banner(`The CLI exited ${exitCode}. See the log for the failing stage.`);
  }
  loadJobs();
});

function describeOverall(snapshot) {
  const done = snapshot.completed.length;
  const total = snapshot.stages.length || '?';
  return snapshot.current
    ? `${done}/${total} · ${snapshot.current} ${snapshot.percent}%`
    : `${done}/${total} stages`;
}

function setOverall(fraction, text) {
  const pct = Math.round(fraction * 100);
  const fill = el('overall-fill');
  fill.style.width = `${pct}%`;
  el('overall-text').textContent = `${pct}% · ${text}`;
}

function renderStages(stages) {
  const host = el('stages');
  host.textContent = '';
  stages.forEach((stage) => {
    const item = document.createElement('li');
    item.className = `is-${stage.state}`;
    const dot = document.createElement('span');
    dot.className = 'dot';
    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = stage.name;
    item.append(dot, name);
    host.append(item);
  });
}

/* -------------------------------------------------------------------- jobs */

async function loadJobs() {
  const result = await api.jobs.list(200);
  const body = el('jobs-body');
  body.textContent = '';
  if (!result.ok) {
    body.innerHTML = `<tr class="empty"><td colspan="5"></td></tr>`;
    body.firstChild.textContent = result.errors.join('; ');
    return;
  }
  state.jobs = result.jobs;
  if (!result.jobs.length) {
    const row = document.createElement('tr');
    row.className = 'empty';
    const cell = document.createElement('td');
    cell.colSpan = 5;
    cell.textContent = 'No jobs yet.';
    row.append(cell);
    body.append(row);
    return;
  }
  result.jobs.forEach((job) => body.append(jobRow(job)));
}

function jobRow(job) {
  const row = document.createElement('tr');
  row.dataset.jobId = job.job_id;
  if (job.job_id === state.selectedJob) row.classList.add('is-selected');

  const id = document.createElement('td');
  id.className = 'mono';
  id.textContent = job.job_id;

  const status = document.createElement('td');
  status.textContent = job.status;
  // Status is the first thing a user scans, so it is coloured rather than left
  // for them to read word by word.
  if (job.status === 'FAILED') status.className = 'err';
  else if (job.status === 'COMPLETED') status.className = 'ok';
  else if (job.status === 'NEEDS_REVIEW') status.className = 'warn';

  const stage = document.createElement('td');
  if (job.failed_stage) {
    stage.textContent = job.failed_stage;
    if (job.error) {
      const err = document.createElement('div');
      err.className = 'err';
      err.textContent = job.error;
      stage.append(err);
    }
  } else {
    stage.textContent = '—';
  }

  const input = document.createElement('td');
  input.textContent = job.input_file || '';

  const updated = document.createElement('td');
  updated.textContent = (job.updated_at || '').replace('T', ' ').slice(0, 19);

  row.append(id, status, stage, input, updated);
  row.addEventListener('click', () => {
    state.selectedJob = job.job_id;
    el('jobId').value = job.job_id;
    el('open-output').disabled = false;
    document.querySelectorAll('#jobs-body tr').forEach((r) => r.classList.remove('is-selected'));
    row.classList.add('is-selected');
    updatePreview();
  });
  return row;
}

el('refresh-jobs').addEventListener('click', loadJobs);

el('open-output').addEventListener('click', async () => {
  if (!state.selectedJob) return;
  const result = await api.jobs.openOutput(state.selectedJob);
  if (!result.ok) banner(result.errors.join('\n'));
});

/* ------------------------------------------------------------------ models */

const SLOTS = ['asr', 'vision', 'reasoning', 'critic', 'translation', 'tts'];
const MODEL_FIELDS = [
  'model',
  'precision',
  'backend',
  'base_url',
  'endpoint_path',
  'api_key_env',
  'timeout_seconds',
  'max_tokens',
  'enabled',
];

async function loadSettings() {
  const result = await api.settings.read();
  state.settings = result;
  el('settings-path').textContent = result.paths ? result.paths.config : '';
  if (result.load_error) {
    showErrors('settings-errors', [result.load_error]);
  } else {
    el('settings-errors').hidden = true;
  }
  renderInto(el('settings-body'), result.default || {}, '');
  loadModels();
}

async function loadModels() {
  if (!state.settings) state.settings = await api.settings.read();
  const result = state.settings;
  el('models-path').textContent = result.paths ? result.paths.models : '';
  state.modelsDraft = JSON.parse(JSON.stringify(result.models || {}));
  const picker = el('profile-picker');
  picker.textContent = '';
  (result.profiles || []).forEach((name) => {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    picker.append(option);
  });
  state.modelsProfile =
    (result.default && result.default.models && result.default.models.profile) ||
    (result.profiles || [])[0] ||
    null;
  if (state.modelsProfile) picker.value = state.modelsProfile;
  renderModels();
}

el('profile-picker').addEventListener('change', () => {
  state.modelsProfile = el('profile-picker').value;
  renderModels();
});

function renderModels() {
  const host = el('models-body');
  host.textContent = '';
  const profiles = (state.modelsDraft && state.modelsDraft.profiles) || {};
  const slots = profiles[state.modelsProfile] || {};

  const note = document.createElement('p');
  note.className = 'note';
  note.textContent = `Profile "${state.modelsProfile}". Blank fields are omitted when saving, so the CLI defaults apply.`;
  host.append(note);

  SLOTS.forEach((slot) => {
    if (!(slot in slots)) return;
    const spec = slots[slot] || {};
    const box = document.createElement('div');
    box.className = 'slot';
    const title = document.createElement('h3');
    title.textContent = slot;
    const flag = document.createElement('span');
    flag.className = 'flag';
    flag.textContent = slot === 'translation' ? 'optional, falls back to reasoning' : '';
    title.append(flag);
    box.append(title);

    const grid = document.createElement('div');
    grid.className = 'slot-grid';
    MODEL_FIELDS.forEach((name) => {
      const value = spec[name];
      if (value === undefined) return;
      const label = document.createElement('label');
      label.className = 'field';
      const caption = document.createElement('span');
      caption.textContent = name;
      const input = document.createElement('input');
      input.type = 'text';
      input.dataset.slot = slot;
      input.dataset.field = name;
      input.value = value === null ? '' : String(value);
      input.addEventListener('change', () => {
        const target = state.modelsDraft.profiles[state.modelsProfile][slot];
        const raw = input.value.trim();
        if (raw === '') {
          delete target[name];
        } else if (raw === 'true' || raw === 'false') {
          target[name] = raw === 'true';
        } else if (raw !== '' && !Number.isNaN(Number(raw))) {
          target[name] = Number(raw);
        } else {
          target[name] = raw;
        }
      });
      label.append(caption, input);
      grid.append(label);
    });
    box.append(grid);
    host.append(box);
  });
}

el('save-models').addEventListener('click', async () => {
  showErrors('models-errors', []);
  el('save-models').disabled = true;
  try {
    const result = await api.settings.write('models', state.modelsDraft);
    if (!result.ok) {
      showErrors('models-errors', result.errors);
      return;
    }
    quiet(`Saved ${result.path}${result.backup ? ` (backup: ${result.backup})` : ''}`);
    await loadSettings();
  } finally {
    el('save-models').disabled = false;
  }
});

/* ---------------------------------------------------------------- settings */

function renderInto(host, data, prefix) {
  Object.entries(data).forEach(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
      const title = document.createElement('h3');
      title.textContent = path;
      title.style.margin = '10px 0 0';
      title.style.fontSize = '12px';
      title.style.color = 'var(--muted)';
      host.append(title);
      renderInto(host, value, path);
      return;
    }
    const label = document.createElement('label');
    label.className = 'field';
    const caption = document.createElement('span');
    caption.textContent = path;
    const input = document.createElement('input');
    input.type = 'text';
    input.dataset.path = path;
    input.value = value === null ? '' : String(value);
    input.addEventListener('change', () => {
      const raw = input.value.trim();
      const parsed =
        raw === ''
          ? null
          : raw === 'true' || raw === 'false'
            ? raw === 'true'
            : !Number.isNaN(Number(raw)) && raw !== ''
              ? Number(raw)
              : raw;
      setByPath(state.settings.default, path, parsed);
    });
    label.append(caption, input);
    host.append(label);
  });
}

function setByPath(root, path, value) {
  const parts = path.split('.');
  let node = root;
  for (let i = 0; i < parts.length - 1; i += 1) {
    if (typeof node[parts[i]] !== 'object' || node[parts[i]] === null) return;
    node = node[parts[i]];
  }
  node[parts[parts.length - 1]] = value;
}

el('reload-settings').addEventListener('click', () => {
  loadSettings().then(() => quiet('Reloaded from disk.'));
});

el('save-default').addEventListener('click', async () => {
  showErrors('settings-errors', []);
  el('save-default').disabled = true;
  try {
    const result = await api.settings.write('default', state.settings.default);
    if (!result.ok) {
      showErrors('settings-errors', result.errors);
      return;
    }
    quiet(`Saved ${result.path}${result.backup ? ` (backup: ${result.backup})` : ''}`);
    await loadSettings();
  } finally {
    el('save-default').disabled = false;
  }
});

function showErrors(id, errors) {
  const node = el(id);
  node.textContent = '';
  if (!errors || !errors.length) {
    node.hidden = true;
    return;
  }
  node.hidden = false;
  node.textContent = errors.join('\n\n');
}

/* -------------------------------------------------------------------- boot */

(async function boot() {
  const env = await api.environment();
  el('repo-root').textContent = env.repoRoot;
  if (!env.runnerAvailable) {
    el('run-hint').textContent =
      'uv was not found: the CLI cannot be started until it is installed or ' +
      'MOVIE_REVIEW_DESKTOP_RUNNER is set. Browsing and config editing still work.';
  }
  // Read once up front: the profile dropdown and both editors need it, and a
  // failed read is reported on the Settings tab rather than swallowed here.
  state.settings = await api.settings.read();
  const stages = await api.stages();
  if (stages.ok) {
    state.stages = stages.stages.map((pair) => ({ name: pair[0], state: 'pending' }));
    renderStages(state.stages);
  }
  await renderFields();
  const status = await api.run.status();
  if (status.running) {
    state.running = true;
    el('start').disabled = true;
    el('stop').disabled = false;
  }
  const entries = await api.run.entries();
  if (entries.ok) entries.entries.forEach(appendEntry);
  loadJobs();
})();

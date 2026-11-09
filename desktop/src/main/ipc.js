'use strict';

/**
 * IPC surface between the renderer and the CLI.
 *
 * The renderer holds no pipeline logic: it sends a command name plus form values
 * and receives progress events back. Everything stateful (which process is
 * running, the progress tracker) lives in the main process, so a renderer
 * reload or a crash cannot lose a running job's status.
 */

const { ipcMain } = require('electron');
const { PipelineProcess, runBridge, runnerAvailable, REPO_ROOT } = require('./python-runner');
const { buildArgv, previewCommand, describeCommand, COMMAND_FIELDS } = require('./argv');
const { parseLine, ProgressTracker } = require('./line-parser');

/** The one run the app supervises at a time. */
let current = null;
let tracker = new ProgressTracker([]);

/** Bounded log buffer so a long run cannot grow the main process without limit. */
const MAX_ENTRIES = 5000;
const entries = [];

function send(channel, payload) {
  const window = require('electron').BrowserWindow.getAllWindows()[0];
  if (window) window.webContents.send(channel, payload);
}

function pushEntry(entry) {
  entries.push(entry);
  if (entries.length > MAX_ENTRIES) entries.splice(0, entries.length - MAX_ENTRIES);
  send('run:entry', entry);
}

async function register() {
  ipcMain.handle('app:environment', async () => ({
    repoRoot: REPO_ROOT,
    runnerAvailable: runnerAvailable(),
  }));

  ipcMain.handle('stages', async () => runBridge(['stages']));

  ipcMain.handle('settings:read', async () => runBridge(['settings:read']));

  ipcMain.handle('settings:write', async (_event, { payload }) => {
    const args = ['settings:write'];
    // The payload goes to a temp file rather than argv: config JSON is full of
    // quotes and backslashes, and a shell-mangled payload would be written as
    // truth. Writing it ourselves avoids the shell entirely (spawn, not exec).
    const fs = require('node:fs');
    const os = require('node:os');
    const path = require('node:path');
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'movie-review-desktop-'));
    const file = path.join(dir, 'payload.json');
    fs.writeFileSync(file, JSON.stringify(payload), 'utf8');
    try {
      return await runBridge([...args, '--payload-file', file]);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  ipcMain.handle('jobs:list', async (_event, { limit } = {}) =>
    runBridge(['jobs:list', '--limit', String(limit || 100)]),
  );

  ipcMain.handle('jobs:show', async (_event, { jobId }) => runBridge(['jobs:show', jobId]));

  ipcMain.handle('jobs:open-output', async (_event, { jobId }) => {
    const { shell } = require('electron');
    const fs = require('node:fs');
    const path = require('node:path');
    // Mirrors the CLI's own resolution: <data_dir>/jobs/<job_id>. The desktop app
    // must not guess a second layout that the pipeline does not use.
    const settings = await runBridge(['settings:read']);
    if (!settings.ok) return settings;
    const dataDir = (settings.loaded && settings.loaded.paths && settings.loaded.paths.data_dir)
      || 'data';
    const dir = path.resolve(REPO_ROOT, dataDir, 'jobs', jobId);
    if (!fs.existsSync(dir)) {
      return { ok: false, errors: [`No output directory for ${jobId}: ${dir}`] };
    }
    const result = await shell.openPath(dir);
    return result ? { ok: true, errors: [], path: dir } : { ok: false, errors: [result] };
  });

  ipcMain.handle('dialog:pick-movie', async () => {
    const { dialog, BrowserWindow } = require('electron');
    const window = BrowserWindow.getAllWindows()[0];
    const result = await dialog.showOpenDialog(window, {
      title: 'Choose a movie file',
      properties: ['openFile'],
      filters: [
        { name: 'Video', extensions: ['mp4', 'mkv', 'mov', 'avi', 'webm', 'm4v', 'mpg', 'mpeg'] },
        { name: 'All files', extensions: ['*'] },
      ],
    });
    if (result.canceled || result.filePaths.length === 0) {
      return { ok: true, canceled: true, path: null };
    }
    return { ok: true, canceled: false, path: result.filePaths[0] };
  });

  ipcMain.handle('describe:command', async (_event, { command }) =>
    describeCommand(command) || { ok: false, errors: [`Unknown command ${command}`] },
  );

  ipcMain.handle('run:preview', async (_event, { command, values, options }) => ({
    preview: previewCommand(command, values, options),
    problems: buildArgv(command, values, options).problems,
  }));

  ipcMain.handle('run:entries', async () => ({ ok: true, entries: [...entries] }));

  ipcMain.handle('run:start', async (_event, { command, values, options }) => {
    if (current) {
      return { ok: false, errors: ['A run is already in progress. Stop it first.'] };
    }
    if (!runnerAvailable()) {
      return {
        ok: false,
        errors: [
          'uv was not found on PATH.',
          'Install uv, or set MOVIE_REVIEW_DESKTOP_RUNNER to the command that runs the CLI.',
        ],
      };
    }
    const { argv, problems } = buildArgv(command, values, options);
    if (problems.length) return { ok: false, errors: problems };

    const stages = await runBridge(['stages']);
    tracker = new ProgressTracker(stages.ok ? stages.stages : []);
    entries.length = 0;
    send('run:reset', { command, argv, stages: tracker.stages });

    current = new PipelineProcess({ command, argv });
    current.on('line', (line, stream) => {
      const entry = parseLine(line, stream);
      tracker.apply(entry);
      pushEntry(entry);
      if (entry.kind !== 'blank') send('run:progress', tracker.snapshot());
    });
    current.on('error', (error) => {
      pushEntry({ kind: 'error', message: `Could not start the CLI: ${error.message}` });
    });
    current.on('exit', ({ code, signal, stopping }) => {
      current = null;
      const snapshot = tracker.snapshot();
      // A cancelled run is not a failed run. Reporting exit 1 for a run the
      // user deliberately stopped is the fastest way to make them distrust the
      // failure indicator entirely.
      const verdict = stopping
        ? 'cancelled'
        : code === 0
          ? 'succeeded'
          : 'failed';
      pushEntry({
        kind: 'verdict',
        verdict,
        exitCode: code,
        signal,
        failedStage: snapshot.failed ? snapshot.failed.stage : null,
      });
      send('run:progress', snapshot);
      send('run:finished', { verdict, exitCode: code, signal, snapshot });
    });

    current.start();
    return { ok: true, errors: [], argv, command: current.command };
  });

  ipcMain.handle('run:stop', async () => {
    if (!current) return { ok: false, errors: ['Nothing is running.'] };
    current.stop();
    return { ok: true, errors: [] };
  });

  ipcMain.handle('run:status', async () => ({
    running: current !== null,
    pid: current ? current.pid : null,
  }));
}

module.exports = { register, commands: Object.keys(COMMAND_FIELDS) };

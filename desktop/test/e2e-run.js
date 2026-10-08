'use strict';

/**
 * Drives a real pipeline run through the app (T111).
 *
 * This is the acceptance test that unit tests cannot replace: it proves the
 * window starts a CLI process, receives its stage lines over a pipe, renders
 * them, and reports the verdict. The run is limited to the two stages that need
 * nothing but ffmpeg (`ingest`, `scenes`) so it finishes in seconds and needs no
 * model weights -- the streaming path is what is under test, not the pipeline.
 *
 * Run it from `desktop/` with `node test/e2e-run.js`.
 */

const { app, BrowserWindow } = require('electron');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ipc = require('../src/main/ipc');
const { REPO_ROOT } = require('../src/main/python-runner');

app.disableHardwareAcceleration();
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-gpu-compositing');
app.commandLine.appendSwitch('disable-features=VizDisplayCompositor');

const TIMEOUT_MS = 180000;

/** A 6-second synthetic clip: enough for scene detection to find cuts. */
function makeMovie() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'movie-review-e2e-'));
  const file = path.join(dir, 'clip.mkv');
  execFileSync(
    'ffmpeg',
    [
      '-y',
      '-f', 'lavfi',
      '-i', 'testsrc=size=320x240:rate=15:duration=6',
      '-f', 'lavfi',
      '-i', 'sine=frequency=440:duration=6',
      '-c:v', 'libx264',
      '-preset', 'ultrafast',
      '-pix_fmt', 'yuv420p',
      '-c:a', 'aac',
      '-shortest',
      file,
    ],
    { stdio: 'ignore' },
  );
  return file;
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  await app.whenReady();
  ipc.register();

  const errors = [];
  const window = new BrowserWindow({
    width: 1280,
    height: 900,
    show: true,
    webPreferences: {
      preload: path.join(__dirname, '..', 'src', 'preload', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.webContents.on('console-message', (_e, level, message, line, source) => {
    if (level >= 2) errors.push(`${message} (${source}:${line})`);
  });
  await window.loadFile(path.join(__dirname, '..', 'src', 'renderer', 'index.html'));

  // Let boot() settle so the stage list and the form are populated.
  await window.webContents.executeJavaScript(
    `new Promise((resolve) => {
       const ready = () =>
         document.querySelectorAll('#stages li').length > 0 ? resolve(true) : setTimeout(ready, 200);
       ready();
     })`,
    true,
  );

  const movie = makeMovie();

  // Fill the form exactly as a user would: pick the command, type the path, set
  // a stage range, then press Start. The handler is clicked, not called, so the
  // IPC round trip is part of what is being tested.
  await window.webContents.executeJavaScript(
    `(() => {
       const set = (name, value) => {
         const input = document.querySelector('#dynamic-fields [name="' + name + '"]');
         if (input) { input.value = value; input.dispatchEvent(new Event('input')); }
       };
       document.getElementById('movie').value = ${JSON.stringify(movie)};
       set('stageFrom', 'ingest');
       set('stageTo', 'scenes');
       document.getElementById('movie').dispatchEvent(new Event('input'));
       return document.getElementById('preview').textContent;
     })()`,
    true,
  );

  const preview = await window.webContents.executeJavaScript(
    `document.getElementById('preview').textContent`,
    true,
  );

  const started = await window.webContents.executeJavaScript(
    `(() => { document.getElementById('start').click(); return true; })()`,
    true,
  );
  assert(started);

  const finished = await window.webContents.executeJavaScript(
    `new Promise((resolve) => {
       const deadline = Date.now() + ${TIMEOUT_MS};
       const poll = () => {
         const verdict = document.querySelector('#log .is-verdict-ok, #log .is-verdict-bad, #log .is-verdict-cancelled');
         if (verdict) resolve({ text: verdict.textContent, cls: verdict.className });
         else if (Date.now() > deadline) resolve({ text: null, cls: 'timeout' });
         else setTimeout(poll, 300);
       };
       poll();
     })`,
    true,
  );

  const state = await window.webContents.executeJavaScript(
    `({
       lines: document.querySelectorAll('#log .line').length,
       logText: document.getElementById('log').textContent,
       doneStages: Array.from(document.querySelectorAll('#stages li.is-done')).map((li) => li.querySelector('.name').textContent),
       failedStages: Array.from(document.querySelectorAll('#stages li.is-failed')).map((li) => li.querySelector('.name').textContent),
       overall: document.getElementById('overall-text').textContent,
       stageNow: document.getElementById('stage-now').textContent,
       banner: document.getElementById('banner').hidden ? null : document.getElementById('banner').textContent,
       startDisabled: document.getElementById('start').disabled,
     })`,
    true,
  );

  // The log sits below the fold on a 900px window, and it is the part worth
  // looking at: scroll it into view for its own capture.
  await window.webContents.executeJavaScript(
    `document.querySelector('.log-card').scrollIntoView({ block: 'start' });
     new Promise((r) => setTimeout(r, 400))`,
    true,
  );
  const image = await window.webContents.capturePage();
  fs.writeFileSync(path.join(REPO_ROOT, 'desktop', 'screenshot-e2e.png'), image.toPNG());
  fs.rmSync(path.dirname(movie), { recursive: true, force: true });

  const report = {
    preview,
    finished,
    doneStages: state.doneStages,
    failedStages: state.failedStages,
    overall: state.overall,
    stageNow: state.stageNow,
    banner: state.banner,
    startDisabled: state.startDisabled,
    lineCount: state.lines,
    rendererErrors: errors,
  };
  console.log(JSON.stringify(report, null, 2));

  const sawStageLines = /-> ingest/.test(state.logText) && /ingest: OK/.test(state.logText);
  // The verdict element carries layout classes too, so match on the token.
  const succeeded = String(finished.cls).includes('is-verdict-ok');
  app.exit(errors.length || !sawStageLines || !succeeded ? 1 : 0);
}

function assert(condition, message) {
  if (!condition) throw new Error(message || 'assertion failed');
}

main()
  .catch((error) => {
    console.error(error);
    app.exit(1);
  })
  .catch(() => wait(0));

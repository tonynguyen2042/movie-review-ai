'use strict';

/**
 * Verifies that Stop terminates a running pipeline and reports it as cancelled
 * (T111).
 *
 * Two things are being checked, and the second is the reason this test exists:
 *
 *   1. The child actually goes away. The CLI spawns ffmpeg, so killing only the
 *      parent would leave an encoder running and holding the output file.
 *   2. The verdict is "cancelled", not "failed". A deliberate stop reported as a
 *      failure is how a user learns to ignore the failure indicator.
 *
 * The run has to be slow enough to interrupt, which is why this generates a
 * ten-minute clip: `scenes` then runs PySceneDetect over 3000 frames and takes
 * long enough to press the button mid-stage.
 *
 * Run from `desktop/` with `npx electron test/e2e-stop.js`.
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

const TIMEOUT_MS = 240000;

/** A ten-minute clip: long enough that `scenes` is still working when we stop. */
function makeLongMovie() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'movie-review-stop-'));
  const file = path.join(dir, 'long.mkv');
  execFileSync(
    'ffmpeg',
    [
      '-y',
      '-f', 'lavfi',
      '-i', 'testsrc=size=320x240:rate=25:duration=600',
      '-f', 'lavfi',
      '-i', 'sine=frequency=440:duration=600',
      '-c:v', 'libx264',
      '-preset', 'ultrafast',
      '-crf', '40',
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
  window.webContents.on('console-message', (_e, level, message) => {
    if (level >= 2) errors.push(message);
  });
  await window.loadFile(path.join(__dirname, '..', 'src', 'renderer', 'index.html'));
  await window.webContents.executeJavaScript(
    `new Promise((resolve) => {
       const ready = () =>
         document.querySelectorAll('#stages li').length > 0 ? resolve(true) : setTimeout(ready, 200);
       ready();
     })`,
    true,
  );

  const movie = makeLongMovie();

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
       document.getElementById('start').click();
       return true;
     })()`,
    true,
  );

  // Wait until the stage that is slow to finish has started, so the stop lands
  // mid-run rather than after everything already completed.
  const reachedScenes = await window.webContents.executeJavaScript(
    `new Promise((resolve) => {
       const deadline = Date.now() + ${TIMEOUT_MS};
       const poll = () => {
         if (/-> scenes/.test(document.getElementById('log').textContent)) resolve(true);
         else if (Date.now() > deadline) resolve(false);
         else setTimeout(poll, 200);
       };
       poll();
     })`,
    true,
  );

  // Prove the run really was in flight when the button was pressed. Without
  // this the test would also pass by stopping a process that had already
  // finished, which is not what Stop is for.
  const before = await window.webContents.executeJavaScript(
    `window.desktop.run.status()`,
    true,
  );

  const stopRequested = await window.webContents.executeJavaScript(
    `(() => { document.getElementById('stop').click(); return true; })()`,
    true,
  );

  const finished = await window.webContents.executeJavaScript(
    `new Promise((resolve) => {
       const deadline = Date.now() + 60000;
       const poll = () => {
         const node = document.querySelector('#log .is-verdict-cancelled, #log .is-verdict-bad, #log .is-verdict-ok');
         if (node) resolve({ text: node.textContent, cls: node.className });
         else if (Date.now() > deadline) resolve({ text: null, cls: 'timeout' });
         else setTimeout(poll, 200);
       };
       poll();
     })`,
    true,
  );

  const state = await window.webContents.executeJavaScript(
    `({
       log: document.getElementById('log').textContent,
       startDisabled: document.getElementById('start').disabled,
       stopDisabled: document.getElementById('stop').disabled,
       stageNow: document.getElementById('stage-now').textContent,
       doneStages: Array.from(document.querySelectorAll('#stages li.is-done')).map((li) => li.querySelector('.name').textContent),
     })`,
    true,
  );

  // The child must be gone, not merely unreferenced.
  const after = await window.webContents.executeJavaScript(
    `window.desktop.run.status()`,
    true,
  );

  const image = await window.webContents.capturePage();
  fs.writeFileSync(path.join(REPO_ROOT, 'desktop', 'screenshot-e2e-stop.png'), image.toPNG());
  fs.rmSync(path.dirname(movie), { recursive: true, force: true });

  const cancelled = String(finished.cls).includes('is-verdict-cancelled');
  const report = {
    reachedScenes,
    stopRequested,
    runningBeforeStop: before.running,
    runningAfterStop: after.running,
    pidAfterStop: after.pid,
    verdictClass: finished.cls,
    verdictText: finished.text,
    cancelled,
    startDisabledAfterStop: state.startDisabled,
    stopDisabledAfterStop: state.stopDisabled,
    stageNow: state.stageNow,
    doneStages: state.doneStages,
    // The CLI handles SIGINT and says so on stderr. On Windows a spawned child
    // has no console, so Node cannot deliver SIGINT and `taskkill /T /F` is
    // used instead: the process dies without the chance to print this. The job
    // is still resumable, because the stage never got to record a failure.
    cliReportedInterrupt: /Interrupt/i.test(state.log),
    platform: process.platform,
    rendererErrors: errors,
  };
  console.log(JSON.stringify(report, null, 2));

  app.exit(
    !reachedScenes ||
      !before.running ||
      !cancelled ||
      after.running ||
      errors.length ||
      state.startDisabled
      ? 1
      : 0,
  );
}

main().catch((error) => {
  console.error(error);
  app.exit(1);
});

void wait;

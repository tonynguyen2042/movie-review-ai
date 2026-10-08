'use strict';

/**
 * Launches the real window, waits for it to settle, screenshots it, and exits.
 *
 * This is a manual verification aid, not part of `npm test`: it needs a display
 * and writes a PNG. Run it with `node test/screenshot.js` from `desktop/`.
 *
 * Renderer errors are the failure worth catching. Electron does not fail the
 * process when a renderer script throws: the window simply comes up blank, so
 * the only way to know the UI actually rendered is to ask the page and to look.
 */

const { app, BrowserWindow } = require('electron');
const path = require('node:path');

const ipc = require('../src/main/ipc');
const { REPO_ROOT } = require('../src/main/python-runner');

const TIMEOUT_MS = 25000;

// This machine has no usable GPU for Chromium, and `UnknownVizError` kills the
// renderer before any of the script above runs. Software rendering is the fix
// for a capture harness; the shipped app keeps the default so it animates.
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('disable-software-rasterizer');
app.commandLine.appendSwitch('in-process-gpu');

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

  window.webContents.on('console-message', (_event, level, message, line, source) => {
    if (level >= 2) errors.push(`${message} (${source}:${line})`);
    else console.log(`[renderer:${level}] ${message} (${source}:${line})`);
  });
  window.webContents.on('render-process-gone', (_event, details) => {
    errors.push(`renderer gone: ${details.reason}`);
  });

  await window.loadFile(path.join(__dirname, '..', 'src', 'renderer', 'index.html'));

  // The renderer boots asynchronously: it awaits the environment, the stage list
  // and the job list before it settles. Wait for real content rather than a
  // fixed delay, so a slow machine does not produce a misleading screenshot.
  await window.webContents.executeJavaScript(
    `new Promise((resolve) => {
       const ready = () => {
         const stages = document.querySelectorAll('#stages li').length;
         const jobs = document.querySelectorAll('#jobs-body tr').length;
         const preview = document.getElementById('preview').textContent.trim();
         if (stages > 0 && jobs > 0 && preview) resolve({ stages, jobs, preview });
         else setTimeout(ready, 200);
       };
       ready();
       // Report what was actually missing instead of hanging: an empty
       // selector is the symptom, and this is where it is worth printing.
       setTimeout(() => resolve({
         stages: document.querySelectorAll('#stages li').length,
         jobs: document.querySelectorAll('#jobs-body tr').length,
         preview: document.getElementById('preview').textContent.trim(),
         timedOut: true,
       }), 15000);
     })`,
    true,
  );

  // Capture each tab: one screenshot of a working window says far less than one
  // per panel, and the models editor is only exercised for the `remote` profile
  // (the only one with base_url / api_key_env fields to render).
  const shots = {};
  const fs = require('node:fs');
  const capture = async (name) => {
    const image = await window.webContents.capturePage();
    const out = path.join(REPO_ROOT, 'desktop', `screenshot-${name}.png`);
    fs.writeFileSync(out, image.toPNG());
    shots[name] = out;
  };

  await capture('run');
  await window.webContents.executeJavaScript(
    `document.querySelector('[data-tab="jobs"]').click();
     new Promise((r) => setTimeout(r, 800))`,
    true,
  );
  await capture('jobs');
  await window.webContents.executeJavaScript(
    `document.querySelector('[data-tab="models"]').click();
     document.getElementById('profile-picker').value = 'remote';
     document.getElementById('profile-picker').dispatchEvent(new Event('change'));
     new Promise((r) => setTimeout(r, 800))`,
    true,
  );
  await capture('models-remote');
  await window.webContents.executeJavaScript(
    `document.querySelector('[data-tab="settings"]').click();
     new Promise((r) => setTimeout(r, 1200))`,
    true,
  );
  await capture('settings');
  await window.webContents.executeJavaScript(
    `document.querySelector('[data-tab="models"]').click();
     new Promise((r) => setTimeout(r, 400))`,
    true,
  );

  const state = await window.webContents.executeJavaScript(
    `({
       stages: document.querySelectorAll('#stages li').length,
       stageNow: document.getElementById('stage-now').textContent,
       preview: document.getElementById('preview').textContent,
       modelSlots: document.querySelectorAll('#models-body .slot').length,
       profileOptions: document.getElementById('profile-picker').options.length,
       jobs: document.querySelectorAll('#jobs-body tr').length,
       banner: document.getElementById('banner').hidden
         ? null
         : document.getElementById('banner').textContent,
     })`,
    true,
  );

  console.log(JSON.stringify({ state, errors, shots }, null, 2));
  app.exit(errors.length ? 1 : 0);
}

const timer = setTimeout(() => {
  console.error(`timed out after ${TIMEOUT_MS}ms waiting for the renderer`);
  app.exit(2);
}, TIMEOUT_MS);

main()
  .catch((error) => {
    console.error(error);
    app.exit(1);
  })
  .finally(() => clearTimeout(timer));

'use strict';

/**
 * Electron main entry point (T111).
 *
 * Deliberately thin: it creates the window, registers the IPC surface and gets
 * out of the way. All pipeline behaviour lives in `python-runner.js`, `argv.js`
 * and `line-parser.js`, which are plain Node modules with no Electron imports
 * and can therefore be unit tested without launching a window.
 */

const { app, BrowserWindow, dialog, shell } = require('electron');
const path = require('node:path');

const ipc = require('./ipc');
const { runnerAvailable, REPO_ROOT } = require('./python-runner');

function createWindow() {
  const window = new BrowserWindow({
    width: 1180,
    height: 860,
    minWidth: 900,
    minHeight: 640,
    title: 'Movie Review',
    backgroundColor: '#11151c',
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload', 'preload.js'),
      // The renderer only ever renders local HTML and talks to the main process
      // through the narrow bridge in preload.js. Node integration stays off.
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  window.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));

  // A pipeline run is long; closing the window mid-run must be a choice, not a
  // side effect of clicking the title bar.
  window.on('close', (event) => {
    if (!window.__forceQuit) {
      event.preventDefault();
      window.webContents.send('app:before-close', {});
    }
  });

  // External links open in the browser, never inside the app shell.
  window.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  return window;
}

function warnAboutRunner() {
  if (runnerAvailable()) return;
  dialog.showMessageBox({
    type: 'warning',
    title: 'uv not found',
    message: 'uv was not found on PATH',
    detail:
      'The desktop app runs the pipeline through `uv run movie-review`. ' +
      'Install uv, or set MOVIE_REVIEW_DESKTOP_RUNNER to the command that ' +
      'runs the CLI on this machine.\n\nYou can still browse jobs and edit ' +
      'configuration without it.',
    buttons: ['OK'],
  });
}

app.whenReady().then(() => {
  ipc.register();
  createWindow();
  warnAboutRunner();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// Nothing in this app needs a GPU or a sandboxed helper process; the renderer
// draws text and the pipeline runs in a Python child, not in Chromium.
app.disableHardwareAcceleration();

// Keep the repo root discoverable for support: it is where config/ and data/
// live, and a user reporting "the app ran the wrong config" needs it.
if (!app.isPackaged && process.env.MOVIE_REVIEW_DESKTOP_VERBOSE === '1') {
  console.log(`[desktop] repo root: ${REPO_ROOT}`);
}

'use strict';

/**
 * The only channel between the renderer and Node.
 *
 * The renderer gets a fixed set of named methods and nothing else: no `require`,
 * no `process`, no filesystem. Anything the UI cannot do through this list it
 * cannot do at all, which is what makes `contextIsolation` worth having.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  environment: () => ipcRenderer.invoke('app:environment'),

  stages: () => ipcRenderer.invoke('stages'),

  describeCommand: (command) => ipcRenderer.invoke('describe:command', { command }),

  settings: {
    read: () => ipcRenderer.invoke('settings:read'),
    write: (target, payload) => ipcRenderer.invoke('settings:write', { target, payload }),
  },

  jobs: {
    list: (limit) => ipcRenderer.invoke('jobs:list', { limit }),
    show: (jobId) => ipcRenderer.invoke('jobs:show', { jobId }),
    openOutput: (jobId) => ipcRenderer.invoke('jobs:open-output', { jobId }),
  },

  dialog: {
    pickMovie: () => ipcRenderer.invoke('dialog:pick-movie'),
  },

  run: {
    preview: (command, values, options) =>
      ipcRenderer.invoke('run:preview', { command, values, options }),
    start: (command, values, options) =>
      ipcRenderer.invoke('run:start', { command, values, options }),
    stop: () => ipcRenderer.invoke('run:stop'),
    status: () => ipcRenderer.invoke('run:status'),
    entries: () => ipcRenderer.invoke('run:entries'),

    onReset: (callback) => subscribe('run:reset', callback),
    onEntry: (callback) => subscribe('run:entry', callback),
    onProgress: (callback) => subscribe('run:progress', callback),
    onFinished: (callback) => subscribe('run:finished', callback),
    onBeforeClose: (callback) => subscribe('app:before-close', callback),
  },
});

function subscribe(channel, callback) {
  const handler = (_event, payload) => callback(payload);
  ipcRenderer.on(channel, handler);
  // The renderer is long-lived but the subscriptions are set up per view; the
  // returned unsubscribe keeps a re-render from stacking duplicate listeners.
  return () => ipcRenderer.removeListener(channel, handler);
}

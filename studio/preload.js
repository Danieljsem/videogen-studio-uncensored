const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('studio', {
  isApp: true,
  openOutput: () => ipcRenderer.invoke('open-output'),
  showItem: name => ipcRenderer.invoke('show-item', name),
  saveAs: name => ipcRenderer.invoke('save-as', name),
  openLog: name => ipcRenderer.invoke('open-log', name),
  serverLog: () => ipcRenderer.invoke('server-log'),
  retry: () => ipcRenderer.invoke('retry'),
  onStatus: fn => ipcRenderer.on('splash-status', (_, s) => fn(s)),
});

import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('electronAPI', {
  GetGroups: () => ipcRenderer.invoke('get-groups'),
  RunScript: (groupIdx: number, scriptIdx: number, args: string[]) =>
    ipcRenderer.invoke('run-script', groupIdx, scriptIdx, args),
  PickFile: () => ipcRenderer.invoke('pick-file'),
  PickFolder: () => ipcRenderer.invoke('pick-folder'),
});

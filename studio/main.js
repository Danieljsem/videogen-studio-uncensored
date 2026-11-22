// Videogen Studio – Electron shell around server.py (Wan 2.2 image -> video, Chroma text -> image).
// Starts the Python server with the GPU settings from local.env (written by the installer), shows a splash
// screen, then loads the UI. Windows and Linux.
// Extras: progress in the taskbar, notifications when done, native save/folder dialogs.
const { app, BrowserWindow, ipcMain, dialog, shell, Notification, nativeImage } = require('electron');
const { spawn, execFile } = require('child_process');
const path = require('path');
const fs = require('fs');

const ROOT = path.resolve(__dirname, '..');            // project root
const OUT = path.join(ROOT, process.env.WAN_MOCK === '1' ? 'test/mock_output' : 'output');
const PORT = Number(process.env.WAN_PORT || 7870);   // 7860 is usually taken (Gradio/A1111/Forge)
const URL = `http://127.0.0.1:${PORT}`;
const WIN = process.platform === 'win32';
const PY = WIN ? path.join(ROOT, 'venv', 'Scripts', 'python.exe') : path.join(ROOT, 'venv', 'bin', 'python');
const ICON = path.join(__dirname, 'icon.png');          // notifications
const WIN_ICON = path.join(__dirname, WIN ? 'icon.ico' : 'icon.png');   // window + taskbar
const SERVER_LOG = path.join(__dirname, 'server.log');

let win = null, server = null, ownServer = false, quitting = false, monitor = null, lastState = null;
const seen = new Map();   // job id -> last status (for notifications)

const firstInstance = app.requestSingleInstanceLock();
if (!firstInstance) { app.quit(); process.exit(0); }
app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
app.setAppUserModelId('videogen-studio');   // notifications + taskbar icon

const status = (text, error = false) => win && !win.isDestroyed() && win.webContents.send('splash-status', { text, error });
const sleep = ms => new Promise(r => setTimeout(r, ms));

// UI language: the choice saved in the web UI (localStorage), otherwise the OS language
const LANGS = ['en', 'cs', 'de', 'uk', 'es'];
let lang = LANGS.find(l => (app.getLocale?.() || '').toLowerCase().startsWith(l)) || 'en';
async function syncLang() {
  try {
    const s = await win.webContents.executeJavaScript("(()=>{try{return localStorage.getItem('lang')}catch{return null}})()");
    if (LANGS.includes(s)) lang = s;
  } catch {}
}
const L = (...texts) => texts[LANGS.indexOf(lang)] ?? texts[0];   // L(en, cs, de, uk, es)
const tx = v => (v && typeof v === 'object' ? v[lang] || v.en : v);

// null = nothing running; {foreign:true} = another program holds the port; otherwise our server's state
async function probe(ms = 1500) {
  try {
    const r = await fetch(`${URL}/api/state`, { signal: AbortSignal.timeout(ms) });
    const st = r.ok ? await r.json().catch(() => null) : null;
    return st && st.app === 'videogen-studio' ? st : { foreign: true };
  } catch { return null; }
}
async function ping(ms) { const st = await probe(ms); return st && !st.foreign ? st : null; }

// GPU-specific variables from the installer (KEY=VALUE lines); values already set in the environment win
function localEnv() {
  const out = {};
  try {
    for (const line of fs.readFileSync(path.join(ROOT, 'local.env'), 'utf8').split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
      if (m && !line.trim().startsWith('#')) out[m[1]] = m[2].replace(/^"(.*)"$/, '$1');
    }
  } catch {}
  return out;
}

function startServer() {
  const env = {
    MIOPEN_FIND_MODE: '2', MIOPEN_LOG_LEVEL: '3',   // harmless on NVIDIA; quieter, faster MIOpen on AMD
    ...localEnv(),
    ...process.env,
    PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8',
    WAN_PORT: String(PORT),
  };
  if (WIN && env.HIP_PATH) env.PATH = `${path.join(env.HIP_PATH, 'bin')};${process.env.PATH}`;
  const log = fs.createWriteStream(SERVER_LOG, { flags: 'w' });
  // own process group on Linux, so closing the app also stops generate.py / downloads
  server = spawn(PY, ['-u', path.join(ROOT, 'server.py')], { cwd: ROOT, env, windowsHide: true, detached: !WIN });
  server.stdout.pipe(log); server.stderr.pipe(log);
  server.on('exit', code => {
    server = null;
    if (quitting || !win || win.isDestroyed()) return;
    clearInterval(monitor); win.setProgressBar(-1);
    // show the error screen with "Try again" / "Open log" buttons
    const msg = code === 98 ? portMsg()
      : L(`The generator exited unexpectedly (code ${code}). The video in progress may be lost.`,
          `Generátor se nečekaně ukončil (kód ${code}). Rozpracované video se mohlo ztratit.`,
          `Der Generator wurde unerwartet beendet (Code ${code}). Das laufende Video ist möglicherweise verloren.`,
          `Генератор несподівано завершився (код ${code}). Відео, що створювалося, могло бути втрачене.`,
          `El generador se cerró inesperadamente (código ${code}). El vídeo en curso puede haberse perdido.`);
    win.loadFile(path.join(__dirname, 'splash.html'), { query: { lang } }).then(() => status(msg, true));
  });
  ownServer = true;
}

const portMsg = () => L(`Port ${PORT} is used by another program. Close it, or start Studio with a different WAN_PORT.`,
  `Port ${PORT} používá jiný program. Zavři ho, nebo spusť Studio s jiným WAN_PORT.`,
  `Port ${PORT} wird von einem anderen Programm verwendet. Schließe es oder starte Studio mit einem anderen WAN_PORT.`,
  `Порт ${PORT} зайнятий іншою програмою. Закрийте її або запустіть Studio з іншим WAN_PORT.`,
  `Otro programa está usando el puerto ${PORT}. Ciérralo o inicia Studio con otro WAN_PORT.`);

// server started by an earlier app instance – stop it through the API (also stops generation)
async function shutdownForeign() {
  try { await fetch(`${URL}/api/shutdown`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', signal: AbortSignal.timeout(3000) }); } catch {}
}

function killServer() {
  if (!server || !ownServer) return;
  // including the generate.py / download child processes
  if (WIN) { try { execFile('taskkill', ['/F', '/T', '/PID', String(server.pid)], { windowsHide: true }); } catch {} }
  else { try { process.kill(-server.pid, 'SIGTERM'); } catch { try { server.kill('SIGTERM'); } catch {} } }
  server = null;
}

async function boot() {
  win.loadFile(path.join(__dirname, 'splash.html'), { query: { lang } });
  await new Promise(r => win.webContents.once('did-finish-load', r));
  status(L('Starting…', 'Spouštím…', 'Starte…', 'Запуск…', 'Iniciando…'));
  const first = await probe();
  if (first && first.foreign) return status(portMsg(), true);
  if (!first) {
    if (!fs.existsSync(PY)) return status(L(`Python not found: ${PY} – run the installer first (install.bat / install.sh).`,
      `Nenalezen Python: ${PY} – nejdřív spusť instalátor (install.bat / install.sh).`,
      `Python nicht gefunden: ${PY} – starte zuerst den Installer (install.bat / install.sh).`,
      `Python не знайдено: ${PY} – спочатку запустіть інсталятор (install.bat / install.sh).`,
      `No se encontró Python: ${PY}: ejecuta primero el instalador (install.bat / install.sh).`), true);
    startServer();
    for (let i = 0; i < 120; i++) {               // max ~60 s
      if (!server) return;                        // crashed – the error is already on screen
      if (await ping()) break;
      if (i === 4) status(L('Preparing the generator…', 'Připravuji generátor…', 'Bereite den Generator vor…', 'Готую генератор…', 'Preparando el generador…'));
      await sleep(500);
    }
    if (!(await ping())) return status(L('The server did not start within a minute. Details in server.log.', 'Server nenaběhl do minuty. Podrobnosti v server.log.',
    'Der Server ist nicht innerhalb einer Minute gestartet. Details in server.log.', 'Сервер не запустився протягом хвилини. Подробиці в server.log.',
    'El servidor no arrancó en un minuto. Detalles en server.log.'), true);
  }
  await win.loadURL(URL);
  startMonitor();
}

// taskbar progress + notifications
function startMonitor() {
  clearInterval(monitor);
  monitor = setInterval(async () => {
    const st = await ping();
    if (!st || !win || win.isDestroyed()) return;
    lastState = st;
    await syncLang();
    const run = st.jobs.find(j => j.status === 'running');
    const queued = st.jobs.some(j => j.status === 'queued');
    win.setProgressBar(run ? Math.max(0.02, run.progress) : queued ? 2 : -1, { mode: run ? 'normal' : queued ? 'indeterminate' : 'none' });
    for (const j of st.jobs) {
      const prev = seen.get(j.id);
      seen.set(j.id, j.status);
      if (prev && prev !== j.status && (j.status === 'error')) notify(L('Generation failed', 'Generování selhalo', 'Generierung fehlgeschlagen', 'Помилка генерації', 'La generación falló'), tx(j.error) || j.prompt);
    }
    // finished jobs leave the queue -> look for new videos
    for (const v of st.videos) {
      if (!seen.has('v:' + v.name)) {
        if (seen.has('init') && !v.partial) notify(v.kind === 'image'
          ? L('Image is ready', 'Obrázek je hotový', 'Bild ist fertig', 'Зображення готове', 'La imagen está lista')
          : L('Video is ready', 'Video je hotové', 'Video ist fertig', 'Відео готове', 'El vídeo está listo'), v.prompt || v.name, v.poster);
        seen.set('v:' + v.name, 1);
      }
    }
    seen.set('init', 1);
  }, 2000);
}

function notify(title, body, poster) {
  if (win.isFocused()) return;                   // the app shows its own toast
  win.flashFrame(true);
  if (!Notification.isSupported()) return;
  let icon = ICON;
  if (poster) { const p = path.join(OUT, path.basename(poster)); if (fs.existsSync(p)) icon = p; }
  const n = new Notification({ title, body: String(body).slice(0, 180), icon: nativeImage.createFromPath(icon) });
  n.on('click', () => { win.show(); win.focus(); });
  n.show();
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 920, minWidth: 960, minHeight: 620,
    backgroundColor: '#121110', show: false, icon: WIN_ICON, title: 'Videogen Studio',
    titleBarStyle: 'hidden',
    titleBarOverlay: { color: '#121110', symbolColor: '#9a938a', height: 40 },
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true, spellcheck: false },
  });
  win.once('ready-to-show', () => win.show());
  win.on('focus', () => win.flashFrame(false));
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith(URL) && !url.startsWith('file:')) { e.preventDefault(); shell.openExternal(url); } });
  win.webContents.on('before-input-event', (e, i) => {
    if (i.type !== 'keyDown') return;
    if (i.key === 'F12' || (i.control && i.shift && i.key.toLowerCase() === 'i')) win.webContents.toggleDevTools();
    if (i.key === 'F5' || (i.control && i.key.toLowerCase() === 'r')) { e.preventDefault(); win.webContents.reload(); }
  });
  win.on('close', async e => {
    if (quitting) return;
    e.preventDefault();
    const st = (await ping(4000)) || lastState;   // if the server is busy, use the last known state
    const act = st ? st.jobs.filter(j => ['running', 'queued'].includes(j.status)) : [];
    const downloading = !!(st && st.download && st.download.status === 'running');
    const active = act.length + (downloading ? 1 : 0);
    let stopForeign = false;
    await syncLang();
    if (active) {
      const stop = L('Stop and close', 'Zastavit a zavřít', 'Stoppen und schließen', 'Зупинити й закрити', 'Detener y cerrar');
      const cancel = L('Cancel', 'Zrušit', 'Abbrechen', 'Скасувати', 'Cancelar');
      const keep = L('Keep running in background', 'Nechat běžet na pozadí', 'Im Hintergrund weiterlaufen lassen', 'Залишити працювати у фоні', 'Seguir en segundo plano');
      const buttons = ownServer ? [stop, cancel] : [stop, keep, cancel];
      const img = act.length === 1 && act[0].kind === 'image';
      const message = !act.length
        ? L('A model is being downloaded.', 'Právě se stahuje model.', 'Gerade wird ein Modell heruntergeladen.', 'Зараз завантажується модель.', 'Se está descargando un modelo.')
        : act.length === 1
          ? (img ? L('An image is being generated.', 'Právě se generuje obrázek.', 'Gerade wird ein Bild generiert.', 'Зараз генерується зображення.', 'Se está generando una imagen.')
                 : L('A video is being generated.', 'Právě se generuje video.', 'Gerade wird ein Video generiert.', 'Зараз генерується відео.', 'Se está generando un vídeo.'))
          : L(`${act.length} jobs are in the queue.`, `Ve frontě ${act.length <= 4 ? 'jsou' : 'je'} ${act.length} ${act.length <= 4 ? 'úlohy' : 'úloh'}.`,
              `${act.length} Aufträge sind in der Warteschlange.`, `Завдань у черзі: ${act.length}.`, `Hay ${act.length} tareas en cola.`);
      const dlNote = downloading && act.length ? L(' The model download stops too.', ' Zastaví se i stahování modelu.', ' Auch der Modell-Download wird gestoppt.', ' Завантаження моделі теж зупиниться.', ' También se detendrá la descarga del modelo.') : '';
      const { response } = await dialog.showMessageBox(win, {
        type: 'warning', title: 'Videogen Studio', noLink: true, defaultId: buttons.length - 1, cancelId: buttons.length - 1,
        message,
        detail: (!act.length
          ? L('Closing the app stops the download. It resumes where it stopped next time.',
              'Zavřením aplikace se stahování zastaví. Příště naváže tam, kde skončilo.',
              'Beim Schließen wird der Download gestoppt. Beim nächsten Mal geht es dort weiter.',
              'Закриття застосунку зупинить завантаження. Наступного разу воно продовжиться з того ж місця.',
              'Al cerrar la app se detiene la descarga. La próxima vez continúa donde se quedó.')
          : ownServer ? L('Closing the app stops generation; work in progress will be lost (finished images are kept).',
                              'Zavřením aplikace se generování zastaví a rozpracovaná práce se ztratí (hotové obrázky zůstanou).',
                              'Beim Schließen wird die Generierung gestoppt und die laufende Arbeit geht verloren (fertige Bilder bleiben).',
                              'Закриття застосунку зупинить генерацію, і незавершена робота буде втрачена (готові зображення залишаться).',
                              'Al cerrar la app se detiene la generación y se pierde el trabajo en curso (las imágenes terminadas se conservan).')
          : L('Generation runs in the background (started by an earlier instance). Stop it, or let it finish – the result will appear in the library.',
              'Generování běží na pozadí (spustila ho dřívější instance). Můžeš ho zastavit, nebo nechat doběhnout – výsledek se objeví v knihovně.',
              'Die Generierung läuft im Hintergrund (von einer früheren Instanz gestartet). Stoppe sie oder lass sie fertig laufen – das Ergebnis erscheint in der Bibliothek.',
              'Генерація працює у фоні (її запустив попередній екземпляр). Зупиніть її або дайте завершитися – результат з’явиться в бібліотеці.',
              'La generación sigue en segundo plano (la inició una instancia anterior). Detenla o deja que termine: el resultado aparecerá en la biblioteca.')) + dlNote,
        buttons,
      });
      if (response === buttons.length - 1) return;
      stopForeign = !ownServer && response === 0;
    }
    quitting = true;
    clearInterval(monitor);
    if (stopForeign) await shutdownForeign();
    killServer();
    win.destroy();
  });
  boot();
}

// ---- IPC from the UI ----
const outFile = name => path.join(OUT, path.basename(String(name)));
ipcMain.handle('open-output', () => { fs.mkdirSync(OUT, { recursive: true }); return shell.openPath(OUT); });
ipcMain.handle('show-item', (_, name) => shell.showItemInFolder(outFile(name)));
ipcMain.handle('open-log', (_, name) => {
  const p = outFile(name);
  return fs.existsSync(p) ? shell.openPath(p) : shell.openPath(SERVER_LOG);
});
ipcMain.handle('save-as', async (_, name) => {
  const src = outFile(name);
  const png = src.toLowerCase().endsWith('.png');
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    title: png ? L('Save image', 'Uložit obrázek', 'Bild speichern', 'Зберегти зображення', 'Guardar imagen')
               : L('Save video', 'Uložit video', 'Video speichern', 'Зберегти відео', 'Guardar vídeo'),
    defaultPath: path.join(app.getPath(png ? 'pictures' : 'videos'), path.basename(src)),
    filters: [png ? { name: 'PNG image', extensions: ['png'] } : { name: 'MP4 video', extensions: ['mp4'] }],
  });
  if (canceled || !filePath) return false;
  await fs.promises.copyFile(src, filePath);
  return true;
});
ipcMain.handle('retry', () => { if (!server) boot(); });
ipcMain.handle('server-log', () => shell.openPath(SERVER_LOG));

app.whenReady().then(createWindow);
app.on('window-all-closed', () => { killServer(); app.quit(); });
app.on('before-quit', () => { quitting = true; killServer(); });

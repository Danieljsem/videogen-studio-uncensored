// UI smoke test (dev only). Start the mock server first (set WAN_MOCK=1, WAN_PORT=7861, python server.py),
// put any image at test/example.png, then: studio\node_modules\electron\dist\electron.exe dev\ui_smoke.js
const { app, BrowserWindow } = require('electron');
const path = require('path'), fs = require('fs');
const URL = `http://127.0.0.1:${process.env.WAN_PORT || 7861}`, DIR = path.resolve(__dirname, '..', 'test', 'shots');
fs.mkdirSync(DIR, { recursive: true });
const sleep = ms => new Promise(r => setTimeout(r, ms));
app.whenReady().then(async () => {
  const w = new BrowserWindow({ width: 1440, height: 920, show: false, backgroundColor: '#121110',
    titleBarStyle: 'hidden', titleBarOverlay: { color: '#121110', symbolColor: '#9a938a', height: 40 },
    webPreferences: { preload: path.join(__dirname, '..', 'studio', 'preload.js'), contextIsolation: true, sandbox: true, backgroundThrottling: false } });
  const shot = async n => fs.writeFileSync(path.join(DIR, n + '.png'), (await w.webContents.capturePage()).toPNG());
  const js = c => w.webContents.executeJavaScript(c);
  w.webContents.on('console-message', (e, l, m) => console.log('CONSOLE', m));
  await w.loadURL(URL); await sleep(1500); await shot('1_empty');
  const img = 'data:image/png;base64,' + fs.readFileSync(path.resolve(__dirname, '..', 'test', 'example.png')).toString('base64');
  await js(`setImage({data:${JSON.stringify(img)}}); document.querySelector('#prompt').value='A woman turns toward the camera and smiles warmly, hair moving in the wind'; document.querySelector('#prompt').dispatchEvent(new Event('input')); document.querySelector('#advBtn').click();`);
  await sleep(500); console.log('GO disabled:', await js(`document.querySelector('#go').disabled + ' img=' + !!image`)); await shot('2_filled');
  await js(`submit()`); await sleep(300);
  await js(`setImage({data:${JSON.stringify(img)}}); document.querySelector('#prompt').value='Slow cinematic camera push-in'; submit()`);
  await sleep(6000); await shot('3_running'); console.log('JOBS sig stable:', await js(`(async()=>{const a=document.querySelector('[data-job]'); await new Promise(r=>setTimeout(r,2500)); return a===document.querySelector('[data-job]')})()`));
  await sleep(26000); await shot('4_done'); await js(`document.querySelector('#main').scrollTop=600`); await sleep(400); await shot('4b_scrolled');
  await js(`document.querySelector('.card')?.click()`); await sleep(1500); await shot('5_lightbox');
  console.log('LB:', await js(`try{closeLb(); show('lib'); 'ok'}catch(e){String(e)}`)); await sleep(800); await shot('6_lib');
  console.log('AGAIN:', await js(`(async()=>{openLb(state.videos[0]); document.querySelector('#lbAgain').click(); await new Promise(r=>setTimeout(r,1500)); const j=state.jobs.find(x=>x.status==='running'||x.status==='queued'); if(!j) return 'no job'; await api('/api/cancel',{id:j.id}); await new Promise(r=>setTimeout(r,2500)); await poll(); return JSON.stringify(state.jobs.map(x=>x.status))})()`)); await shot('6b_cancelled');
  w.setSize(820, 900); await js(`show('create')`); await sleep(800); await shot('7_narrow');
  app.exit(0);
});

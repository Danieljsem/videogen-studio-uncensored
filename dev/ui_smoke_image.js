// UI smoke test for text -> image and the in-app model download (dev only).
// Start the mock server first (WAN_MOCK=1, WAN_PORT=7861, python server.py; delete test/mock_packs.json so the
// image model starts "not installed"), then: studio\node_modules\electron\dist\electron.exe dev\ui_smoke_image.js
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
  const step = async (name, fn) => { try { console.log(name, await fn()); } catch (e) { console.log(name, 'FAILED', String(e)); } };
  await w.loadURL(URL); await sleep(1500);
  await js(`show('create','image')`); await sleep(800); await shot('i1_not_installed');
  await step('install visible:', () => js(`!document.querySelector('#install').hidden && document.querySelector('#composer').hidden`));
  await js(`document.querySelector('#dlGo').click()`); await sleep(2500); await shot('i2_downloading');
  await step('dl progress text:', () => js(`document.querySelector('#dlNum')?.textContent`));
  await sleep(8000); await shot('i3_installed');
  await step('composer visible after install:', () => js(`!document.querySelector('#composer').hidden && document.querySelector('#imgModel').options.length`));
  await js(`document.querySelector('#prompt').value='portrait of a woman in a red coat on a rainy street at night, cinematic light'; document.querySelector('#prompt').dispatchEvent(new Event('input')); document.querySelector('#segCount [data-v="2"]').click(); document.querySelector('#advBtn').click();`);
  await sleep(500); await shot('i4_filled');
  await step('go enabled:', () => js(`!document.querySelector('#go').disabled + ' est=' + document.querySelector('#est').textContent`));
  await js(`submit()`); await sleep(4000); await shot('i5_running');
  await step('job:', () => js(`JSON.stringify(state.jobs.map(j=>[j.kind,j.status,j.progress.toFixed(2),tx(j.phase)]))`));
  await sleep(14000); await shot('i6_done');
  await step('images in library:', () => js(`state.videos.filter(v=>v.kind==='image').map(v=>v.name+':'+v.seed).join(', ')`));
  await js(`openLb(state.videos.find(v=>v.kind==='image'))`); await sleep(1200); await shot('i7_lightbox');
  await step('lb buttons:', () => js(`['lbAnimate','lbAgain','lbEdit','lbDel'].map(id=>id+'='+!document.getElementById(id).hidden).join(' ')`));
  await js(`document.querySelector('#lbAnimate').click()`); await sleep(1500); await shot('i8_animate');
  await step('animate ->', () => js(`mode + ' upload=' + !!(image && image.upload) + ' view=' + !document.querySelector('#viewCreate').hidden`));
  await js(`show('lib'); document.querySelector('#libFilter [data-v="image"]').click()`); await sleep(800); await shot('i9_lib_images');
  await step('lib count:', () => js(`document.querySelectorAll('#lib .card').length + ' / ' + document.querySelector('#libSub').textContent`));
  // edit + again on an image
  await step('edit:', () => js(`(async()=>{openLb(state.videos.find(v=>v.kind==='image')); document.querySelector('#lbEdit').click(); await new Promise(r=>setTimeout(r,500)); return mode+' prompt='+document.querySelector('#prompt').value.slice(0,20)+' aspect='+iopts.aspect})()`));
  await step('again+cancel:', () => js(`(async()=>{openLb(state.videos.find(v=>v.kind==='image')); document.querySelector('#lbAgain').click(); await new Promise(r=>setTimeout(r,2500)); const j=state.jobs.find(x=>x.status==='running'||x.status==='queued'); if(!j) return 'no job'; await api('/api/cancel',{id:j.id}); await new Promise(r=>setTimeout(r,2500)); await poll(); return JSON.stringify(state.jobs.map(x=>[x.kind,x.status]))})()`));
  // FAIL in prompt -> partial batch
  await step('fail batch:', () => js(`(async()=>{await api('/api/generate',{kind:'image',prompt:'FAIL test',count:2,aspect:'16:9',mp:1,model:'chroma'}); for(let i=0;i<40;i++){await new Promise(r=>setTimeout(r,1000)); await poll(); const j=state.jobs.find(x=>x.prompt==='FAIL test'); if(j && j.status==='error') return tx(j.error);} return 'timeout'})()`));
  await js(`show('create','image')`); await sleep(800); await shot('i10_error');
  // delete one image
  await step('delete:', () => js(`(async()=>{const n=state.videos.filter(v=>v.kind==='image').length; const r=await api('/api/delete',{name:state.videos.find(v=>v.kind==='image').name}); await poll(); return r.status+' '+n+'->'+state.videos.filter(v=>v.kind==='image').length})()`));
  // language check
  await js(`localStorage.setItem('lang','cs')`); await w.reload(); await sleep(1500); await js(`show('create','image')`); await sleep(600); await shot('i11_cs');
  await js(`localStorage.setItem('lang','en')`);
  w.setSize(820, 900); await sleep(600); await shot('i12_narrow');
  app.exit(0);
});

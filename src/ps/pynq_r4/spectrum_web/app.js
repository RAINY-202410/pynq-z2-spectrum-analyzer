'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="control-token"]').content;
const viewerId = window.crypto && crypto.randomUUID ? crypto.randomUUID() : 'viewer-' + Date.now() + '-' + Math.random().toString(16).slice(2);
let current = null, shownFrame = null, lastFrameKey = '', waterfall = [], cursorBin = null;
let commandBusy = false, screenshotBusy = false, autoSnapshotRun = '';
let drawCount = 0, firstDrawAt = 0, lastDrawAt = 0, previousPhase = '', configuredCases = false;
let savedError = '';
let lastRenderMs = 0;

async function request(path, payload) {
  const options = payload === undefined ? {cache: 'no-store'} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Spectrum-Token': token}, body: JSON.stringify(payload)};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
function errorMessage(text) {
  savedError = text || '';
  $('errorBanner').hidden = !text;
  $('errorText').textContent = text ? text.split('\n').filter(Boolean).slice(-1)[0] : '';
  $('errorDetails').hidden = !text;
  $('errorDetailText').textContent = text || '';
}
function buttons() {
  if (!current) return;
  const running = ['RUNNING', 'CONFIGURING'].includes(current.phase);
  $('startButton').disabled = commandBusy || running;
  $('stopButton').disabled = commandBusy || !running;
  $('exportButton').disabled = commandBusy || screenshotBusy || !current.export_ready || running;
  $('snapshotButton').disabled = commandBusy || screenshotBusy || !shownFrame || (current.screenshot_count || 0) >= 8;
  for (const element of $('runForm').querySelectorAll('input,select')) element.disabled = running || commandBusy;
  $('window').disabled = running || commandBusy || current.mode === 'REPLAY';
}
function selectReplayWindow() {
  if (!current || current.mode !== 'REPLAY') return;
  const item = current.cases.find(c => c.label === $('replayCase').value);
  if (item) $('window').value = item.window;
}
function setupCases(status) {
  if (configuredCases) return;
  $('replayLabel').hidden = status.mode !== 'REPLAY';
  $('sourceNote').textContent = status.mode === 'LIVE' ? '实时采集 · LINE IN → PL FFT。开始后复用同一硬件会话。' : '离线回放 · 来自已归档的真实 PL 频谱。循环显示同一保存帧。';
  for (const item of status.cases) {
    const option = document.createElement('option'); option.value = item.label;
    const labels = {tone1k_hann:'1 kHz · Hann', tone1k_rect:'1 kHz · 矩形', tone2k_hann:'2 kHz · Hann', tone2k_low:'2 kHz · 低音量', dual_hann:'1 + 3 kHz · Hann', dual_rect:'1 + 3 kHz · 矩形', analog_silence:'模拟静音'};
    option.textContent = labels[item.label] || item.label; $('replayCase').appendChild(option);
  }
  if (status.cases.some(c => c.label === 'tone1k_hann')) $('replayCase').value = 'tone1k_hann';
  configuredCases = true; current = status; selectReplayWindow();
}
function fit(canvas) {
  const ratio = Math.min(window.devicePixelRatio || 1, 2), box = canvas.getBoundingClientRect();
  const width = Math.max(200, Math.round(box.width)), height = Math.max(100, Math.round(box.height));
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
  }
  const ctx = canvas.getContext('2d'); ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return {ctx, width, height};
}
function axisRange(frame) {return Math.min(Number($('maxFrequency').value), frame.fs_hz / 2);}
function drawSpectrum(frame) {
  const {ctx, width, height} = fit($('spectrumCanvas')), left = 53, right = width - 14, top = 15, bottom = height - 30;
  const maxHz = axisRange(frame), linear = $('amplitudeUnit').value === 'linear';
  const values = linear ? frame.amplitude : frame.dbfs;
  const minY = linear ? 0 : -100, maxY = linear ? Math.max(1, Math.max(...frame.amplitude) * 1.05) : 0;
  const x = f => left + f / maxHz * (right - left), y = a => bottom - (Math.max(minY, Math.min(maxY, a)) - minY) / (maxY - minY) * (bottom - top);
  ctx.clearRect(0, 0, width, height); ctx.font = '10px Consolas, monospace';
  for (let i = 0; i <= 5; i++) {
    const yy = top + (bottom - top) * i / 5, xx = left + (right - left) * i / 5;
    ctx.strokeStyle = '#243443'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(right, yy); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(xx, top); ctx.lineTo(xx, bottom); ctx.stroke();
    ctx.fillStyle = '#7991a6'; ctx.textAlign = 'right'; const val = maxY - (maxY - minY) * i / 5;
    ctx.fillText(linear ? val.toFixed(2) : val.toFixed(0), left - 10, yy + 3);
    ctx.textAlign = 'center'; const hz = maxHz * i / 5; ctx.fillText(hz >= 1000 ? (hz / 1000).toFixed(1) + 'k' : hz.toFixed(0), xx, bottom + 19);
  }
  ctx.save(); ctx.beginPath(); ctx.rect(left, top, right-left, bottom-top); ctx.clip();
  ctx.beginPath(); let count = 0;
  for (let i = 0; i < values.length && frame.frequency_hz[i] <= maxHz; i++) { if (!count++) ctx.moveTo(x(frame.frequency_hz[i]), y(values[i])); else ctx.lineTo(x(frame.frequency_hz[i]), y(values[i])); }
  ctx.strokeStyle = '#56dacb'; ctx.lineWidth = 1.7; ctx.stroke();
  ctx.lineTo(x(frame.frequency_hz[Math.max(0, count - 1)]), bottom); ctx.lineTo(left, bottom); ctx.closePath();
  const gradient = ctx.createLinearGradient(0, top, 0, bottom); gradient.addColorStop(0, '#56dacb24'); gradient.addColorStop(1, '#56dacb00'); ctx.fillStyle = gradient; ctx.fill();
  if (cursorBin !== null && frame.frequency_hz[cursorBin] <= maxHz) {
    const xx = x(frame.frequency_hz[cursorBin]); ctx.setLineDash([4,4]); ctx.strokeStyle = '#edbd79'; ctx.beginPath(); ctx.moveTo(xx, top); ctx.lineTo(xx, bottom); ctx.stroke();
    ctx.setLineDash([]); ctx.fillStyle = '#edbd79'; ctx.beginPath(); ctx.arc(xx, y(values[cursorBin]), 3, 0, 2*Math.PI); ctx.fill();
  }
  ctx.restore(); ctx.textAlign = 'left'; ctx.fillStyle = '#7991a6'; ctx.fillText(linear ? 'Amplitude' : 'dBFS', 0, 10);
  if (cursorBin !== null) $('cursorReadout').textContent = 'bin ' + cursorBin + ' · ' + frame.frequency_hz[cursorBin].toFixed(2) + ' Hz · ' + frame.dbfs[cursorBin].toFixed(2) + ' dBFS';
}
function color(value) {
  const t = Math.max(0, Math.min(1, (value + 100) / 90));
  const colors = [[14,23,38],[41,59,118],[39,140,158],[94,229,193],[240,211,145]];
  const n = Math.min(3, Math.floor(t*4)), v = t*4-n;
  return colors[n].map((a,i) => Math.round(a + (colors[n+1][i]-a)*v));
}
function drawWaterfall(frame) {
  const {ctx,width,height} = fit($('waterfallCanvas')), left = 53, right = width-14, top = 0, bottom = height-24;
  ctx.clearRect(0,0,width,height);
  const bins = Math.max(2, Math.floor(axisRange(frame) / (frame.fs_hz / 1024)) + 1);
  const off = document.createElement('canvas'); off.width = bins; off.height = Math.max(1, waterfall.length);
  const oc = off.getContext('2d'), pixels = oc.createImageData(bins, off.height);
  for (let r = 0; r < waterfall.length; r++) for (let b = 0; b < bins; b++) {
    const rgb = color(waterfall[r][b]), index=(r*bins+b)*4;
    pixels.data[index]=rgb[0]; pixels.data[index+1]=rgb[1]; pixels.data[index+2]=rgb[2]; pixels.data[index+3]=255;
  }
  oc.putImageData(pixels,0,0); ctx.imageSmoothingEnabled=false; ctx.drawImage(off,left,top,right-left,bottom-top);
  ctx.fillStyle='#7991a6'; ctx.font='10px Consolas, monospace'; ctx.textAlign='center';
  for(let i=0;i<=5;i++){const hz=axisRange(frame)*i/5;ctx.fillText(hz>=1000?(hz/1000).toFixed(1)+'k':hz.toFixed(0),left+(right-left)*i/5,height-5);}
  ctx.textAlign='left'; ctx.fillText(waterfall.length+'帧',0,12);
}
function updateMetrics(frame, renderMs) {
  const peaks=frame.metrics.peaks, peak=peaks[0];
  $('peakFrequency').innerHTML=(peak?peak.frequency_hz.toFixed(2):'—')+'<small>Hz</small>';
  $('peakAmplitude').innerHTML=(peak?peak.dbfs.toFixed(2):'—')+'<small>dBFS</small>';
  $('peakEstimate').textContent=frame.metrics.max_nondc_dbfs < -50 ? '输入较弱 / 静音候选' : peak && peak.interpolated ? '插值估计 '+peak.estimated_frequency_hz.toFixed(2)+' Hz（辅助）' : '最大非直流频点';
  $('sampleRate').innerHTML=frame.fs_hz.toFixed(2)+'<small>Hz</small>';
  $('resolution').textContent='Δf = '+frame.metrics.bin_width_hz.toFixed(3)+' Hz · N = 1024';
  const localRate=drawCount>1 && lastDrawAt>firstDrawAt ? (drawCount-1)*1000/(lastDrawAt-firstDrawAt) : 0;
  $('actualRate').innerHTML=current.snapshot_frame_rate_hz.toFixed(2)+' / '+localRate.toFixed(2)+'<small>Hz</small>';
  $('rateLabel').textContent=frame.mode==='LIVE'?'实际采集 / 绘制':'实际回放 / 绘制';
  $('renderTiming').textContent=(frame.mode==='LIVE'?'采集 ':'回放读取 ')+(frame.capture_call_s*1000).toFixed(1)+' ms · 绘制 '+renderMs.toFixed(1)+' ms';
  $('version').textContent='0x'+frame.version.toString(16).toUpperCase();
  $('sequence').textContent=frame.frame_id+' / '+frame.sequence;
  $('plotSubtitle').textContent='PL_FFT · '+frame.mode+' · '+(frame.window_name==='hann'?'Hann':'矩形')+' · '+frame.fs_hz.toFixed(2)+' Hz';
  $('peakTable').replaceChildren();
  if(!peaks.length){const tr=document.createElement('tr');const td=document.createElement('td');td.colSpan=3;td.textContent='未检测到非零局部峰';tr.appendChild(td);$('peakTable').appendChild(tr);}
  for(const p of peaks){const tr=document.createElement('tr');for(const value of [p.bin,p.frequency_hz.toFixed(2),p.dbfs.toFixed(2)]){const td=document.createElement('td');td.textContent=value;tr.appendChild(td);}$('peakTable').appendChild(tr);}
  const quality=$('qualityStatus');quality.classList.toggle('fail',!frame.metrics.tone_checks_passed);
  quality.textContent=frame.metrics.tones.length ? (frame.metrics.tone_checks_passed?'测试音检查通过':'测试音检查失败，请核对实际播放') : current.settings && current.settings.scenario==='silence'?'模拟静音已记录；不要求频谱全零':'频谱观察 · 未启用测试音断言';
}
async function renderFrame(frame) {
  if(shownFrame && shownFrame.run_id!==frame.run_id){waterfall=[];cursorBin=null;drawCount=0;firstDrawAt=0;}
  shownFrame=frame; waterfall.push(frame.dbfs.slice()); if(waterfall.length>96)waterfall.shift();
  const started=performance.now();drawSpectrum(frame);drawWaterfall(frame);
  if(document.visibilityState==='visible')await new Promise(resolve=>requestAnimationFrame(resolve));
  const duration=performance.now()-started;lastRenderMs=duration;lastDrawAt=performance.now();if(!firstDrawAt)firstDrawAt=lastDrawAt;drawCount++;
  updateMetrics(frame,duration);
  await request('/api/render',{run_id:frame.run_id,viewer_id:viewerId,frame_id:frame.frame_id,render_ms:duration,visible:document.visibilityState==='visible'});
}
async function screenshot(download=false) {
  if(!shownFrame||screenshotBusy||(current.screenshot_count||0)>=8)return;
  screenshotBusy=true;buttons();
  try {
    const canvas=document.createElement('canvas');canvas.width=1200;canvas.height=720;const ctx=canvas.getContext('2d');
    ctx.fillStyle='#121b25';ctx.fillRect(0,0,1200,720);ctx.fillStyle='#e7eef5';ctx.font='22px Segoe UI';ctx.fillText('PYNQ-Z2 Spectrum Analyzer',30,38);
    ctx.font='14px Consolas';ctx.fillStyle='#9eb5c8';
    ctx.fillText('source=PL_FFT  mode='+shownFrame.mode+'  fs='+shownFrame.fs_hz.toFixed(4)+' Hz  N=1024  window='+shownFrame.window_name,30,67);
    ctx.fillText('run='+shownFrame.run_id+'  frame='+shownFrame.frame_id+'  sequence='+shownFrame.sequence+'  amplitude: dBFS / normalized, not voltage calibrated',30,91);
    ctx.drawImage($('spectrumCanvas'),20,110,1160,330);ctx.drawImage($('waterfallCanvas'),20,460,1160,210);
    ctx.font='13px Consolas';ctx.fillText('PL FFT v1.0 | snapshot acquisition with inter-frame gaps | original scaling restored once',30,700);
    const url=canvas.toDataURL('image/png');
    const result=await request('/api/screenshot',{run_id:shownFrame.run_id,frame_id:shownFrame.frame_id,png_base64:url.split(',')[1]});
    if(download){const a=document.createElement('a');a.href=url;a.download=shownFrame.run_id+'_'+result.file;a.click();}
  } finally {screenshotBusy=false;buttons();}
}
async function poll() {
  try {
    const status=await request('/api/status');current=status;setupCases(status);
    $('connectionDot').classList.remove('offline');$('connectionText').textContent='仪器已连接';
    $('modeBadge').textContent=status.mode==='LIVE'?'LIVE 实时采集':'REPLAY 离线回放';$('modeBadge').classList.toggle('replay',status.mode==='REPLAY');
    $('phaseBadge').textContent=({IDLE:'已停止',RUNNING:'运行中',CONFIGURING:'配置硬件',ERROR:'异常停止'})[status.phase]||status.phase;
    $('elapsed').textContent=status.elapsed_s.toFixed(1)+' s';$('runName').textContent=status.run_id||'尚无运行记录';
    const view=status.browser_viewers[viewerId];
    $('runStatus').textContent=status.phase==='CONFIGURING'?'正在配置 codec 并测量采样率…':status.frames+' 帧 · '+status.elapsed_s.toFixed(1)+' s'+(status.reason?' · '+status.reason:'')+(status.stop_verified===true?' · 已安全停止':'')+(view?' · 前台连续绘制 '+view.longest_visible_s.toFixed(1)+' s':'')+(status.completed_runs?' · 会话已保存 '+status.completed_runs+' 次运行':'');
    if(status.error)errorMessage(status.error); else if(savedError)errorMessage('');
    const key=status.latest?status.latest.run_id+':'+status.latest.frame_id:'';
    if(key&&key!==lastFrameKey){await renderFrame(status.latest);lastFrameKey=key;}
    else if(shownFrame&&shownFrame.run_id===status.run_id)updateMetrics(shownFrame,lastRenderMs);
    if(['IDLE','ERROR'].includes(status.phase)&&status.run_id&&status.frames>0&&autoSnapshotRun!==status.run_id){if(!(status.screenshot_count||0))await screenshot(false);autoSnapshotRun=status.run_id;}
    previousPhase=status.phase;buttons();
  } catch(error){$('connectionDot').classList.add('offline');$('connectionText').textContent='连接或绘制请求异常';errorMessage(error.message);}
  setTimeout(poll,100);
}
$('runForm').addEventListener('submit',async event=>{
  event.preventDefault();if(commandBusy)return;commandBusy=true;buttons();errorMessage('');
  try {await request('/api/start',{window:$('window').value,duration_s:Number($('duration').value),target_hz:Number($('targetHz').value),replay_case:$('replayCase').value,scenario:$('scenario').value});}
  catch(error){errorMessage(error.message);}finally{commandBusy=false;buttons();}
});
$('stopButton').addEventListener('click',async()=>{commandBusy=true;buttons();try{await request('/api/stop',{});}catch(error){errorMessage(error.message);}finally{commandBusy=false;buttons();}});
$('exportButton').addEventListener('click',async()=>{commandBusy=true;buttons();try{if(shownFrame)try{await screenshot(false);}catch(error){errorMessage('界面图未追加：'+error.message+'；仍可导出已有记录。');}const data=await request('/api/export-session',{});const a=document.createElement('a');a.href=data.url;a.download=data.file;a.click();}catch(error){errorMessage(error.message);}finally{commandBusy=false;buttons();}});
$('snapshotButton').addEventListener('click',()=>screenshot(true).catch(error=>errorMessage(error.message)));
$('replayCase').addEventListener('change',selectReplayWindow);
for(const id of ['maxFrequency','amplitudeUnit'])$(id).addEventListener('change',()=>{if(shownFrame){drawSpectrum(shownFrame);drawWaterfall(shownFrame);}});
$('spectrumCanvas').addEventListener('click',event=>{if(!shownFrame)return;const box=event.currentTarget.getBoundingClientRect();const fraction=Math.max(0,Math.min(1,(event.clientX-box.left-53)/(box.width-67)));cursorBin=Math.max(0,Math.min(512,Math.round(fraction*axisRange(shownFrame)/(shownFrame.fs_hz/1024))));drawSpectrum(shownFrame);});
$('spectrumCanvas').addEventListener('keydown',event=>{if(!shownFrame||!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();cursorBin=Math.max(0,Math.min(512,(cursorBin===null?21:cursorBin)+(event.key==='ArrowRight'?1:-1)));drawSpectrum(shownFrame);});
window.addEventListener('resize',()=>{if(shownFrame){drawSpectrum(shownFrame);drawWaterfall(shownFrame);}});
poll();

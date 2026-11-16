/* apps/web-server/app.js — 实现 2：网页客户端 + Python 编码服务
 *
 * 分工：**编码全在服务端**（/api/encode 返回 base64 帧），本文件只做
 *       UI + 调 API + 用 MBLink 把帧写进蓝牙。没有本地编码器、没有 GBK 码表。
 */
'use strict';

const { $, createLogger, initTabs, setChip, setProgress, b64ToBytes, copyText, keepAwake } = window.MBUI;
const APP_VERSION = '2.0.0';

const log = createLogger($('#log'));
const link = window.MBLink.createLink({ log });

const state = { imageDataUrl: null, busy: false, version: '?' };

/* ------------------------------------------------------------------ API */
async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

/* --------------------------------------------------------------- 请求体 */
const textReq = () => ({
  kind: 'text',
  text: $('#text').value,
  fontSize: parseInt($('#font-size').value, 10),
  bold: $('#bold').checked,
  underline: $('#underline').checked,
  mode: $('#mode-text').value,
  invert: $('#invert-text').checked,
  format: 'gbk',
  darken: parseInt($('#darken-text').value, 10),
  feed: $('#feed').checked,
});

const imageReq = () => ({
  kind: 'image',
  dataUrl: state.imageDataUrl,
  mode: $('#mode-image').value,
  invert: $('#invert-image').checked,
  format: 'bmp',
  vflip: $('#vflip').checked,
  darken: parseInt($('#darken-image').value, 10),
  feed: $('#feed').checked,
});

/* --------------------------------------------------------------- 预览 */
async function preview(req) {
  const r = await fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  $('#preview').src = URL.createObjectURL(await r.blob());
}

/* --------------------------------------------------------------- 打印 */
function jobFromApi(j) {
  return { frames: j.frames.map(b64ToBytes), meta: j.meta };
}

async function printApi(path, req, label) {
  if (!link.connected) { log('先点「连接打印机」', 'warn'); return; }
  const j = await api(path, req);
  $('#meta').textContent = j.meta
    ? `${j.meta.format} · ${j.meta.bytes}B · ${j.meta.chunks}帧 · ${j.meta.width}×${j.meta.height}`
    : '';
  const chunk = parseInt($('#chunk').value, 10);
  await link.sendJob(jobFromApi(j), label, {
    chunk,
    preheat: $('#preheat').checked,
    onProgress: (r) => setProgress($('#bar'), r),
  });
}

/* --------------------------------------------------------------- 事件 */
initTabs();

$('#btn-connect').addEventListener('click', async () => {
  if (state.busy) return;
  state.busy = true;
  try {
    await link.connect();
    setChip($('#conn'), `已连接 ${link.state.device.name || link.state.device.id} · 写 ${link.state.writeChr.uuid.slice(4, 8)}`, 'ok');
    keepAwake(true);
  } catch (e) {
    log('连接失败：' + (e.message || e), 'err');
    setChip($('#conn'), '未连接', 'err');
    try {
      const lines = await link.dumpGatt();
      if (lines.length) { $('#gatt-out').textContent = lines.join('\n'); log('已输出 GATT 表到调试页', 'warn'); }
    } catch (e2) { /* ignore */ }
  } finally {
    state.busy = false;
  }
});

$('#font-size').addEventListener('input', (e) => { $('#font-size-val').textContent = e.target.value; });

$('#file').addEventListener('change', (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    state.imageDataUrl = rd.result;
    $('#preview').src = state.imageDataUrl;
    log(`已载入图片 ${(f.size / 1024).toFixed(0)}KB`);
  };
  rd.readAsDataURL(f);
});

$('#btn-preview-text').addEventListener('click', () => preview(textReq()).then(() => log('预览已更新')).catch((e) => log('预览失败：' + (e.message || e), 'err')));
$('#btn-print-text').addEventListener('click', () => printApi('/api/encode', textReq(), '文字打印').catch((e) => log('文字打印失败：' + (e.message || e), 'err')));

$('#btn-preview-image').addEventListener('click', () => {
  if (!state.imageDataUrl) { log('先选一张图片', 'warn'); return; }
  preview(imageReq()).then(() => log('预览已更新')).catch((e) => log('预览失败：' + (e.message || e), 'err'));
});
$('#btn-print-image').addEventListener('click', () => {
  if (!state.imageDataUrl) { log('先选一张图片', 'warn'); return; }
  printApi('/api/encode', imageReq(), '图片打印').catch((e) => log('图片打印失败：' + (e.message || e), 'err'));
});

$('#btn-calib').addEventListener('click', () => {
  printApi('/api/calibration', { format: 'bmp', feed: true }, '校准图')
    .then(() => log('若上下颠倒 → 勾「垂直翻转」；全白 → 查电量/纸面；断行 → 分片改 20B', 'warn'))
    .catch((e) => log('校准图失败：' + (e.message || e), 'err'));
});

$('#btn-sizeprobe').addEventListener('click', () => {
  printApi('/api/size-probe', {}, '字号档位测试')
    .then(() => log('看纸面：四行「档位 tier=N」一样大 → 固件忽略字号档位', 'warn'))
    .catch((e) => log('档位测试失败：' + (e.message || e), 'err'));
});

$('#btn-device').addEventListener('click', async () => {
  if (!link.connected) { log('先连接', 'warn'); return; }
  try {
    const infos = await link.readDeviceInfo(1500);
    if (!infos.length) {
      log('设备没有回包 —— 可能被官方 App 占着，或固件不回应 cmd 0x01', 'warn');
      return;
    }
    const f = infos[infos.length - 1];
    $('#dev-out').textContent = window.MBBle.formatStatus(f).join('\n');
    const pick = (tag) => { const x = f.fields.find((y) => y.tag === tag); return x ? x.int : '?'; };
    log(`设备信息：序列号 ${f.serial || '?'} · 0x01=${pick(0x01)} · 灯=${pick(0x03)} · 0x02=${pick(0x02)}`, 'ok');
  } catch (e) { log('读设备信息失败：' + (e.message || e), 'err'); }
});

$('#btn-led-on').addEventListener('click', () => toggleLed(true));
$('#btn-led-off').addEventListener('click', () => toggleLed(false));

async function toggleLed(on) {
  if (!link.connected) { log('先连接', 'warn'); return; }
  try {
    const state = await link.setLed(on);
    if (state === null) log(on ? '已发开灯（状态没读回来）' : '已发关灯（状态没读回来）', 'warn');
    else log(`指示灯 = ${state}（${state ? '亮' : '灭'}）`, state === (on ? 1 : 0) ? 'ok' : 'warn');
  } catch (e) { log('灯操作失败：' + (e.message || e), 'err'); }
}

$('#btn-gatt').addEventListener('click', async () => {
  if (!link.connected) { log('先连接', 'warn'); return; }
  try {
    const lines = await link.dumpGatt();
    $('#gatt-out').textContent = lines.join('\n');
    log('GATT 表已输出（可复制发我）', 'ok');
  } catch (e) { log('探测失败：' + (e.message || e), 'err'); }
});

$('#btn-status').addEventListener('click', async () => {
  if (!link.connected) { log('先连接', 'warn'); return; }
  try {
    const chunk = parseInt($('#chunk').value, 10);
    await link.writeAll(Uint8Array.from([0xaa, 0x01, 0x00, 0x01, 0x54]), '状态查询', chunk);
    log('已发状态查询，等 notify 回包', 'warn');
  } catch (e) { log('状态查询失败：' + (e.message || e), 'err'); }
});

$('#btn-clear').addEventListener('click', () => { $('#log').innerHTML = ''; });
$('#btn-copy').addEventListener('click', async () => {
  const ok = await copyText($('#log').innerText);
  log(ok ? '日志已复制' : '复制失败，手动长按选择吧', ok ? 'ok' : 'warn');
});

/* --------------------------------------------------------------- 启动 */
(async function init() {
  if (!navigator.bluetooth) {
    log('这个浏览器不支持 Web Bluetooth —— 用 Android 版 Chrome / Edge', 'err');
    $('#btn-connect').disabled = true;
  }
  if (!window.isSecureContext) log('当前不是安全上下文：必须用 http://127.0.0.1 或 https 打开', 'err');

  try {
    const h = await (await fetch('/api/health')).json();
    state.version = h.version;
    document.querySelector('#mode').textContent = `编码服务 v${h.version} · 页面 v${APP_VERSION}`;
    document.getElementById('health').textContent = `PIL ${h.pil ? 'ok' : '缺失'}`;
    log(`编码服务就绪（v${h.version}，PIL ${h.pil ? 'ok' : '缺失'}）`, 'ok');
    if (!h.pil) log('服务端缺 Pillow：apt install python3-pil', 'err');
  } catch (e) {
    document.querySelector('#mode').textContent = '编码服务不可达';
    log('连不上 /api/health —— 确认 serve.py 在跑，且页面是从它这里打开的', 'err');
  }
  log('先「连接打印机」再打印', 'ok');
})();

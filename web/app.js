/* app.js — 双模式控制台
 *
 *  服务端模式：页面由 phone/serve.py 提供 → 编码在 Python 里做（Pillow，质量最好）
 *  浏览器模式：纯静态托管（如 GitHub Pages）→ 编码在浏览器里做（encoder.js + canvas）
 *
 * BLE 部分两种模式完全一样，都走 Web Bluetooth。
 */
'use strict';

// BLE 选特征值 / 回包解析都在 web/ble-util.js（有单元测试，兼容新旧 Chrome）
const BLE = window.MBBle;
const { SVC_FF00, CHR_WRITE, CHR_NOTIFY } = BLE;

const $ = (s) => document.querySelector(s);
const logEl = $('#log');

/** 页面版本：改代码时顺手加一，方便确认手机上加载的是新版 */
const APP_VERSION = '1.5.0';

const state = {
  backend: 'unknown',      // 'server' | 'client'
  device: null,
  server: null,
  writeChr: null,
  notifyChr: null,
  busy: false,
  imageDataUrl: null,
  imageEl: null,
  gbkLoading: null,
};

/* ------------------------------------------------------------------ 工具 */
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function log(msg, cls = '') {
  const line = document.createElement('div');
  if (cls) line.className = cls;
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
  if (logEl.childElementCount > 400) logEl.removeChild(logEl.firstChild);
}

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

const hex = (bytes, max = 24) => {
  const a = Array.from(bytes.slice(0, max), (b) => b.toString(16).padStart(2, '0')).join(' ');
  return bytes.length > max ? a + ' …' : a;
};

function setMode(text, cls = '') {
  const el = $('#mode');
  if (el) { el.textContent = text; el.className = cls; }
}

/* ------------------------------------------------------- 报文解析（仅日志） */
function describeFrame(bytes) {
  const f = BLE.parseFrame(bytes);
  if (!f) return '';
  const tlvs = f.tlvs.map((t) => {
    const dec = t.len === 1 ? `(${t.value[0]})` : '';
    return `tag=0x${t.tag.toString(16)} len=${t.len} ${hex(t.value, 12)}${dec}`;
  });
  return ` | cmd=0x${f.cmd.toString(16)}${f.sumOk ? '' : ' (校验和错误!)'} ${tlvs.join(' ; ')}`;
}

/* ------------------------------------------------------------ 后端探测 */
async function detectBackend() {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 2500);
  try {
    const r = await fetch('/api/health', { cache: 'no-store', signal: ctrl.signal });
    if (r.ok) {
      const j = await r.json();
      if (j && j.ok) {
        state.backend = 'server';
        return j;
      }
    }
  } catch (e) { /* 没有服务端 —— 走浏览器模式 */ }
  finally { clearTimeout(timer); }
  state.backend = 'client';
  return null;
}

async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

/* --------------------------------------------------- GBK 码表（按需加载） */
function ensureGbk() {
  if (window.GBK) return Promise.resolve(window.GBK);
  if (state.gbkLoading) return state.gbkLoading;
  state.gbkLoading = new Promise((resolve) => {
    const s = document.createElement('script');
    s.src = 'gbk.js';
    s.onload = () => {
      log(`GBK 码表就绪（${window.GBK ? window.GBK.valid : '?'} 个码位）`);
      resolve(window.GBK || null);
    };
    s.onerror = () => {
      log('GBK 码表加载失败 → 文字将转成位图（慢一些）', 'warn');
      resolve(null);
    };
    document.head.appendChild(s);
  });
  return state.gbkLoading;
}

/* -------------------------------------------------------- 编码（双模式） */
async function encodeRequest(req) {
  if (state.backend === 'server') {
    const j = await api('/api/encode', req);
    return { frames: j.frames.map(b64ToBytes), meta: j.meta, source: 'server' };
  }
  return encodeClient(req);
}

async function encodeClient(req) {
  const E = window.MBEncoder;
  const R = window.MBRender;
  if (!E || !R) throw new Error('编码器未加载（encoder.js / render.js 缺失）');

  const mode = req.mode || 'threshold';
  const format = req.format === 'raw' ? 'raw' : 'bmp';
  const darken = Math.max(0, Math.min(3, parseInt(req.darken, 10) || 0));

  // 文字 + GBK 帧：最快路径（字号走固件档位 tag 0x10）
  // 但浓度（阈值/膨化）改不了固件渲染的文本，所以选了浓度就自动走位图
  if (req.kind !== 'image' && (req.format || 'gbk') === 'gbk' && darken === 0) {
    const gbk = await ensureGbk();
    if (gbk) {
      const job = E.jobFromText(req.text || '', gbk.encode, {
        bold: req.bold,
        underline: req.underline,
        fontSize: sizeTier(req.fontSize),
      });
      if (job) {
        if (req.feed) job.frames = job.frames.concat(E.feedJob(3).frames);
        return { ...job, source: 'client' };
      }
      log('文本含 GBK 无法表示的字符 → 自动转位图', 'warn');
    }
  }

  // 文本/图片 → 灰度 → 抖动 → 位图任务
  let grayed;
  if (req.kind === 'image') {
    if (!state.imageEl) {
      state.imageEl = await loadImage(req.dataUrl || state.imageDataUrl);
    }
    grayed = await R.imageToGray(state.imageEl);
  } else {
    grayed = R.textToGray(req.text || '', req);
  }

  let gray = grayed.gray;
  if (req.invert) {
    for (let i = 0; i < gray.length; i++) gray[i] = 255 - gray[i];
  }

  if (darken > 0 && (req.format || 'gbk') === 'gbk') {
    log(`浓度档位 ${darken} 需要位图编码（GBK 文本由固件渲染，改不了深浅）`, 'warn');
  }

  const d = E.ditherToRaw(gray, grayed.w, grayed.h, mode === 'none' ? 'threshold' : mode, null, darken);
  const job = E.jobFromRaw(d.raw, d.w, d.h, format, { official: true, topDown: !req.vflip });
  if (req.feed) job.frames = job.frames.concat(E.feedJob(3).frames);
  return { ...job, source: 'client', raw: d.raw };
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('图片解码失败'));
    img.src = src;
  });
}

/* ------------------------------------------------------------------ 预览 */
async function previewRequest(req) {
  if (state.backend === 'server') {
    const r = await fetch('/api/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    $('#preview').src = URL.createObjectURL(await r.blob());
    return;
  }
  const job = await encodeClient({ ...req, format: 'raw' });
  $('#preview').src = window.MBRender.rawToDataURL(job.meta.width, job.meta.height, job.raw, 2);
}

/* ------------------------------------------------------------ BLE 连接 */
/** 取服务列表；若 getPrimaryServices() 没覆盖到已知服务，逐个补问一次 */
async function servicesWithFallback(server) {
  let services = [];
  try { services = await server.getPrimaryServices(); } catch { services = []; }
  const have = new Set(services.map((s) => String(s.uuid).toLowerCase()));
  for (const uuid of BLE.OPTIONAL_SERVICES) {
    if (have.has(String(uuid).toLowerCase())) continue;
    try {
      const s = await server.getPrimaryService(uuid);
      if (s) services.push(s);
    } catch { /* 该服务不存在，正常 */ }
  }
  return services;
}

async function dumpGatt() {
  if (!state.server) return [];
  const services = await servicesWithFallback(state.server);
  const lines = await BLE.dumpGatt(services);
  const out = $('#gatt-out');
  if (out) out.textContent = lines.join('\n');
  return lines;
}

async function connect() {
  if (state.busy) return false;
  state.busy = true;
  try {
    log('请求蓝牙设备…（在弹窗里选打印机）');
    state.device = await navigator.bluetooth.requestDevice({
      acceptAllDevices: true,
      optionalServices: BLE.OPTIONAL_SERVICES,
    });
    log(`选中：${state.device.name || '(无名)'}`, 'ok');

    state.device.addEventListener('gattserverdisconnected', () => {
      $('#conn').textContent = `已断开（${state.device.name || state.device.id}）`;
      $('#conn').className = 'conn err';
      log('设备断开', 'warn');
      state.writeChr = null;
    });

    state.server = await state.device.gatt.connect();
    const services = await servicesWithFallback(state.server);
    const { write, notify, all, reason } = await BLE.pickWrite(services);
    log(`读到 ${services.length} 个服务 / ${all.length} 个特征值`);

    const manual = $('#write-uuid').value.trim();
    if (manual) {
      const s = await state.server.getPrimaryService(SVC_FF00).catch(() => null);
      state.writeChr = s ? await s.getCharacteristic(manual).catch(() => write) : write;
    } else {
      state.writeChr = write;
    }
    state.notifyChr = notify;

    if (!state.writeChr) throw new Error(reason || '没找到可写特征值 —— 点「探测 GATT」把结果发我');
    log(`写入特征值：${state.writeChr.uuid}`, 'ok');

    if (state.notifyChr) {
      try {
        await state.notifyChr.startNotifications();
        state.notifyChr.addEventListener('characteristicvaluechanged', (e) => {
          const v = new Uint8Array(e.target.value.buffer);
          log(`notify ${v.length}B ${hex(v)}${describeFrame(v)}`, 'hex');
        });
        log(`通知特征值：${state.notifyChr.uuid}`, 'ok');
      } catch (e) {
        log('订阅通知失败（不影响打印）：' + e.message, 'warn');
      }
    }

    $('#conn').textContent = `已连接 ${state.device.name || state.device.id} · 写 ${state.writeChr.uuid.slice(4, 8)}`;
    $('#conn').className = 'conn ok';
    return true;
  } catch (e) {
    log('连接失败：' + (e.message || e), 'err');
    $('#conn').textContent = '未连接';
    $('#conn').className = 'conn err';
    try { await dumpGatt(); log('已自动输出 GATT 表到「调试」页', 'warn'); } catch { /* ignore */ }
    return false;
  } finally {
    state.busy = false;
  }
}

/* ------------------------------------------------------------------ 写入 */
async function writeAll(bytes, label = '') {
  const chunk = parseInt($('#chunk').value, 10);
  const total = bytes.length;
  let sent = 0;
  const bar = $('#bar');
  const t0 = performance.now();

  for (let i = 0; i < total; i += chunk) {
    const part = bytes.subarray(i, Math.min(i + chunk, total));
    try {
      if (state.writeChr.properties.writeWithoutResponse) {
        await state.writeChr.writeValueWithoutResponse(part);
      } else {
        await state.writeChr.writeValue(part);
      }
    } catch (e) {
      try {
        await state.writeChr.writeValue(part);
      } catch (e2) {
        throw new Error(`写入失败 @${i}/${total}: ${e2.message || e2}`);
      }
    }
    sent += part.length;
    bar.style.width = ((sent / total) * 100).toFixed(1) + '%';
    if (chunk <= 20 && (i / chunk) % 8 === 0) await sleep(4);
  }
  log(`${label} 完成 ${total}B / ${Math.ceil(total / chunk)} 片，${(performance.now() - t0).toFixed(0)}ms`, 'ok');
}

async function sendJob(job, label) {
  if (!state.writeChr) throw new Error('还没连接打印机');
  if (job.meta && job.meta.preheat && $('#preheat').checked) {
    log(`预热 ${job.meta.preheat}B`);
    await writeAll(new Uint8Array(job.meta.preheat), '预热');
    await sleep(120);
  }
  const frames = job.frames;
  log(`共 ${frames.length} 帧 / ${job.meta ? job.meta.bytes : '?'}B（${job.meta ? job.meta.format : ''}${
    job.source ? ' · ' + (job.source === 'server' ? 'Python 编码' : '浏览器编码') : ''}）`);
  for (let i = 0; i < frames.length; i++) {
    await writeAll(frames[i], `帧 ${i + 1}/${frames.length}`);
    await sleep(30);
  }
  log(`${label} 已全部发送`, 'ok');
}

/* -------------------------------------------------------------- 请求构造 */
/** 像素字号 → 固件字号档位（tag 0x10）：≤26→0 普通 / ≤36→1 大 / 更大→2 */
function sizeTier(px) {
  const v = parseInt(px, 10) || 26;
  if (v <= 26) return 0;
  if (v <= 36) return 1;
  return 2;
}

const textReq = () => ({
  kind: 'text',
  text: $('#text').value,
  fontSize: parseInt($('#font-size').value, 10),
  bold: !!($('#bold') && $('#bold').checked),
  underline: !!($('#underline') && $('#underline').checked),
  mode: $('#mode-text').value,
  invert: $('#invert-text').checked,
  format: $('#fmt-text').value,
  darken: parseInt(($('#darken-text') || {}).value || '0', 10),
  feed: !!($('#feed') && $('#feed').checked),
});

const imageReq = () => ({
  kind: 'image',
  dataUrl: state.imageDataUrl,
  mode: $('#mode-image').value,
  invert: $('#invert-image').checked,
  format: $('#fmt-image').value,
  vflip: $('#vflip').checked,
  darken: parseInt(($('#darken-image') || {}).value || '0', 10),
  feed: !!($('#feed') && $('#feed').checked),
});

async function runPreview(req) {
  try {
    await previewRequest(req);
    log('预览已更新');
  } catch (e) { log('预览失败：' + (e.message || e), 'err'); }
}

async function runPrint(req, label) {
  try {
    if (!state.writeChr) { log('先点「连接打印机」', 'warn'); return; }
    const job = await encodeRequest(req);
    $('#meta').textContent = `${job.meta.format} · ${job.meta.bytes}B · ${job.meta.chunks}帧 · ${job.meta.width}×${job.meta.height}`;
    await sendJob(job, label);
  } catch (e) {
    log(label + ' 失败：' + (e.message || e), 'err');
  }
}

/* ------------------------------------------------------------------ 事件 */
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
  document.querySelectorAll('.pane').forEach((x) => x.classList.remove('active'));
  t.classList.add('active');
  $('#pane-' + t.dataset.tab).classList.add('active');
}));

$('#btn-connect').addEventListener('click', connect);
$('#font-size').addEventListener('input', (e) => { $('#font-size-val').textContent = e.target.value; });

$('#file').addEventListener('change', (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    state.imageDataUrl = rd.result;
    state.imageEl = null;
    $('#preview').src = state.imageDataUrl;
    log(`已载入图片 ${(f.size / 1024).toFixed(0)}KB`);
  };
  rd.readAsDataURL(f);
});

$('#btn-preview-text').addEventListener('click', () => runPreview(textReq()));
$('#btn-print-text').addEventListener('click', () => runPrint(textReq(), '文字打印'));

$('#btn-preview-image').addEventListener('click', () => {
  if (!state.imageDataUrl) { log('先选一张图片', 'warn'); return; }
  runPreview(imageReq());
});
$('#btn-print-image').addEventListener('click', () => {
  if (!state.imageDataUrl) { log('先选一张图片', 'warn'); return; }
  runPrint(imageReq(), '图片打印');
});

$('#btn-calib').addEventListener('click', async () => {
  try {
    if (!state.writeChr) { log('先点「连接打印机」', 'warn'); return; }
    let job;
    if (state.backend === 'server') {
      job = await api('/api/calibration', { format: 'bmp', vflip: $('#vflip').checked, feed: true });
      job = { frames: job.frames.map(b64ToBytes), meta: job.meta, source: 'server' };
    } else {
      const E = window.MBEncoder;
      const R = window.MBRender;
      const g = R.calibrationGray();
      const d = E.ditherToRaw(g.gray, g.w, g.h, 'threshold', 128);
      job = {
        ...E.jobFromRaw(d.raw, d.w, d.h, 'bmp', { official: true, topDown: !$('#vflip').checked }),
        source: 'client', raw: d.raw,
      };
      job.frames = job.frames.concat(E.feedJob(3).frames);
      $('#preview').src = R.rawToDataURL(d.w, d.h, d.raw, 2);
    }
    $('#meta').textContent = `${job.meta.format} · ${job.meta.bytes}B · ${job.meta.chunks}帧 · ${job.meta.width}×${job.meta.height}`;
    await sendJob(job, '校准图');
    log('若上下颠倒 → 勾「垂直翻转」；全白 → 先查电量/纸面，再试浓度 2；断行 → 分片改 20B', 'warn');
  } catch (e) { log('校准图失败：' + (e.message || e), 'err'); }
});

$('#btn-sizeprobe').addEventListener('click', async () => {
  try {
    if (!state.writeChr) { log('先点「连接打印机」', 'warn'); return; }
    let frames;
    if (state.backend === 'server') {
      const j = await api('/api/size-probe', {});
      frames = j.frames.map(b64ToBytes);
    } else {
      const E = window.MBEncoder;
      const R = window.MBRender;
      const gbk = await ensureGbk();
      frames = [];
      if (gbk) {
        for (let tier = 0; tier < 4; tier++) {
          const job = E.jobFromText(`档位 tier=${tier}\n`, gbk.encode, { fontSize: tier });
          frames = frames.concat(job.frames);
        }
      } else {
        log('GBK 码表没加载，无法做档位测试', 'err');
        return;
      }
      const g = R.textToGray('位图 40px 对照', { fontSize: 40 });
      const d = E.ditherToRaw(g.gray, g.w, g.h, 'threshold', null, 0);
      frames = frames.concat(E.jobFromRaw(d.raw, d.w, d.h, 'bmp', { official: true }).frames);
      frames = frames.concat(E.feedJob(3).frames);
    }
    await sendJob({ frames, meta: { format: 'probe', bytes: frames.reduce((a, f) => a + f.length, 0), chunks: frames.length, preheat: 2048 }, source: state.backend }, '字号档位测试');
    log('看纸面：四行「档位 tier=N」如果一样大 → 固件忽略 tag 0x10；若变大 → 档位有效', 'warn');
  } catch (e) { log('档位测试失败：' + (e.message || e), 'err'); }
});

$('#btn-gatt').addEventListener('click', async () => {
  if (!state.server) { log('先连接', 'warn'); return; }
  try {
    await dumpGatt();
    log('GATT 表已输出（可复制发我）', 'ok');
  } catch (e) { log('探测失败：' + (e.message || e), 'err'); }
});

$('#btn-status').addEventListener('click', async () => {
  if (!state.writeChr) { log('先连接', 'warn'); return; }
  try {
    const frame = window.MBEncoder ? window.MBEncoder.statusFrame()
      : new Uint8Array([0xaa, 0x01, 0x00, 0x01, 0x54]);
    await writeAll(frame, '状态查询');
    log('已发状态查询，等 notify 回包（没反应说明该机型不支持）', 'warn');
  } catch (e) { log('状态查询失败：' + (e.message || e), 'err'); }
});

$('#btn-clear').addEventListener('click', () => { logEl.innerHTML = ''; });
$('#btn-copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(logEl.innerText);
    log('日志已复制', 'ok');
  } catch { log('复制失败，手动长按选择吧', 'warn'); }
});

/* ------------------------------------------------------------------ 启动 */
(async function init() {
  if (!navigator.bluetooth) {
    log('这个浏览器不支持 Web Bluetooth —— 请用 Android 版 Chrome / Edge', 'err');
    $('#btn-connect').disabled = true;
  }
  if (!window.isSecureContext) {
    log('当前不是安全上下文：请用 https:// 或 http://127.0.0.1 打开', 'err');
  }

  const health = await detectBackend();
  const healthEl = $('#health');
  if (healthEl) healthEl.textContent = `页面 v${APP_VERSION}`;

  if (state.backend === 'server') {
    setMode(`编码：Python 服务端 v${health.version}`, 'ok');
    log(`服务端就绪（v${health.version}，PIL ${health.pil ? 'ok' : '缺失'}）`, 'ok');
    if (!health.pil) log('服务端缺 Pillow：apt install python3-pil', 'err');
  } else {
    setMode('编码：浏览器本地（纯静态）', 'ok');
    log(`没有检测到 Python 服务端 → 切到浏览器本地编码（纯静态模式，页面 v${APP_VERSION}）`, 'warn');
    if (!window.MBEncoder || !window.MBRender) {
      log('本地编码器缺失：encoder.js / render.js 没加载', 'err');
    }
    // 静态模式：预热加载 GBK 表，第一次打印就不用等
    if ((($('#fmt-text') || {}).value || 'gbk') === 'gbk') ensureGbk();
  }
  log('先「连接打印机」再打印', 'ok');
})();

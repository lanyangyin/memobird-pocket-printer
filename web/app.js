/* app.js — 手机端控制台
 * 分工：Python(serve.py) 负责渲染/抖动/BMP/帧封装；本文件只负责 Web Bluetooth 传输。
 */
'use strict';

const SVC_FF00 = 0xff00;
const CHR_WRITE = '0000ff02-0000-1000-8000-00805f9b34fb';
const CHR_NOTIFY = '0000ff01-0000-1000-8000-00805f9b34fb';
const SVC_ISSC = '49535343-fe7d-4ae5-8fa9-9fafd205e455';
const CHR_ISSC_W = '49535343-8841-43f4-a8d4-ecbe34729bb3';
const CHR_ISSC_N = '49535343-1e4d-4bd9-ba61-23c647249616';

const $ = (s) => document.querySelector(s);
const logEl = $('#log');
let device = null, server = null, writeChr = null, notifyChr = null, busy = false;
let imageDataUrl = null;

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

/* --------------------------------------------------------------- 协议解析（仅用于日志） */
function parseFrame(bytes) {
  if (bytes.length < 5 || bytes[0] !== 0xaa) return null;
  const len = bytes[1] | (bytes[2] << 8);
  if (bytes.length < 3 + len + 1) return null;
  const cmd = bytes[3];
  const payload = bytes.slice(4, 3 + len);
  const tlvs = [];
  for (let i = 0; i + 3 <= payload.length; ) {
    const tag = payload[i];
    const l = payload[i + 1] | (payload[i + 2] << 8);
    const v = payload.slice(i + 3, i + 3 + l);
    tlvs.push(`tag=0x${tag.toString(16)} len=${l} ${hex(v, 12)}`);
    i += 3 + l;
  }
  return { cmd, len, tlvs };
}

/* ------------------------------------------------------------------ 连接 */
function pickWrite(services) {
  const all = [];
  for (const s of services) for (const c of s.characteristics) all.push({ svc: s, chr: c });

  const byUuid = (u) => all.find((x) => x.chr.uuid.toLowerCase().startsWith(u));
  let pick = byUuid(CHR_WRITE);
  if (!pick) pick = byUuid(CHR_ISSC_W);
  if (!pick) pick = all.find((x) => x.chr.properties.write || x.chr.properties.writeWithoutResponse);

  let note = byUuid(CHR_NOTIFY) || byUuid(CHR_ISSC_N)
    || all.find((x) => x.chr.properties.notify || x.chr.properties.indicate);
  return { write: pick && pick.chr, notify: note && note.chr, table: all };
}

async function connect() {
  if (busy) return;
  busy = true;
  try {
    log('请求蓝牙设备…（在弹窗里选打印机）');
    device = await navigator.bluetooth.requestDevice({
      acceptAllDevices: true,
      optionalServices: [SVC_FF00, 0xff80, 0xfee7, SVC_ISSC, 0x180a],
    });
    log(`选中：${device.name || '(无名)'} ${device.id}`, 'ok');

    device.addEventListener('gattserverdisconnected', () => {
      $('#conn').textContent = '已断开（' + (device.name || device.id) + '）';
      $('#conn').className = 'conn err';
      log('设备断开', 'warn');
      writeChr = null;
    });

    server = await device.gatt.connect();
    const services = await server.getPrimaryServices();
    const { write, notify, table } = pickWrite(services);

    const manual = $('#write-uuid').value.trim();
    if (manual) {
      const s = await server.getPrimaryService(SVC_FF00).catch(() => null);
      writeChr = s ? await s.getCharacteristic(manual).catch(() => write) : write;
    } else {
      writeChr = write;
    }
    notifyChr = notify;

    if (!writeChr) throw new Error('没找到可写特征值 —— 点「探测 GATT」把结果发我');
    log(`写入特征值：${writeChr.uuid}`, 'ok');
    if (notifyChr) {
      try {
        await notifyChr.startNotifications();
        notifyChr.addEventListener('characteristicvaluechanged', (e) => {
          const v = new Uint8Array(e.target.value.buffer);
          const f = parseFrame(v);
          log(`notify ${v.length}B ${hex(v)}${f ? ` | cmd=0x${f.cmd.toString(16)} ${f.tlvs.join(' ; ')}` : ''}`, 'hex');
        });
        log(`通知特征值：${notifyChr.uuid}`, 'ok');
      } catch (e) {
        log('订阅通知失败（不影响打印）：' + e.message, 'warn');
      }
    }

    $('#conn').textContent = `已连接 ${device.name || device.id} · 写 ${writeChr.uuid.slice(4, 8)}`;
    $('#conn').className = 'conn ok';
    return true;
  } catch (e) {
    log('连接失败：' + (e.message || e), 'err');
    $('#conn').textContent = '未连接';
    $('#conn').className = 'conn err';
    // 失败时自动把 GATT 表打出来，方便定位特征值
    if (server) {
      try {
        const services = await server.getPrimaryServices();
        const lines = [];
        for (const s of services) {
          lines.push(`service ${s.uuid}`);
          for (const c of await s.getCharacteristics()) {
            const props = Object.entries(c.properties).filter(([, v]) => v).map(([k]) => k).join(',');
            lines.push(`   chr ${c.uuid}  [${props}]`);
          }
        }
        $('#gatt-out').textContent = lines.join('\n');
        log('已自动输出 GATT 表到「调试」页', 'warn');
      } catch { /* 忽略 */ }
    }
    return false;
  } finally {
    busy = false;
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
      if (writeChr.properties.writeWithoutResponse) {
        await writeChr.writeValueWithoutResponse(part);
      } else {
        await writeChr.writeValue(part);
      }
    } catch (e) {
      try {
        await writeChr.writeValue(part);
      } catch (e2) {
        throw new Error(`写入失败 @${i}/${total}: ${e2.message || e2}`);
      }
    }
    sent += part.length;
    bar.style.width = ((sent / total) * 100).toFixed(1) + '%';
    if (chunk <= 20 && (i / chunk) % 8 === 0) await sleep(4);   // 小分片时给协议栈一点空隙
  }
  const ms = performance.now() - t0;
  bar.style.width = '100%';
  log(`${label} 完成 ${total}B / ${Math.ceil(total / chunk)} 片，${ms.toFixed(0)}ms`, 'ok');
}

async function sendJob(job, label) {
  if (!writeChr) throw new Error('还没连接打印机');
  if (job.meta && job.meta.preheat && $('#preheat').checked) {
    log(`预热 ${job.meta.preheat}B`);
    await writeAll(new Uint8Array(job.meta.preheat), '预热');
    await sleep(120);
  }
  const frames = job.frames.map(b64ToBytes);
  log(`共 ${frames.length} 帧 / ${job.meta ? job.meta.bytes : '?'}B（${job.meta ? job.meta.format : ''}）`);
  for (let i = 0; i < frames.length; i++) {
    await writeAll(frames[i], `帧 ${i + 1}/${frames.length}`);
    await sleep(30);   // 连发但别把缓冲写爆
  }
  log(`${label} 已全部发送`, 'ok');
}

/* ------------------------------------------------------------------ API */
async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
  return r.json();
}

async function preview(body) {
  const r = await fetch('/api/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const blob = await r.blob();
  $('#preview').src = URL.createObjectURL(blob);
}

function textReq() {
  return {
    kind: 'text',
    text: $('#text').value,
    fontSize: parseInt($('#font-size').value, 10),
    mode: $('#mode-text').value,
    invert: $('#invert-text').checked,
    format: $('#fmt-text').value,
  };
}

function imageReq() {
  return {
    kind: 'image',
    dataUrl: imageDataUrl,
    mode: $('#mode-image').value,
    invert: $('#invert-image').checked,
    format: $('#fmt-image').value,
    vflip: $('#vflip').checked,
  };
}

async function runPreview(req) {
  try {
    await preview(req);
    log('预览已更新');
  } catch (e) { log('预览失败：' + e.message, 'err'); }
}

async function runPrint(req, label) {
  try {
    if (!writeChr) { log('先点「连接打印机」', 'warn'); return; }
    const job = await api('/api/encode', req);
    $('#meta').textContent = `${job.meta.format} · ${job.meta.bytes}B · ${job.meta.chunks}帧 · ${job.meta.width}×${job.meta.height}`;
    await sendJob(job, label);
  } catch (e) {
    log(label + ' 失败：' + (e.message || e), 'err');
  }
}

/* ------------------------------------------------------------------ 事件 */
document.querySelectorAll('.tab').forEach((t) =>
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    document.querySelectorAll('.pane').forEach((x) => x.classList.remove('active'));
    t.classList.add('active');
    $('#pane-' + t.dataset.tab).classList.add('active');
  })
);

$('#btn-connect').addEventListener('click', connect);

$('#font-size').addEventListener('input', (e) => { $('#font-size-val').textContent = e.target.value; });

$('#file').addEventListener('change', (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    imageDataUrl = rd.result;
    $('#preview').src = imageDataUrl;
    log(`已载入图片 ${(f.size / 1024).toFixed(0)}KB`);
  };
  rd.readAsDataURL(f);
});

$('#btn-preview-text').addEventListener('click', () => runPreview(textReq()));
$('#btn-print-text').addEventListener('click', () => runPrint(textReq(), '文字打印'));

$('#btn-preview-image').addEventListener('click', () => {
  if (!imageDataUrl) { log('先选一张图片', 'warn'); return; }
  runPreview(imageReq());
});
$('#btn-print-image').addEventListener('click', () => {
  if (!imageDataUrl) { log('先选一张图片', 'warn'); return; }
  runPrint(imageReq(), '图片打印');
});

$('#btn-calib').addEventListener('click', async () => {
  try {
    if (!writeChr) { log('先点「连接打印机」', 'warn'); return; }
    const job = await api('/api/calibration', { format: 'bmp', vflip: $('#vflip').checked });
    runPreview({ kind: 'text', text: '校准图预览见下', fontSize: 18, mode: 'threshold' });
    await sendJob(job, '校准图');
    log('如果出来的图上下颠倒 → 勾选「垂直翻转」再试；如果全白 → 换「裸位图帧」再试', 'warn');
  } catch (e) { log('校准图失败：' + (e.message || e), 'err'); }
});

$('#btn-gatt').addEventListener('click', async () => {
  const out = $('#gatt-out');
  out.textContent = '';
  if (!server) { out.textContent = '先连接'; return; }
  try {
    const services = await server.getPrimaryServices();
    const lines = [];
    for (const s of services) {
      lines.push(`service ${s.uuid}`);
      const chars = await s.getCharacteristics();
      for (const c of chars) {
        const props = Object.entries(c.properties).filter(([, v]) => v).map(([k]) => k).join(',');
        lines.push(`   chr ${c.uuid}  [${props}]`);
      }
    }
    out.textContent = lines.join('\n');
    log('GATT 表已输出（可复制发我）', 'ok');
  } catch (e) {
    out.textContent = '探测失败：' + e.message;
  }
});

$('#btn-status').addEventListener('click', async () => {
  if (!writeChr) { log('先连接', 'warn'); return; }
  try {
    await writeAll(new Uint8Array([0xaa, 0x01, 0x00, 0x01, 0x54]), '状态查询');
    log('已发状态查询，等 notify 回包（没反应说明该机型不支持）', 'warn');
  } catch (e) { log('状态查询失败：' + e.message, 'err'); }
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
    log('当前不是安全上下文：请用 http://127.0.0.1 或 localhost 打开', 'err');
  }
  try {
    const h = await (await fetch('/api/health')).json();
    $('#health').textContent = `server ${h.version} · PIL ${h.pil ? 'ok' : '缺失'}`;
    if (!h.pil) log('服务端缺 Pillow：apt install python3-pil', 'err');
    else log('服务就绪，先「连接打印机」再打印', 'ok');
  } catch (e) {
    log('连不上本地服务（是不是没跑 serve.py？）', 'err');
  }
})();

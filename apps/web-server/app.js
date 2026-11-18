/* apps/web-server/app.js — 实现 2：网页客户端 + Python 编码服务
 *
 * 分工：**编码全在服务端**（/api/encode 返回 base64 帧），本文件只做
 *       UI + 调 API + 用 MBLink 把帧写进蓝牙。没有本地编码器、没有 GBK 码表。
 */
'use strict';

const { $, createLogger, initTabs, setChip, setProgress, b64ToBytes, copyText, keepAwake } = window.MBUI;
const APP_VERSION = '__VER__';   // serve.py 响应时注入

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
const totalMm = () => parseFloat($('#total-mm').value) || 0;

const textReq = () => ({
  kind: 'text',
  text: $('#text').value,
  fontSize: parseInt($('#font-size').value, 10),
  bold: $('#bold').checked,
  underline: $('#underline').checked,
  mode: $('#mode-text').value,
  invert: $('#invert-text').checked,
  format: 'gbk',
  feed: $('#feed').checked,
  feedLines: parseInt($('#feed-lines').value, 10) || 0,
  totalMm: totalMm(),
});

const imageReq = () => ({
  kind: 'image',
  dataUrl: state.imageDataUrl,
  mode: $('#mode-image').value,
  invert: $('#invert-image').checked,
  format: 'bmp',
  vflip: $('#vflip').checked,
  feed: $('#feed').checked,
  feedLines: parseInt($('#feed-lines').value, 10) || 0,
  totalMm: totalMm(),
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

  // 浓度：低浓度打印更慢 → 长图在慢速 BLE 下才完整
  const dens = parseInt($('#density').value, 10) || 0;
  let restore = null;
  if (dens) {
    try {
      restore = await link.getDensity();
      await link.setDensity(dens);
      log(`浓度 ${restore} → ${dens}（打完恢复）`, 'ok');
    } catch (e) { log('设浓度失败：' + (e.message || e), 'warn'); }
  }

  try {
    const j = await api(path, req);
    const pages = j.pages || [j];
    $('#meta').textContent = j.meta
      ? `纸 57mm（内容 ${(j.meta.height / 8).toFixed(1)}mm 居中，两侧各 `
        + `${((456 - j.meta.width) / 2 / 8).toFixed(1)}mm 纸边）`
        + ` · 总长 ${((j.meta.height + 144) / 8).toFixed(1)}mm`
        + (pages.length > 1 ? ` · ${pages.length} 页` : '')
      : '';
    const chunk = parseInt($('#chunk').value, 10);

    for (let i = 0; i < pages.length; i++) {
      if (pages.length > 1) log(`发送第 ${i + 1}/${pages.length} 页（${pages[i].meta.height} 行）`, 'ok');
      await link.sendJob(jobFromApi(pages[i]),
        pages.length > 1 ? `${label} ${i + 1}/${pages.length}` : label, {
          chunk,
          preheat: $('#preheat').checked,
          onProgress: (r) => setProgress($('#bar'), r),
        });

      // 收尾帧：用 cmd 0x01 状态帧 —— 既触发打印，又不会断开 BLE（0x08 会断连）。
      try { await link.query(window.MBBle.STATUS_FRAME, 400); } catch (e) { /* 忽略 */ }

      // 实测：0x01 收尾不会断连；万一断了也自动重连（保险）
      try {
        await new Promise((r) => setTimeout(r, 600));
        if (!link.connected) { await link.ensureConnected(); log('打印后固件断开，已自动重连', 'ok'); }
      } catch (e) { log('自动重连失败：' + (e.message || e), 'warn'); }

      if (i < pages.length - 1) await new Promise((r) => setTimeout(r, 400));
    }
  } finally {
    if (dens && restore != null) {
      try {
      await link.setDensity(restore);
      log(`浓度已恢复为 ${restore}`, 'ok');
    } catch (e) {
      // 打印结束后固件常主动断开 —— 重连一次再恢复
      try {
        await link.connect();
        await link.setDensity(restore);
        log(`重连后浓度已恢复为 ${restore}`, 'ok');
      } catch (e2) { log('恢复浓度失败：' + (e2.message || e2), 'warn'); }
    }
      }
  }
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

$('#btn-disconnect').addEventListener('click', () => {
  try {
    link.disconnect();
    setChip($('#conn'), '未连接', 'warn');
    log('已断开（打印机已释放，官方 App / 其它设备可以连了）', 'ok');
  } catch (e) { log('断开失败：' + (e.message || e), 'err'); }
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

$('#btn-feed').addEventListener('click', async () => {
  if (!link.connected) { log('先连接', 'warn'); return; }
  const mm = parseFloat($('#feed-mm').value) || 0;
  if (mm <= 0) { log('走纸 0mm = 不走纸（已跳过）', 'ok'); return; }
  try {
    const j = await api('/api/feed', { mm, tick: true, total: true });
    $('#meta').textContent = `走纸 ${j.meta.mm}mm · ${j.meta.dots} 点 · ${j.frames.length} 帧`;
    await link.sendJob({ frames: j.frames.map(b64ToBytes), meta: j.meta }, `走纸 ${mm}mm`, {
      chunk: parseInt($('#chunk').value, 10),
      preheat: $('#preheat').checked,
      onProgress: (r) => setProgress($('#bar'), r),
    });
  } catch (e) { log('走纸失败：' + (e.message || e), 'err'); }
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
    const noPaper = window.MBBle.paperOut(f);
    const bat = window.MBBle.batteryPercent(f);
    const volt = window.MBBle.batteryVoltage(f);
    log(`设备信息：序列号 ${f.serial || '?'} · 灯=${pick(0x03)} · 0x02=${pick(0x02)}${noPaper === null ? '' : (noPaper ? ' · ⚠ 缺纸' : ' · 有纸')}${bat === null ? '' : ` · 电量≈${bat}% (${volt}V)`}`, noPaper ? 'warn' : 'ok');
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

/* --------------------------------------------------------------- 底层 */
const rawOut = (line) => {
  const el = $('#raw-out');
  el.textContent = (el.textContent ? el.textContent + '\n' : '') + line;
};

$('#btn-raw').addEventListener('click', async () => {
  if (!link.connected) { log('先连接', 'warn'); return; }
  const hex = $('#raw-hex').value.trim();
  if (!hex) { log('填一个帧，例如 aa 01 00 01 54', 'warn'); return; }
  try {
    const replies = await link.sendHex(hex);
    rawOut(`TX ${hex}`);
    replies.forEach((r) => rawOut(`RX ${r}`));
    if (!replies.length) rawOut('（无回包）');
  } catch (e) { rawOut('错误: ' + (e.message || e)); }
});

$('#btn-cmd').addEventListener('click', async () => {
  if (!link.connected) { log('先连接', 'warn'); return; }
  try {
    const cmd = parseInt($('#cmd-code').value, 0);
    const tag = parseInt($('#cmd-tag').value, 0);
    const val = parseInt($('#cmd-val').value, 0);
    const frame = window.MBBle.buildFrame(cmd, window.MBBle.tlv8(tag, val));
    const replies = await link.sendHex(window.MBBle.bytesToHex(frame));
    rawOut(`TX ${window.MBBle.bytesToHex(frame)}  (cmd=0x${cmd.toString(16)} tag=0x${tag.toString(16)}=${val})`);
    replies.forEach((r) => rawOut(`RX ${r}`));
  } catch (e) { rawOut('错误: ' + (e.message || e)); }
});

$('#btn-notify').addEventListener('click', async () => {
  if (!link.connected) { log('先连接', 'warn'); return; }
  rawOut('监听 5 秒…');
  try {
    const frames = await link.query(new Uint8Array(0), 5000);
    frames.forEach((f) => rawOut(`RX ${window.MBBle.bytesToHex(f)}`));
    rawOut(`共 ${frames.length} 帧`);
  } catch (e) { rawOut('错误: ' + (e.message || e)); }
});

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

/* apps/static-web/app.js — 实现 1：纯静态网页（零后端）
 *
 * 编码全在浏览器里：canvas 渲染 + encoder.js 抖动封帧 + 内嵌 GBK 码表。
 * 本文件**不发起任何网络请求**（除了加载自身脚本）。
 */
'use strict';

const { $, createLogger, initTabs, setChip, setProgress, copyText, keepAwake } = window.MBUI;
const E = window.MBEncoder;
const R = window.MBRender;
const APP_VERSION = '2.0.0';

const log = createLogger($('#log'));
const link = window.MBLink.createLink({ log });

const state = { imageDataUrl: null, imageEl: null, busy: false };

/* ------------------------------------------------------------------ 工具 */
/** 像素字号 → 固件字号档位（≤26→0 / ≤36→1 / 更大→2） */
function sizeTier(px) {
  const v = parseInt(px, 10) || 26;
  if (v <= 26) return 0;
  if (v <= 36) return 1;
  return 2;
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('图片解码失败'));
    img.src = src;
  });
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
  format: $('#fmt-text').value,
  darken: parseInt($('#darken-text').value, 10),
  feed: $('#feed').checked,
  feedLines: parseInt($('#feed-lines').value, 10) || 0,
  exact: $('#chk-exact').checked,
  totalMm: totalMm(),
});

const imageReq = () => ({
  kind: 'image',
  dataUrl: state.imageDataUrl,
  mode: $('#mode-image').value,
  invert: $('#invert-image').checked,
  vflip: $('#vflip').checked,
  darken: parseInt($('#darken-image').value, 10),
  feed: $('#feed').checked,
  feedLines: parseInt($('#feed-lines').value, 10) || 0,
  totalMm: totalMm(),
});

/* --------------------------------------------------------------- 编码 */
/** 请求 → {frames:[Uint8Array], meta} ；raw 已附带（预览用） */
async function encode(req) {
  const mode = req.mode || 'threshold';
  const darken = Math.max(0, Math.min(3, parseInt(req.darken, 10) || 0));
  const tier = sizeTier(req.fontSize);
  const useGbk = req.kind !== 'image' && (req.format || 'gbk') === 'gbk';

  if (useGbk && (darken > 0 || tier > 0)) {
    log(`已自动改走位图：${darken > 0 ? '浓度' : '字号'}只能在位图模式下生效`, 'warn');
  }

  // 中文/非 ASCII 必须走位图：这台固件的 GBK 文本帧没有中文字形，汉字会变黑块
  const isAscii = !/[^\x00-\x7F]/.test(req.text || '');
  if (useGbk && !isAscii) {
    log('文本含中文 → 自动改走位图（GBK 文本帧无中文字形，会打成黑块）', 'warn');
  }

  // 快路径：GBK 文本帧（仅 ASCII）
  if (useGbk && isAscii && darken === 0 && tier === 0) {
    const job = E.jobFromText(req.text || '', window.GBK.encode, {
      bold: req.bold, underline: req.underline, fontSize: 0,
    });
    if (job) {
      if (req.feed) job.frames = job.frames.concat(E.feedJob(3).frames);
      return job;
    }
    log('文本含 GBK 无法表示的字符 → 自动转位图', 'warn');
  }

  // 位图路径
  let grayed;
  if (req.kind === 'image') {
    if (!state.imageEl) state.imageEl = await loadImage(req.dataUrl || state.imageDataUrl);
    grayed = await R.imageToGray(state.imageEl);
  } else {
    grayed = R.textToGray(req.text || '', req);
  }
  let gray = grayed.gray;
  if (req.invert) {
    for (let i = 0; i < gray.length; i++) gray[i] = 255 - gray[i];
  }

  let d = E.ditherToRaw(gray, grayed.w, grayed.h, mode === 'none' ? 'threshold' : mode, null, darken);

  // exact：内容结束即停，不补白
  if (req.exact) {
    // 跳过 lengthMm / totalMm 的补白
  } else if (req.lengthMm) {
    const targetH = Math.round(parseFloat(req.lengthMm) * 8);
    d = E.padRaw(d.raw, d.w, d.h, targetH);
    log(`内容高度 ${req.lengthMm}mm → ${d.h} 点`, 'ok');
  }

  // 纸总长：内容高度 = 总长 - 固件固定的 18mm
  if (!req.exact && req.totalMm) {
    const targetH = E.contentDotsForTotal(parseFloat(req.totalMm), 203);
    d = E.padRaw(d.raw, d.w, d.h, targetH);
    log(`纸总长 ${req.totalMm}mm：内容 ${d.h} 点 (${(d.h / 8).toFixed(1)}mm) + 固件 18mm`, 'ok');
  }

  // 超过单任务上限就切页（实测 400 行能完整打，480 行只出一行）
  const slices = E.paginateRaw(d.raw, d.w, d.h, E.MAX_ROWS_PER_JOB);
  if (slices.length > 1) {
    log(`图高 ${d.h} 行 > 单任务上限 ${E.MAX_ROWS_PER_JOB} 行 → 分 ${slices.length} 页（页间有固件 18mm 空隙）`, 'warn');
  }

  const feedLines = Math.max(0, Math.min(8, parseInt(req.feedLines, 10) || 0));
  const pages = slices.map((slice) => {
    const pageJob = E.jobFromRaw(slice.raw, slice.w, slice.h, 'bmp', { official: true, topDown: !req.vflip });
    if (feedLines > 0) pageJob.frames = pageJob.frames.concat(E.feedJob(feedLines).frames);
    return pageJob;
  });

  // job 本身保持「整图」—— 预览要用完整位图；打印时走 job.pages
  const job = E.jobFromRaw(d.raw, d.w, d.h, 'bmp', { official: true, topDown: !req.vflip });
  if (feedLines > 0) job.frames = job.frames.concat(E.feedJob(feedLines).frames);
  job.raw = d.raw;
  job.pages = pages;
  return job;
}

async function preview(req) {
  const job = await encode({ ...req, format: req.kind === 'image' ? 'bmp' : 'bmp' });
  $('#preview').src = R.rawToDataURL(job.meta.width, job.meta.height, job.raw, 2);
}

/* --------------------------------------------------------------- 打印 */
async function print(req, label) {
  if (!link.connected) { log('先点「连接打印机」', 'warn'); return; }
  const job = await encode(req);

  // 浓度：低浓度打印更慢 → 慢速 BLE 下长图才打得完整
  const dens = parseInt($('#density').value, 10) || 0;
  let restore = null;
  if (dens) {
    try {
      restore = await link.getDensity();
      await link.setDensity(dens);
      log(`浓度 ${restore} → ${dens}（打完恢复）`, 'ok');
    } catch (e) { log('设浓度失败：' + (e.message || e), 'warn'); }
  }
  const pages = job.pages || [job];
  $('#meta').textContent = `${job.meta.format} · ${job.meta.width}×${job.meta.height}`
    + (pages.length > 1 ? ` · ${pages.length} 页` : '');

  for (let i = 0; i < pages.length; i++) {
    const page = pages[i];
    if (pages.length > 1) log(`发送第 ${i + 1}/${pages.length} 页（${page.meta.height} 行）`, 'ok');
    await link.sendJob(page, pages.length > 1 ? `${label} ${i + 1}/${pages.length}` : label, {
      chunk: parseInt($('#chunk').value, 10),
      preheat: $('#preheat').checked,
      onProgress: (r) => setProgress($('#bar'), r),
    });

    // 终结帧：大图必须给固件一个"任务结束"信号，否则会中途断。
    // 用状态查询帧 —— 只一个来回，不驱动电机（零走纸）。
    if (!($('#chk-exact') && $('#chk-exact').checked)) {
      try { await link.query(window.MBBle.STATUS_FRAME, 400); } catch (e) { /* 忽略 */ }
    }
    if (i < pages.length - 1) await new Promise((r) => setTimeout(r, 400));
  }

  if (dens && restore != null) {
    try { await link.setDensity(restore); log(`浓度已恢复为 ${restore}`, 'ok'); }
    catch (e) { log('恢复浓度失败：' + (e.message || e), 'warn'); }
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

$('#btn-preview-text').addEventListener('click', () => preview(textReq()).then(() => log('预览已更新')).catch((e) => log('预览失败：' + (e.message || e), 'err')));
$('#btn-print-text').addEventListener('click', () => print(textReq(), '文字打印').catch((e) => log('文字打印失败：' + (e.message || e), 'err')));

$('#btn-preview-image').addEventListener('click', () => {
  if (!state.imageDataUrl) { log('先选一张图片', 'warn'); return; }
  preview(imageReq()).then(() => log('预览已更新')).catch((e) => log('预览失败：' + (e.message || e), 'err'));
});
$('#btn-print-image').addEventListener('click', () => {
  if (!state.imageDataUrl) { log('先选一张图片', 'warn'); return; }
  print(imageReq(), '图片打印').catch((e) => log('图片打印失败：' + (e.message || e), 'err'));
});

$('#btn-feed').addEventListener('click', async () => {
  if (!link.connected) { log('先连接', 'warn'); return; }
  const mm = parseFloat($('#feed-mm').value) || 0;
  if (mm <= 0) { log('走纸 0mm = 不走纸（已跳过）', 'ok'); return; }
  try {
    const job = E.blankJob(mm, { tick: true, total: true });
    $('#meta').textContent = `走纸 ${job.meta.mm}mm · ${job.meta.dots} 点 · ${job.frames.length} 帧`;
    await link.sendJob(job, `走纸 ${mm}mm`, {
      chunk: parseInt($('#chunk').value, 10),
      preheat: $('#preheat').checked,
      onProgress: (r) => setProgress($('#bar'), r),
    });
  } catch (e) { log('走纸失败：' + (e.message || e), 'err'); }
});

$('#btn-calib').addEventListener('click', async () => {
  try {
    if (!link.connected) { log('先点「连接打印机」', 'warn'); return; }
    const g = R.calibrationGray();
    const d = E.ditherToRaw(g.gray, g.w, g.h, 'threshold', null, 0);
    const job = E.jobFromRaw(d.raw, d.w, d.h, 'bmp', { official: true, topDown: !$('#vflip').checked });
    job.frames = job.frames.concat(E.feedJob(3).frames);
    $('#preview').src = R.rawToDataURL(d.w, d.h, d.raw, 2);
    $('#meta').textContent = `${job.meta.format} · ${job.meta.bytes}B · ${job.meta.chunks}帧 · ${job.meta.width}×${job.meta.height}`;
    await link.sendJob(job, '校准图', {
      chunk: parseInt($('#chunk').value, 10),
      preheat: $('#preheat').checked,
      onProgress: (r) => setProgress($('#bar'), r),
    });
    log('若上下颠倒 → 勾「垂直翻转」；全白 → 查电量/纸面；断行 → 分片改 20B', 'warn');
  } catch (e) { log('校准图失败：' + (e.message || e), 'err'); }
});

$('#btn-sizeprobe').addEventListener('click', async () => {
  try {
    if (!link.connected) { log('先点「连接打印机」', 'warn'); return; }
    let frames = [];
    for (let tier = 0; tier < 4; tier++) {
      const job = E.jobFromText(`档位 tier=${tier}\n`, window.GBK.encode, { fontSize: tier });
      frames = frames.concat(job.frames);
    }
    const g = R.textToGray('位图 40px 对照', { fontSize: 40 });
    const d = E.ditherToRaw(g.gray, g.w, g.h, 'threshold', null, 0);
    frames = frames.concat(E.jobFromRaw(d.raw, d.w, d.h, 'bmp', { official: true }).frames);
    frames = frames.concat(E.feedJob(3).frames);
    const bytes = frames.reduce((a, f) => a + f.length, 0);
    await link.sendJob({ frames, meta: { format: 'probe', bytes, chunks: frames.length, preheat: 2048 } }, '字号档位测试', {
      chunk: parseInt($('#chunk').value, 10),
      preheat: $('#preheat').checked,
      onProgress: (r) => setProgress($('#bar'), r),
    });
    log('看纸面：四行「档位 tier=N」一样大 → 固件忽略字号档位', 'warn');
  } catch (e) { log('档位测试失败：' + (e.message || e), 'err'); }
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
    await link.writeAll(Uint8Array.from([0xaa, 0x01, 0x00, 0x01, 0x54]), '状态查询', parseInt($('#chunk').value, 10));
    log('已发状态查询，等 notify 回包', 'warn');
  } catch (e) { log('状态查询失败：' + (e.message || e), 'err'); }
});

$('#btn-clear').addEventListener('click', () => { $('#log').innerHTML = ''; });
$('#btn-copy').addEventListener('click', async () => {
  const ok = await copyText($('#log').innerText);
  log(ok ? '日志已复制' : '复制失败，手动长按选择吧', ok ? 'ok' : 'warn');
});

/* --------------------------------------------------------------- 启动 */
(function init() {
  if (!navigator.bluetooth) {
    log('这个浏览器不支持 Web Bluetooth —— 用 Android 版 Chrome / Edge', 'err');
    $('#btn-connect').disabled = true;
  }
  if (!window.isSecureContext) log('当前不是安全上下文：必须用 https 或 localhost 打开', 'err');
  document.getElementById('health').textContent = window.MB_STANDALONE ? '单文件静态版' : '静态目录版';
  document.querySelector('#mode').textContent = `浏览器本地编码 · 页面 v${APP_VERSION}`;
  log(`纯静态模式：编码全在浏览器（页面 v${APP_VERSION}）`, 'ok');
  log(`GBK 码表：${window.GBK ? window.GBK.valid + ' 个码位' : '未加载（文字将转位图）'}`, window.GBK ? 'ok' : 'warn');
  log('先「连接打印机」再打印', 'ok');
})();

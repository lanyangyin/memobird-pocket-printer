/* web/encoder.js — 编码器（纯 JS，无 DOM 依赖）
 *
 * 与 Python 侧（memobird_printer/）**逐字节等价**，由 tests/test_encoder_js.js
 * 用 tools/gen_fixtures.py 生成的夹具逐字节验证。
 *
 * 用途：让同一个页面在没有 Python 服务端时也能自己编码（纯静态部署 / GitHub Pages）。
 * 依赖注入：GBK 编码表不在这里，文本帧通过 encodeTextJob(text, gbkEncode) 传入。
 *
 * 浏览器：window.MBEncoder
 * Node  ：require('./encoder.js')
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MBEncoder = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const HEADER = 0xAA;
  const MAGIC_SUM = 0x56;

  const CMD_STATUS = 0x01;
  const CMD_CONTROL = 0x03;
  const CMD_PRINT = 0x04;

  const TAG_TEXT = 0x07;
  const TAG_BITMAP = 0x08;
  const TAG_TOTAL_LEN = 0x0A;
  const TAG_PKG_COUNT = 0x0B;
  const TAG_PKG_NO = 0x0C;
  const TAG_BOLD = 0x0D;
  const TAG_FONT_SIZE = 0x10;
  const TAG_UNDERLINE = 0x11;

  const MAX_CHUNK = 1024;
  const TEXT_CHUNK = 300;
  const PREHEAT = 2048;
  const WIDTH = 384;

  /* ------------------------------------------------------------------ 基础 */
  function sumBytes(bytes) {
    let s = 0;
    for (let i = 0; i < bytes.length; i++) s += bytes[i];
    return s;
  }

  function checksum(body) {
    return (MAGIC_SUM - (sumBytes(body) & 0xffff)) & 0xff;
  }

  function buildFrame(cmd, payload) {
    payload = payload || new Uint8Array(0);
    const len = payload.length + 1;
    const body = new Uint8Array(2 + 1 + payload.length);
    body[0] = len & 0xff;
    body[1] = (len >> 8) & 0xff;
    body[2] = cmd;
    body.set(payload, 3);
    const out = new Uint8Array(body.length + 2);
    out[0] = HEADER;
    out.set(body, 1);
    out[out.length - 1] = checksum(body);
    return out;
  }

  function tlv(tag, value) {
    value = value || new Uint8Array(0);
    const out = new Uint8Array(3 + value.length);
    out[0] = tag;
    out[1] = value.length & 0xff;
    out[2] = (value.length >> 8) & 0xff;
    out.set(value, 3);
    return out;
  }

  function u16(n) {
    return new Uint8Array([n & 0xff, (n >> 8) & 0xff]);
  }

  function concat(parts) {
    let total = 0;
    for (const p of parts) total += p.length;
    const out = new Uint8Array(total);
    let off = 0;
    for (const p of parts) { out.set(p, off); off += p.length; }
    return out;
  }

  /* ------------------------------------------------------------------ 任务 */
  function chunkedJob(data, tag, chunk, includeTotalLen) {
    chunk = chunk || MAX_CHUNK;
    const pieces = [];
    for (let i = 0; i < data.length; i += chunk) pieces.push(data.subarray(i, Math.min(i + chunk, data.length)));
    if (pieces.length === 0) pieces.push(new Uint8Array(0));
    const count = pieces.length;
    const frames = pieces.map((piece, idx) => {
      const parts = [
        tlv(TAG_PKG_COUNT, u16(count)),
        tlv(TAG_PKG_NO, u16(idx + 1)),
      ];
      if (includeTotalLen) parts.push(tlv(TAG_TOTAL_LEN, u16(data.length & 0xffff)));
      parts.push(tlv(tag, piece));
      return buildFrame(CMD_PRINT, concat(parts));
    });
    return { frames, meta: { chunks: count, bytes: data.length } };
  }

  /**
   * 文本任务（对齐官方 SDK）：
   *   tag 0x0B 总包数 | 0x0C 包序号 | 0x0D 加粗 | 0x11 下划线 | 0x10 字号(档位) | 0x07 GBK 文本
   * 每包文本不超过 300 字节，超过要分包。
   */
  function buildTextJob(gbkBytes, opts) {
    opts = opts || {};
    const chunk = opts.chunk || TEXT_CHUNK;
    const bold = opts.bold ? 1 : 0;
    const underline = opts.underline ? 1 : 0;
    const fontSize = (opts.fontSize | 0) & 0xff;

    const pieces = [];
    for (let i = 0; i < gbkBytes.length; i += chunk) {
      pieces.push(gbkBytes.subarray(i, Math.min(i + chunk, gbkBytes.length)));
    }
    if (!pieces.length) pieces.push(Uint8Array.from([0x0a]));
    const count = pieces.length;

    const frames = pieces.map((piece, i) => buildFrame(CMD_PRINT, concat([
      tlv(TAG_PKG_COUNT, u16(count)),
      tlv(TAG_PKG_NO, u16(i + 1)),
      tlv(TAG_BOLD, Uint8Array.from([bold])),
      tlv(TAG_UNDERLINE, Uint8Array.from([underline])),
      tlv(TAG_FONT_SIZE, Uint8Array.from([fontSize])),
      tlv(TAG_TEXT, piece),
    ])));

    return { frames, meta: { chunks: count, bytes: gbkBytes.length } };
  }

  function buildBitmapJob(raw, chunk) {
    return chunkedJob(raw, TAG_BITMAP, chunk);
  }

  function buildBmpJob(bmp, chunk) {
    return chunkedJob(bmp, TAG_BITMAP, chunk);
  }

  function preheatBytes() {
    return new Uint8Array(PREHEAT);
  }

  function statusFrame() {
    return buildFrame(CMD_STATUS);
  }

  /* ------------------------------------------------------------ 抖动/打包 */
  const BAYER8 = [
    [0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21],
  ];

  function packThreshold(gray, w, h, threshold) {
    const rb = (w + 7) >> 3;
    const out = new Uint8Array(rb * h);
    for (let y = 0; y < h; y++) {
      const base = y * rb;
      const row = y * w;
      for (let x = 0; x < w; x++) {
        if (gray[row + x] < threshold) out[base + (x >> 3)] |= 0x80 >> (x & 7);
      }
    }
    return out;
  }

  /** 浓度档位 → [阈值, 横向膨化, 纵向膨化]；热敏偏浅时用 */
  const DARKEN_PRESETS = {
    0: [128, 0, 0],
    1: [152, 1, 0],
    2: [172, 1, 1],
    3: [192, 2, 1],
  };

  /** 黑点膨胀（形态学 dilation）—— 补偿打印机偏浅，让笔画变粗 */
  function dilateBlack(raw, w, h, horiz, vert) {
    if ((!horiz && !vert) || !w || !h) return raw;
    const rb = (w + 7) >> 3;
    const grid = [];
    for (let y = 0; y < h; y++) {
      const row = new Uint8Array(w);
      const base = y * rb;
      for (let x = 0; x < w; x++) row[x] = (raw[base + (x >> 3)] & (0x80 >> (x & 7))) ? 1 : 0;
      grid.push(row);
    }
    for (let n = 0; n < horiz; n++) {
      for (let y = 0; y < h; y++) {
        const src = grid[y].slice();
        const row = grid[y];
        for (let x = 0; x < w; x++) {
          if (!src[x]) continue;
          if (x > 0) row[x - 1] = 1;
          row[x] = 1;
          if (x < w - 1) row[x + 1] = 1;
        }
      }
    }
    for (let n = 0; n < vert; n++) {
      const snap = grid.map((r) => r.slice());
      for (let y = 0; y < h; y++) {
        for (let x = 0; x < w; x++) {
          if (!snap[y][x]) continue;
          if (y > 0) grid[y - 1][x] = 1;
          if (y < h - 1) grid[y + 1][x] = 1;
        }
      }
    }
    const out = new Uint8Array(rb * h);
    for (let y = 0; y < h; y++) {
      const base = y * rb;
      const row = grid[y];
      for (let x = 0; x < w; x++) if (row[x]) out[base + (x >> 3)] |= 0x80 >> (x & 7);
    }
    return out;
  }

  /**
   * 灰度 → 1bpp 裸位图
   * @param {number} threshold 二值化阈值；给 null/undefined 则按 darken 档位取
   * @param {number} darken 0 标准 / 1 加深 / 2 更黑 / 3 最黑
   */
  function ditherToRaw(gray, w, h, mode, threshold, darken) {
    mode = mode || 'floyd';
    const preset = DARKEN_PRESETS[darken | 0] || DARKEN_PRESETS[0];
    const th = (threshold == null) ? preset[0] : threshold;
    const hExp = preset[1];
    const vExp = preset[2];

    let raw;
    if (mode === 'none' || mode === 'threshold') {
      raw = packThreshold(gray, w, h, th);
      return { w, h, raw: dilateBlack(raw, w, h, hExp, vExp) };
    }

    if (mode === 'bayer') {
      const rb = (w + 7) >> 3;
      raw = new Uint8Array(rb * h);
      for (let y = 0; y < h; y++) {
        const brow = BAYER8[y & 7];
        const base = y * rb;
        const row = y * w;
        for (let x = 0; x < w; x++) {
          const t = (brow[x & 7] + 0.5) * 255.0 / 64.0 * (th / 128.0);
          if (gray[row + x] < t) raw[base + (x >> 3)] |= 0x80 >> (x & 7);
        }
      }
      return { w, h, raw: dilateBlack(raw, w, h, hExp, vExp) };
    }

    const kernels = {
      floyd: [[1, 0, 7 / 16], [-1, 1, 3 / 16], [0, 1, 5 / 16], [1, 1, 1 / 16]],
      atkinson: [[1, 0, 1 / 8], [2, 0, 1 / 8], [-1, 1, 1 / 8], [0, 1, 1 / 8], [1, 1, 1 / 8], [0, 2, 1 / 8]],
    };
    const kernel = kernels[mode];
    if (!kernel) throw new Error('unknown dither mode: ' + mode);

    const buf = new Float64Array(w * h);
    for (let i = 0; i < gray.length; i++) buf[i] = gray[i];

    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        const i = y * w + x;
        const old = buf[i];
        const nv = old >= th ? 255.0 : 0.0;
        buf[i] = nv;
        const err = old - nv;
        if (err !== 0) {
          for (const [dx, dy, k] of kernel) {
            const nx = x + dx;
            const ny = y + dy;
            if (nx >= 0 && nx < w && ny >= 0 && ny < h) buf[ny * w + nx] += err * k;
          }
        }
      }
    }
    // Python: _pack_threshold([int(v) for v in buf], ...)，int() 向零截断
    const quant = new Uint8Array(w * h);
    for (let i = 0; i < quant.length; i++) quant[i] = Math.trunc(buf[i]);
    raw = packThreshold(quant, w, h, th);
    return { w, h, raw: dilateBlack(raw, w, h, hExp, vExp) };
  }

  /**
   * 1bpp 裸位图 → BMP，**与 PIL 的 1-bit BMP 逐字节一致**（官方 SDK 的编码路径）
   *
   * 两个关键点：
   *  1. 调色板 index0=黑、index1=白；我们内部 bit=1 是黑，所以行数据要**逐字节取反**；
   *  2. official=true 时 biHeight 取正、行序 top-down（官方非标准做法）。
   * 搞反 ⇒ 固件判无效（实测打出自带的 "nice to meet you" 示范页）。
   */
  function rawToBmp(w, h, raw, topDown, official) {
    if (official === undefined) official = true;
    if (!official && topDown === undefined) topDown = true;

    const rowBytes = ((w + 31) >> 5) << 2;
    const srcRb = (w + 7) >> 3;
    const bodyLen = rowBytes * h;
    const palette = 8;
    const off = 14 + 40 + palette;
    const out = new Uint8Array(off + bodyLen);
    const dv = new DataView(out.buffer);

    let heightField;
    if (official) heightField = h;                                   // 正数 + top-down 行序
    else heightField = topDown === false ? h : -h;

    out[0] = 0x42; out[1] = 0x4d;
    dv.setUint32(2, off + bodyLen, true);
    dv.setUint32(10, off, true);
    dv.setUint32(14, 40, true);
    dv.setInt32(18, w, true);
    dv.setInt32(22, heightField, true);
    dv.setUint16(26, 1, true);
    dv.setUint16(28, 1, true);
    dv.setUint32(34, bodyLen, true);
    dv.setInt32(38, 3780, true);
    dv.setInt32(42, 3780, true);
    dv.setUint32(46, 2, true);
    dv.setUint32(50, 2, true);
    dv.setUint32(54, 0x00000000, true);   // index0 = 黑
    dv.setUint32(58, 0x00ffffff, true);   // index1 = 白

    for (let row = 0; row < h; row++) {
      const y = (official || topDown !== false) ? row : h - 1 - row;
      const srcOff = y * srcRb;
      const dstOff = off + row * rowBytes;
      for (let i = 0; i < srcRb; i++) out[dstOff + i] = raw[srcOff + i] ^ 0xff;
    }
    return out;
  }

  /* ------------------------------------------------------------------ 一站式 */
  function utf8ToGray(text, opts) {
    throw new Error('utf8ToGray 需要 DOM：请在页面里用 MBRender.textToGray');
  }

  function flipRows(raw, w, h) {
    const rb = (w + 7) >> 3;
    const out = new Uint8Array(raw.length);
    for (let y = 0; y < h; y++) {
      out.set(raw.subarray((h - 1 - y) * rb, (h - y) * rb), y * rb);
    }
    return out;
  }

  /**
   * 组装一个可直接发送的位图任务
   * @param {Uint8Array} raw 1bpp 裸位图
   * @param {'bmp'|'raw'} format
   * @param {{topDown?:boolean, official?:boolean}} opts
   */
  function jobFromRaw(raw, w, h, format, opts) {
    opts = opts || {};
    const official = opts.official !== false;
    const topDown = opts.topDown !== false;
    format = format === 'raw' ? 'raw' : 'bmp';

    const body = topDown ? raw : flipRows(raw, w, h);
    let data;
    if (format === 'raw') data = body;
    else data = rawToBmp(w, h, body, true, official);

    const job = buildBmpJob(data);
    return {
      frames: job.frames,
      meta: Object.assign({ format, preheat: PREHEAT, width: w, height: h }, job.meta),
    };
  }

  /** 文本：优先 GBK 帧；编不了就返回 null 让调用方退回位图 */
  function jobFromText(text, gbkEncode, opts) {
    opts = opts || {};
    const payloadText = text.endsWith('\n') ? text : text + '\n';
    const bytes = gbkEncode(payloadText);
    if (bytes == null) return null;
    const job = buildTextJob(bytes, opts);
    return {
      frames: job.frames,
      meta: Object.assign({ format: 'gbk', preheat: PREHEAT, width: WIDTH, height: 0 }, job.meta),
    };
  }

  /** 走纸：一段纯换行（官方 SDK 打图后会补一帧） */
  function feedJob(lines) {
    const text = '\n'.repeat(Math.max(1, lines || 3));
    return buildTextJob(Uint8Array.from(text.split('').map((c) => c.charCodeAt(0))));
  }

  return {
    // 常量
    HEADER, MAGIC_SUM, PREHEAT, MAX_CHUNK, TEXT_CHUNK, WIDTH,
    CMD_STATUS, CMD_CONTROL, CMD_PRINT,
    TAG_TEXT, TAG_BITMAP, TAG_TOTAL_LEN, TAG_PKG_COUNT, TAG_PKG_NO,
    TAG_BOLD, TAG_FONT_SIZE, TAG_UNDERLINE,
    // 帧
    checksum, buildFrame, tlv, concat, u16,
    preheatBytes, statusFrame,
    buildTextJob, buildBitmapJob, buildBmpJob, chunkedJob, feedJob,
    // 图像
    ditherToRaw, rawToBmp, packThreshold, flipRows, dilateBlack, DARKEN_PRESETS,
    jobFromRaw, jobFromText, utf8ToGray,
  };
});

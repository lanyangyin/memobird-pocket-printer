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

  const MAX_CHUNK = 1024;
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
  function chunkedJob(data, tag, chunk) {
    chunk = chunk || MAX_CHUNK;
    const pieces = [];
    for (let i = 0; i < data.length; i += chunk) pieces.push(data.subarray(i, Math.min(i + chunk, data.length)));
    if (pieces.length === 0) pieces.push(new Uint8Array(0));
    const count = pieces.length;
    const frames = pieces.map((piece, idx) => buildFrame(
      CMD_PRINT,
      concat([
        tlv(TAG_PKG_COUNT, u16(count)),
        tlv(TAG_PKG_NO, u16(idx + 1)),
        tlv(TAG_TOTAL_LEN, u16(data.length & 0xffff)),
        tlv(tag, piece),
      ]),
    ));
    return { frames, meta: { chunks: count, bytes: data.length } };
  }

  /** 文本任务：text 必须是已经 GBK 编码好的字节（含结尾 \n） */
  function buildTextJob(gbkBytes) {
    const payload = concat([
      tlv(TAG_PKG_COUNT, u16(1)),
      tlv(TAG_PKG_NO, u16(1)),
      tlv(TAG_TOTAL_LEN, u16(gbkBytes.length & 0xffff)),
      tlv(TAG_TEXT, gbkBytes),
    ]);
    return {
      frames: [buildFrame(CMD_PRINT, payload)],
      meta: { chunks: 1, bytes: gbkBytes.length },
    };
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

  /** 灰度（Uint8Array, w*h, 0=黑）→ 1bpp 裸位图（1=黑，MSB 在左，行按字节对齐） */
  function ditherToRaw(gray, w, h, mode, threshold) {
    mode = mode || 'floyd';
    threshold = threshold == null ? 128 : threshold;

    if (mode === 'none' || mode === 'threshold') {
      return { w, h, raw: packThreshold(gray, w, h, threshold) };
    }

    if (mode === 'bayer') {
      const rb = (w + 7) >> 3;
      const out = new Uint8Array(rb * h);
      for (let y = 0; y < h; y++) {
        const brow = BAYER8[y & 7];
        const base = y * rb;
        const row = y * w;
        for (let x = 0; x < w; x++) {
          const t = (brow[x & 7] + 0.5) * 255.0 / 64.0;
          if (gray[row + x] < t) out[base + (x >> 3)] |= 0x80 >> (x & 7);
        }
      }
      return { w, h, raw: out };
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
        const nv = old >= threshold ? 255.0 : 0.0;
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
    return { w, h, raw: packThreshold(quant, w, h, threshold) };
  }

  /** 1bpp 裸位图 → BMP（与 Python raw_to_bmp 字节一致） */
  function rawToBmp(w, h, raw, topDown) {
    topDown = topDown !== false;
    const rowBytes = ((w + 31) >> 5) << 2;
    const srcRb = (w + 7) >> 3;
    const bodyLen = rowBytes * h;
    const palette = 8;                                  // 2 项 × 4 字节
    const off = 14 + 40 + palette;
    const out = new Uint8Array(off + bodyLen);
    const dv = new DataView(out.buffer);

    out[0] = 0x42; out[1] = 0x4d;                       // 'BM'
    dv.setUint32(2, off + bodyLen, true);
    dv.setUint32(10, off, true);
    dv.setUint32(14, 40, true);                         // biSize
    dv.setInt32(18, w, true);
    dv.setInt32(22, topDown ? -h : h, true);
    dv.setUint16(26, 1, true);                          // biPlanes
    dv.setUint16(28, 1, true);                          // biBitCount
    dv.setUint32(34, bodyLen, true);
    dv.setInt32(38, 2835, true);
    dv.setInt32(42, 2835, true);
    dv.setUint32(46, 2, true);                          // biClrUsed
    dv.setUint32(50, 0, true);
    // 调色板：0=白 1=黑
    dv.setUint32(54, 0x00ffffff, true);
    dv.setUint32(58, 0x00000000, true);

    for (let row = 0; row < h; row++) {
      const y = topDown ? row : h - 1 - row;
      const dst = off + row * rowBytes;
      out.set(raw.subarray(y * srcRb, y * srcRb + srcRb), dst);
    }
    return out;
  }

  /* ------------------------------------------------------------------ 一站式 */
  function utf8ToGray(text, opts) {
    throw new Error('utf8ToGray 需要 DOM：请在页面里用 MBRender.textToGray');
  }

  /**
   * 组装一个可直接发送的任务
   * @param {Uint8Array} raw  1bpp 裸位图
   * @param {'bmp'|'raw'} format
   */
  function jobFromRaw(raw, w, h, format, topDown) {
    format = format === 'raw' ? 'raw' : 'bmp';
    let data;
    if (format === 'raw') data = raw;
    else data = rawToBmp(w, h, raw, topDown !== false);
    const job = buildBmpJob(data);
    return {
      frames: job.frames,
      meta: Object.assign({ format, preheat: PREHEAT, width: w, height: h }, job.meta),
    };
  }

  /** 文本：优先 GBK 帧；编不了就返回 null 让调用方退回位图 */
  function jobFromText(text, gbkEncode) {
    const payloadText = text.endsWith('\n') ? text : text + '\n';
    const bytes = gbkEncode(payloadText);
    if (bytes == null) return null;
    const job = buildTextJob(bytes);
    return {
      frames: job.frames,
      meta: Object.assign({ format: 'gbk', preheat: PREHEAT, width: WIDTH, height: 0 }, job.meta),
    };
  }

  return {
    // 常量
    HEADER, MAGIC_SUM, PREHEAT, MAX_CHUNK, WIDTH,
    CMD_STATUS, CMD_CONTROL, CMD_PRINT,
    TAG_TEXT, TAG_BITMAP, TAG_TOTAL_LEN, TAG_PKG_COUNT, TAG_PKG_NO,
    // 帧
    checksum, buildFrame, tlv, concat, u16,
    preheatBytes, statusFrame,
    buildTextJob, buildBitmapJob, buildBmpJob, chunkedJob,
    // 图像
    ditherToRaw, rawToBmp, packThreshold,
    jobFromRaw, jobFromText, utf8ToGray,
  };
});

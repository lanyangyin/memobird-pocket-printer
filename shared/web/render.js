/* web/render.js — DOM 侧渲染（canvas）
 *
 * 只做"变成灰度矩阵"这件事，抖动/打包/封帧在 encoder.js（纯 JS，可 Node 测试）。
 * 浏览器：window.MBRender
 */
(function (root) {
  'use strict';

  const W = 384;
  const FONT_STACK = '"Microsoft YaHei","Noto Sans CJK SC","Noto Sans SC","PingFang SC","Heiti SC",sans-serif';

  function makeCanvas(w, h) {
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    return c;
  }

  function toGray(ctx, w, h) {
    const data = ctx.getImageData(0, 0, w, h).data;
    const gray = new Uint8Array(w * h);
    for (let i = 0, p = 0; i < gray.length; i++, p += 4) {
      // 与 Pillow 的 convert('L') 一致的亮度权重
      gray[i] = Math.round(0.299 * data[p] + 0.587 * data[p + 1] + 0.114 * data[p + 2]);
    }
    return gray;
  }

  /**
   * 文本 → 灰度（白底黑字，按 384 宽自动换行）
   * 参数与 Python 侧 render_text 对齐：fontSize(px) / lineSpacing / padding
   */
  function textToGray(text, opts) {
    opts = opts || {};
    const fontSize = Math.max(8, Math.round(opts.fontSize || 24));
    const lineSpacing = opts.lineSpacing == null ? 6 : opts.lineSpacing;
    const padding = opts.padding == null ? 4 : opts.padding;
    const font = `${fontSize}px ${opts.fontFamily || FONT_STACK}`;

    const probe = makeCanvas(W, 8).getContext('2d');
    probe.font = font;

    const lines = [];
    for (const raw of String(text == null ? '' : text).replace(/\r\n?/g, '\n').split('\n')) {
      if (!raw) { lines.push(''); continue; }
      let cur = '';
      for (const ch of raw) {
        if (probe.measureText(cur + ch).width > W - padding * 2) {
          lines.push(cur);
          cur = ch;
        } else {
          cur += ch;
        }
      }
      if (cur) lines.push(cur);
    }
    if (!lines.length) lines.push('');

    const lineH = Math.round(fontSize * 1.32) + lineSpacing;
    const h = Math.max(lineH * lines.length + padding * 2, lineH);
    const canvas = makeCanvas(W, h);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, W, h);
    ctx.font = font;
    ctx.fillStyle = '#000';
    ctx.textBaseline = 'top';
    lines.forEach((ln, i) => ctx.fillText(ln, padding, padding + i * lineH));

    return { gray: toGray(ctx, W, h), w: W, h };
  }

  /** 图片（dataURL / Image）→ 灰度，等比缩到 384 宽，居中贴白底 */
  function imageToGray(src, opts) {
    opts = opts || {};
    return new Promise((resolve, reject) => {
      const img = src instanceof HTMLImageElement ? src : new Image();
      const done = () => {
        const ratio = W / img.naturalWidth;
        const dw = W;
        const dh = Math.max(1, Math.round(img.naturalHeight * ratio));
        const canvas = makeCanvas(dw, dh);
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, dw, dh);
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(img, 0, 0, dw, dh);
        resolve({ gray: toGray(ctx, dw, dh), w: dw, h: dh });
      };
      if (img.complete && img.naturalWidth) { done(); return; }
      img.onload = done;
      img.onerror = () => reject(new Error('图片解码失败'));
      if (!(src instanceof HTMLImageElement)) img.src = src;
    });
  }

  /** 校准图（与 Python 版布局一致，用于判断方向/丢行） */
  function calibrationGray() {
    const h = 320;
    const canvas = makeCanvas(W, h);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, W, h);
    ctx.fillStyle = '#000';

    // 左上黑方块
    ctx.fillRect(2, 2, 40, 40);
    ctx.font = `28px ${FONT_STACK}`;
    ctx.textBaseline = 'top';
    ctx.fillText('TOP 上', 50, 6);
    ctx.font = `16px ${FONT_STACK}`;
    ctx.fillText('左上应为黑块', 50, 42);

    // 阶梯条 + 行号
    for (let i = 0; i < 8; i++) {
      const y = 76 + i * 18;
      ctx.fillRect(0, y, 24 * (i + 1), 8);
      ctx.font = `16px ${FONT_STACK}`;
      ctx.fillText(`row ${i + 1}`, 240, y - 4);
    }

    // 右侧虚线
    for (let y = 70; y < 230; y += 8) ctx.fillRect(370, y, 10, 3);

    ctx.font = `28px ${FONT_STACK}`;
    ctx.fillText('BOTTOM 下 / 384 dots', 2, 250);
    ctx.font = `16px ${FONT_STACK}`;
    ctx.fillText('1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0', 2, 288);

    return { gray: toGray(ctx, W, h), w: W, h };
  }

  /** 1bpp 裸位图 → dataURL（预览用，放大 scale 倍） */
  /**
   * 补成"整张纸"的样子：上下加固件固定的 11mm / 7mm，左右补到纸宽 57mm。
   * 打印头只有 48mm，两侧 4.5mm 是纸边 —— 预览如实呈现，避免以为被裁掉。
   * 返回 {raw, w, h, top}
   */
  function padWithMargins(raw, w, h, topRows, bottomRows, paperWidth) {
    const srcRow = (w + 7) >> 3;
    const top = topRows == null ? 11 * 8 : topRows;
    const bottom = bottomRows == null ? 7 * 8 : bottomRows;
    const totalW = paperWidth == null ? 456 : paperWidth;
    const left = Math.max(0, (totalW - w) >> 1);
    const dstRow = (totalW + 7) >> 3;
    const out = new Uint8Array(dstRow * (top + h + bottom));
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (raw[y * srcRow + (x >> 3)] & (0x80 >> (x & 7))) {
          const px = left + x;
          out[(top + y) * dstRow + (px >> 3)] |= 0x80 >> (px & 7);
        }
      }
    }
    return { raw: out, w: totalW, h: top + h + bottom, top };
  }

  function rawToDataURL(w, h, raw, scale) {
    scale = scale || 2;
    const rb = (w + 7) >> 3;
    const canvas = makeCanvas(w * scale, h * scale);
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(canvas.width, canvas.height);
    const d = img.data;
    for (let y = 0; y < canvas.height; y++) {
      const sy = (y / scale) | 0;
      for (let x = 0; x < canvas.width; x++) {
        const sx = (x / scale) | 0;
        const bit = raw[sy * rb + (sx >> 3)] & (0x80 >> (sx & 7));
        const p = (y * canvas.width + x) * 4;
        const v = bit ? 0 : 255;
        d[p] = d[p + 1] = d[p + 2] = v;
        d[p + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas.toDataURL('image/png');
  }

  root.MBRender = { W, textToGray, imageToGray, calibrationGray, rawToDataURL, padWithMargins };
})(typeof globalThis !== 'undefined' ? globalThis : this);

/* shared/web/ui.js — 两个网页实现共用的纯 UI 工具（日志/页签/进度/编码转换）
 *
 * 不含任何编码或传输逻辑，只是让两个实现的界面代码短一点。
 * 浏览器：window.MBUI
 */
(function (root) {
  'use strict';

  const $ = (sel) => document.querySelector(sel);

  /** 日志面板：往一个 <pre> 里追加带时间戳的行 */
  function createLogger(el, maxLines) {
    const limit = maxLines || 400;
    return function log(msg, cls) {
      const line = document.createElement('div');
      if (cls) line.className = cls;
      line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
      el.appendChild(line);
      el.scrollTop = el.scrollHeight;
      while (el.childElementCount > limit) el.removeChild(el.firstChild);
    };
  }

  /** 页签：按钮 [data-tab] 控制 .pane#pane-<tab> */
  function initTabs() {
    document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
      document.querySelectorAll('.pane').forEach((x) => x.classList.remove('active'));
      t.classList.add('active');
      const pane = document.getElementById('pane-' + t.dataset.tab);
      if (pane) pane.classList.add('active');
    }));
  }

  function setChip(el, text, cls) {
    if (!el) return;
    el.textContent = text;
    el.className = 'conn' + (cls ? ' ' + cls : '');
  }

  function setProgress(bar, ratio) {
    if (bar) bar.style.width = (Math.max(0, Math.min(1, ratio)) * 100).toFixed(1) + '%';
  }

  /** base64 → Uint8Array */
  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  function hex(bytes, max) {
    const n = max == null ? 24 : max;
    const a = Array.from(bytes.slice(0, n), (b) => b.toString(16).padStart(2, '0')).join(' ');
    return bytes.length > n ? a + ' …' : a;
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      return false;
    }
  }

  /** 屏幕常亮（打印期间别让系统休眠断蓝牙）；不支持就静默失败 */
  async function keepAwake(on) {
    try {
      if (on && 'wakeLock' in navigator) {
        root.__mbWakeLock = await navigator.wakeLock.request('screen');
      } else if (!on && root.__mbWakeLock) {
        await root.__mbWakeLock.release();
        root.__mbWakeLock = null;
      }
    } catch (e) { /* 忽略 */ }
  }

  root.MBUI = { $, createLogger, initTabs, setChip, setProgress, b64ToBytes, hex, copyText, keepAwake };
})(typeof globalThis !== 'undefined' ? globalThis : this);

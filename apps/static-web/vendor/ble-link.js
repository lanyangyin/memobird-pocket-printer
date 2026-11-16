/* shared/web/ble-link.js — BLE 传输层（两个网页实现共用）
 *
 * 只做"连接 + 写字节"，不含任何 UI/编码逻辑：
 *   · 负责 requestDevice / 连接 / 选特征值 / 订阅通知 / 按 MTU 分片写入 / 预热
 *   · 日志通过回调交给各自的页面去渲染
 *
 * 依赖：MBBle（shared/web/ble-util.js）
 *
 * 浏览器：window.MBLink
 */
(function (root, factory) {
  const api = factory(root.MBBle);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MBLink = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (BLE) {
  'use strict';

  if (!BLE) throw new Error('ble-link.js 需要先加载 ble-util.js（MBBle）');

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  const hex = (bytes, max) => {
    const n = max == null ? 24 : max;
    const a = Array.from(bytes.slice(0, n), (b) => b.toString(16).padStart(2, '0')).join(' ');
    return bytes.length > n ? a + ' …' : a;
  };

  function describeFrame(bytes) {
    const f = BLE.parseFrame(bytes);
    if (!f) return '';
    const tlvs = f.tlvs.map((t) => {
      const dec = t.len === 1 ? `(${t.value[0]})` : '';
      return `tag=0x${t.tag.toString(16)} len=${t.len} ${hex(t.value, 12)}${dec}`;
    });
    return ` | cmd=0x${f.cmd.toString(16)}${f.sumOk ? '' : ' (校验和错误!)'} ${tlvs.join(' ; ')}`;
  }

  /**
   * 创建一个打印机连接
   * @param {{log?:Function, deviceNameFilter?:Function}} opts
   */
  function createLink(opts) {
    opts = opts || {};
    const emit = opts.log || function () {};

    const state = {
      device: null,
      server: null,
      writeChr: null,
      notifyChr: null,
      serviceCount: 0,
      charCount: 0,
      connected: false,
    };

    /** 取服务；getPrimaryServices() 没覆盖到的已知服务再单独补问 */
    async function servicesWithFallback(server) {
      let services = [];
      try { services = await server.getPrimaryServices(); } catch (e) { services = []; }
      const have = new Set(services.map((s) => String(s.uuid).toLowerCase()));
      for (const uuid of BLE.OPTIONAL_SERVICES) {
        if (have.has(String(uuid).toLowerCase())) continue;
        try {
          const s = await server.getPrimaryService(uuid);
          if (s) services.push(s);
        } catch (e) { /* 该服务不存在，正常 */ }
      }
      return services;
    }

    /** 连接（失败会抛出带原因的错误，调用方负责提示） */
    async function connect() {
      emit('请求蓝牙设备…（在弹窗里选打印机）');
      state.device = await navigator.bluetooth.requestDevice({
        acceptAllDevices: true,
        optionalServices: BLE.OPTIONAL_SERVICES,
      });
      emit(`选中：${state.device.name || '(无名)'}`, 'ok');

      state.device.addEventListener('gattserverdisconnected', () => {
        state.connected = false;
        state.writeChr = null;
        emit(`设备断开（${state.device ? (state.device.name || state.device.id) : '?'}）`, 'warn');
        if (opts.onDisconnect) opts.onDisconnect(state);
      });

      state.server = await state.device.gatt.connect();
      const services = await servicesWithFallback(state.server);
      const picked = await BLE.pickWrite(services);
      state.serviceCount = services.length;
      state.charCount = picked.all.length;
      emit(`读到 ${services.length} 个服务 / ${picked.all.length} 个特征值`);

      state.writeChr = picked.write;
      state.notifyChr = picked.notify;
      if (!state.writeChr) throw new Error(picked.reason || '没找到可写特征值 —— 用「探测 GATT」把表发我');
      emit(`写入特征值：${state.writeChr.uuid}`, 'ok');

      if (state.notifyChr) {
        try {
          await state.notifyChr.startNotifications();
          state.notifyChr.addEventListener('characteristicvaluechanged', (e) => {
            const v = new Uint8Array(e.target.value.buffer);
            emit(`notify ${v.length}B ${hex(v)}${describeFrame(v)}`, 'hex');
          });
          emit(`通知特征值：${state.notifyChr.uuid}`, 'ok');
        } catch (e) {
          emit('订阅通知失败（不影响打印）：' + (e.message || e), 'warn');
        }
      }

      state.connected = true;
      return state;
    }

    /** 按分片大小写一段字节；write-without-response 失败时自动退回 write */
    async function writeAll(bytes, label, chunk, onProgress) {
      if (!state.writeChr) throw new Error('还没连接打印机');
      const step = Math.max(1, chunk || 20);
      const total = bytes.length;
      let sent = 0;

      for (let i = 0; i < total; i += step) {
        const part = bytes.subarray(i, Math.min(i + step, total));
        try {
          if (state.writeChr.properties.writeWithoutResponse) {
            await state.writeChr.writeValueWithoutResponse(part);
          } else {
            await state.writeChr.writeValue(part);
          }
        } catch (e1) {
          try {
            await state.writeChr.writeValue(part);
          } catch (e2) {
            throw new Error(`写入失败 @${i}/${total}: ${e2.message || e2}`);
          }
        }
        sent += part.length;
        if (onProgress) onProgress(sent / total);
        // 小分片时给协议栈一点空隙，避免写爆缓冲区
        if (step <= 20 && (i / step) % 8 === 0) await sleep(4);
      }
      if (label) emit(`${label} 完成 ${total}B / ${Math.ceil(total / step)} 片`, 'ok');
      return total;
    }

    /**
     * 发一个完整任务
     * @param {{frames:Uint8Array[], meta:object}} job
     */
    async function sendJob(job, label, cfg) {
      cfg = cfg || {};
      const chunk = cfg.chunk || 20;
      if (!state.writeChr) throw new Error('还没连接打印机');

      if (cfg.preheat !== false && job.meta && job.meta.preheat) {
        emit(`预热 ${job.meta.preheat}B`);
        await writeAll(new Uint8Array(job.meta.preheat), '预热', chunk);
        await sleep(120);
      }

      const frames = job.frames;
      emit(`共 ${frames.length} 帧 / ${job.meta ? job.meta.bytes : '?'}B（${job.meta ? job.meta.format : ''}）`);
      const t0 = performance.now();
      for (let i = 0; i < frames.length; i++) {
        await writeAll(frames[i], `帧 ${i + 1}/${frames.length}`, chunk, cfg.onProgress);
        await sleep(cfg.interFrame == null ? 30 : cfg.interFrame);
      }
      emit(`${label || '打印'} 已全部发送（${(performance.now() - t0).toFixed(0)}ms）`, 'ok');
    }

    function disconnect() {
      if (state.device && state.device.gatt && state.device.gatt.connected) {
        state.device.gatt.disconnect();
      }
      state.connected = false;
      state.writeChr = null;
      state.notifyChr = null;
    }

    /** 探测 GATT：返回文本行，供调试页展示 */
    async function dumpGatt() {
      if (!state.server) return [];
      const services = await servicesWithFallback(state.server);
      return BLE.dumpGatt(services);
    }

    return {
      state, connect, disconnect, writeAll, sendJob, dumpGatt,
      servicesWithFallback,
      get connected() { return state.connected; },
    };
  }

  return { createLink, describeFrame, hex };
});

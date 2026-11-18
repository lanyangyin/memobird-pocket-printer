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

    /** 收到的所有通知（query 用） */
    const notifications = [];

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
            notifications.push(v);
            if (notifications.length > 64) notifications.shift();
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
    /**
     * 等固件把这一批数据消化完：ack 帧 cmd=0x04 里
     * tag 0x0B = 总帧数，tag 0x0C = 已收到的序号（1 基）。
     * 只有等它相等，再发收尾帧（0x01）才会真正触发打印。
     */
    async function waitJobAck(fromIndex, timeoutMs) {
      const t0 = Date.now();
      const limit = timeoutMs == null ? 6000 : timeoutMs;
      while (Date.now() - t0 < limit) {
        let total = null;
        let got = null;
        for (let i = fromIndex; i < notifications.length; i++) {
          let p = null;
          try { p = BLE.parseFrame(notifications[i]); } catch (e) { continue; }
          if (!p || p.cmd !== 0x04) continue;
          for (const t of p.tlvs || []) {
            if (t.tag === 0x0b && t.len >= 1) total = t.value[0];
            if (t.tag === 0x0c && t.len >= 1) got = t.value[0];
          }
        }
        if (total != null && got != null) {
          if (total === 0 && got > 0) return { total, got, aborted: true };
          if (got >= total && total > 0) return { total, got };
        }
        await sleep(60);
      }
      return null;
    }

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
      const mark = notifications.length;
      for (let i = 0; i < frames.length; i++) {
        await writeAll(frames[i], `帧 ${i + 1}/${frames.length}`, chunk, cfg.onProgress);
        await sleep(cfg.interFrame == null ? 30 : cfg.interFrame);
      }
      // 关键：等固件确认收完，否则紧接着发的收尾帧会被丢掉（打印不出来）
      const ack = await waitJobAck(mark, cfg.ackTimeout == null ? 8000 : cfg.ackTimeout);
      if (ack && ack.aborted) {
        emit(`固件中止了（只收到 ${ack.got} 帧）—— 大概率缺纸`, 'warn');
      } else if (ack) emit(`固件已收完 ${ack.got}/${ack.total} 帧`, 'ok');
      else emit('没等到固件收完确认 —— 收尾帧可能被忽略', 'warn');
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

    /**
     * 发一帧并收集 waitMs 内的通知回包（读设备信息用）
     * @returns {Promise<Uint8Array[]>}
     */
    async function query(frame, waitMs, chunk) {
      if (!state.writeChr) throw new Error('还没连接打印机');
      const start = notifications.length;
      await writeAll(frame, '', chunk || 20);
      await sleep(waitMs == null ? 1500 : waitMs);
      return notifications.slice(start);
    }

    /** 发任意十六进制帧（底层），返回回包（hex 字符串数组） */
    async function sendHex(hexStr, waitMs) {
      const bytes = BLE.hexToBytes(hexStr);
      const frames = await query(bytes, waitMs == null ? 900 : waitMs);
      return frames.map((f) => BLE.bytesToHex(f));
    }

    /** 列出 GATT 服务/特征值 */
    async function listGatt() {
      return dumpGatt();
    }

    /** 读设备信息（cmd 0x01），返回解析后的对象数组 */
    async function readDeviceInfo(waitMs) {
      const frames = await query(BLE.STATUS_FRAME, waitMs);
      const out = [];
      for (const f of frames) {
        const parsed = BLE.parseStatus(f);
        if (parsed && (parsed.cmd === 0x01 || parsed.cmd === 0x02 || parsed.cmd === 0x0a)) out.push(parsed);
      }
      return out;
    }



    /** 连接已建立后：发现服务、挑特征值、订阅通知 */
    async function setupFromServer(server) {
      const services = await servicesWithFallback(server);
      const picked = await BLE.pickWrite(services);
      state.serviceCount = services.length;
      state.charCount = picked.all.length;
      emit(`读到 ${services.length} 个服务 / ${picked.all.length} 个特征值`);

      state.writeChr = picked.write;
      state.notifyChr = picked.notify;
      if (!state.writeChr) throw new Error(picked.reason || '没找到可写特征值');
      emit(`写入特征值：${state.writeChr.uuid}`, 'ok');

      if (state.notifyChr) {
        try {
          await state.notifyChr.startNotifications();
          state.notifyChr.addEventListener('characteristicvaluechanged', (e) => {
            const dv = e.target.value;
            const bytes = new Uint8Array(dv.buffer, dv.byteOffset, dv.byteLength);
            state.lastNotify = bytes;
            if (opts.onNotify) opts.onNotify(bytes);
          });
        } catch (e) { emit('订阅通知失败：' + (e.message || e), 'warn'); }
      }
      state.connected = true;
      return state;
    }

    /**
     * 重连（不需要再弹选择框）。
     * 实测：固件在"提交打印任务"时会主动断开 BLE，所以每次打印后都要重连。
     */
    async function reconnect() {
      if (!state.device) throw new Error('还没选过设备，先点「连接打印机」');
      emit('打印后固件会断开，正在重连…');
      state.server = await state.device.gatt.connect();
      await setupFromServer(state.server);
      emit('已重连', 'ok');
      return state;
    }

    /** 需要时确保连接可用（断了就重连一次） */
    async function ensureConnected() {
      if (state.connected) return state;
      return reconnect();
    }

    /**
     * 从最近收到的通知（含固件主动推的 0x0A）里读缺纸标志。
     * 缺纸时固件**不回应查询**，只推送，所以必须走这条路。
     * @returns {boolean|null} true=缺纸 / false=有纸 / null=没有状态帧
     */
    function lastPaperOut() {
      return BLE.paperFromFrames(notifications);
    }

    /** 最近一次状态帧里的电压/电量（缺纸时也能拿到，因为固件会推送） */
    function lastBattery() {
      return BLE.batteryFromFrames(notifications);
    }

    /** 读当前打印浓度（tag 0x02），读不到返回 null */
    async function getDensity() {
      const infos = await readDeviceInfo(1200);
      const last = infos[infos.length - 1];
      const f = last && last.fields.find((x) => x.tag === 0x02);
      return f ? f.int : null;
    }

    /** 写打印浓度（1..10）。浓度低 → 打印慢 → 慢速 BLE 下长图才打得完整 */
    async function setDensity(n) {
      await query(BLE.settingFrame(0x02, n), 700);
    }

    /**
     * 开关指示灯（cmd 0x03, tag 0x03 —— 实机验证过因果）
     * @returns {Promise<number|null>} 读回的状态值（1 亮 / 0 灭）
     */
    async function setLed(on, waitMs) {
      const wait = waitMs == null ? 900 : waitMs;
      await query(on ? BLE.LED_ON_FRAME : BLE.LED_OFF_FRAME, wait);
      const infos = await readDeviceInfo(wait + 400);
      const last = infos[infos.length - 1];
      const led = last && last.fields.find((f) => f.tag === 0x03);
      return led ? led.int : null;
    }

    /** 探测 GATT：返回文本行，供调试页展示 */
    async function dumpGatt() {
      if (!state.server) return [];
      const services = await servicesWithFallback(state.server);
      return BLE.dumpGatt(services);
    }

    return {
      state, connect, disconnect, writeAll, sendJob, dumpGatt,
      servicesWithFallback, query, readDeviceInfo, setLed, getDensity, setDensity,
      sendHex, listGatt, reconnect, ensureConnected, lastPaperOut, lastBattery,
      waitJobAck,
      get connected() { return state.connected; },
    };
  }

  return { createLink, describeFrame, hex };
});

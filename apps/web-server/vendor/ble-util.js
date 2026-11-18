/* web/ble-util.js — BLE 侧纯逻辑（无 DOM 依赖，可 Node 单测）
 *
 * 为什么单独拿出来的：Chrome 新旧版本对
 * `BluetoothRemoteGATTService.characteristics` 的支持不一致 ——
 *   · 老实现：同步属性，直接是数组
 *   · 新实现（Chrome 122+ 逐步移除）：只有 async 的 getCharacteristics()
 * 之前代码用了同步属性，在 GT1 上直接抛 `s.characteristics is not iterable`。
 * 这里两种都兼容，并且有单元测试（tests/test_ble_util.js）。
 *
 * 浏览器：window.MBBle
 * Node  ：require('./ble-util.js')
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.MBBle = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const SVC_FF00 = '0000ff00-0000-1000-8000-00805f9b34fb';
  const SVC_FF80 = '0000ff80-0000-1000-8000-00805f9b34fb';
  const SVC_FEE7 = '0000fee7-0000-1000-8000-00805f9b34fb';
  const SVC_ISSC = '49535343-fe7d-4ae5-8fa9-9fafd205e455';
  const SVC_INFO = '0000180a-0000-1000-8000-00805f9b34fb';

  const CHR_WRITE = '0000ff02-0000-1000-8000-00805f9b34fb';
  const CHR_NOTIFY = '0000ff01-0000-1000-8000-00805f9b34fb';
  const CHR_ISSC_WRITE = '49535343-8841-43f4-a8d4-ecbe34729bb3';
  const CHR_ISSC_NOTIFY = '49535343-1e4d-4bd9-ba61-23c647249616';

  /** 请求设备时要用到的服务白名单（Chrome 只允许访问列出来的） */
  const OPTIONAL_SERVICES = [SVC_FF00, SVC_FF80, SVC_FEE7, SVC_ISSC, SVC_INFO];

  const isWritable = (c) => !!(c && c.properties && (c.properties.write || c.properties.writeWithoutResponse));
  const isNotifiable = (c) => !!(c && c.properties && (c.properties.notify || c.properties.indicate));

  /**
   * 把一个 service 的特征值取出来，兼容新旧 Chrome。
   * 取不到就返回空数组（某些服务不允许读，不该让整体失败）。
   */
  async function serviceCharacteristics(service) {
    try {
      if (typeof service.getCharacteristics === 'function') {
        const chars = await service.getCharacteristics();
        return Array.from(chars || []);
      }
    } catch (e) { /* 落到下面的兜底 */ }
    try {
      if (service.characteristics) return Array.from(service.characteristics);
    } catch (e) { /* ignore */ }
    return [];
  }

  /** 展平成 [{ service, chr }] */
  async function collectCharacteristics(services) {
    const all = [];
    for (const s of services || []) {
      const chars = await serviceCharacteristics(s);
      for (const c of chars) all.push({ service: s, chr: c });
    }
    return all;
  }

  /**
   * 挑出写入/通知特征值
   * @returns {{write, notify, all, reason}}
   */
  async function pickWrite(services) {
    const all = await collectCharacteristics(services);
    if (!all.length) {
      return { write: null, notify: null, all, reason: '服务里一个特征值都没读到（可能服务不可读，或设备要求配对）' };
    }
    // 注意：all 里存的是 { service, chr } 包，byUuid 必须返回特征值本身
    const byUuid = (uuid) => {
      const u = String(uuid).toLowerCase();
      const hit = all.find((x) => String(x.chr.uuid).toLowerCase() === u);
      return hit ? hit.chr : null;
    };

    const write = byUuid(CHR_WRITE)
      || byUuid(CHR_ISSC_WRITE)
      || ((all.find((x) => isWritable(x.chr)) || {}).chr || null)
      || null;

    const notify = byUuid(CHR_NOTIFY)
      || byUuid(CHR_ISSC_NOTIFY)
      || ((all.find((x) => isNotifiable(x.chr)) || {}).chr || null)
      || null;

    const reason = write ? '' : `读到 ${all.length} 个特征值，但都不支持写（属性：${
      all.map((x) => `${String(x.chr.uuid).slice(4, 8)}:${Object.entries(x.chr.properties || {})
        .filter(([, v]) => v).map(([k]) => k).join('|') || '-'}`).join(', ')}）`;

    return { write, notify, all, reason };
  }

  /** 解析设备回包（日志用）：AA LEN CMD PAYLOAD SUM */
  function parseFrame(bytes) {
    if (!bytes || bytes.length < 5 || bytes[0] !== 0xaa) return null;
    const len = bytes[1] | (bytes[2] << 8);
    if (bytes.length < 3 + len + 1) return null;
    const cmd = bytes[3];
    const payload = bytes.slice(4, 3 + len);
    const tlvs = [];
    for (let i = 0; i + 3 <= payload.length;) {
      const tag = payload[i];
      const l = payload[i + 1] | (payload[i + 2] << 8);
      const val = payload.slice(i + 3, i + 3 + l);
      tlvs.push({ tag, len: l, value: val });
      i += 3 + l;
    }
    const sum = bytes[3 + len];
    const calc = (0x56 - ((bytes[1] + bytes[2] + cmd + Array.from(payload).reduce((a, b) => a + b, 0)) & 0xff)) & 0xff;
    return { cmd, len, payload, tlvs, sum, sumOk: sum === calc };
  }

  /**
   * 设备状态 TLV 语义 —— 与 memobird_printer/device.py **保持同步**（真机实测结论见那边）
   * confirmed=true 表示因果关系已用肉眼/对照验证过
   */
  const DEVICE_TAGS = {
    0xff: { name: 'magic', label: '固定 0x01', confirmed: false },
    0x01: { name: 'constant_23', label: '恒定 23(非温度非电量)', confirmed: false },
    0x02: { name: 'density', label: '打印浓度(1..10)', confirmed: true },
    0x03: { name: 'led', label: '指示灯', confirmed: true },
    0x04: { name: 'battery_voltage', label: '电池电压(0.05V/LSB)', confirmed: true },
    0x05: { name: 'flag_05', label: '状态位', confirmed: false },
    0x06: { name: 'paper_out', label: '缺纸', confirmed: true },  // 双向验证
    0x0f: { name: 'serial', label: '序列号', confirmed: true },
    0x13: { name: 'flags_13', label: '标志位(重启会变)', confirmed: false },
    0x14: { name: 'counter_14', label: '8 字节计数?', confirmed: false },
  };

  /** "aa 01 00 54" → Uint8Array */
  function hexToBytes(str) {
    const clean = (str || '').replace(/0x/gi, '').replace(/[^0-9a-fA-F]/g, '');
    if (clean.length % 2) throw new Error('十六进制长度必须是偶数');
    const out = new Uint8Array(clean.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
    return out;
  }

  /** Uint8Array → "aa 01 00" */
  function bytesToHex(bytes) {
    return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join(' ');
  }

  /**
   * 从一组通知帧里找**最近一条状态帧**的缺纸标志（tag 0x06）。
   * 缺纸时固件只推送、不回应查询，所以判定必须走这里。
   * @returns {boolean|null} true=缺纸 / false=有纸 / null=没有状态帧
   */
  function paperFromFrames(frames) {
    for (let i = frames.length - 1; i >= 0; i--) {
      let p = null;
      try { p = parseFrame(frames[i]); } catch (e) { continue; }
      if (!p || !p.tlvs) continue;
      if (p.cmd !== 0x0a && p.cmd !== 0x01 && p.cmd !== 0x02) continue;
      for (const t of p.tlvs) {
        if (t.tag === 0x06 && t.len >= 1) return t.value[0] === 1;
      }
    }
    return null;
  }

  /** cmd 0x01：读状态（详版）。校验和已算好：aa 01 00 01 54 */
  const STATUS_FRAME = Uint8Array.from([0xaa, 0x01, 0x00, 0x01, 0x54]);
  /** cmd 0x08：提交/结束任务（不驱动电机，但能让固件把位图打出来） */
  const COMMIT_FRAME = buildFrame(0x08, new Uint8Array(0));

  /** cmd 0x09：读序列号 */
  const SERIAL_FRAME = Uint8Array.from([0xaa, 0x01, 0x00, 0x09, 0x4c]);

  /** 构造一帧：AA | LEN(2LE) | CMD | PAYLOAD | SUM（与 encoder.js 同算法，这里只够用） */
  function buildFrame(cmd, payload) {
    payload = payload || new Uint8Array(0);
    const len = payload.length + 1;
    const body = new Uint8Array(3 + payload.length);
    body[0] = len & 0xff;
    body[1] = (len >> 8) & 0xff;
    body[2] = cmd;
    body.set(payload, 3);
    let sum = 0;
    for (let i = 0; i < body.length; i++) sum += body[i];
    const out = new Uint8Array(body.length + 2);
    out[0] = 0xaa;
    out.set(body, 1);
    out[out.length - 1] = (0x56 - (sum & 0xff)) & 0xff;
    return out;
  }

  /** 单字节 TLV */
  function tlv8(tag, value) {
    return Uint8Array.from([tag, 0x01, 0x00, value & 0xff]);
  }

  /** cmd 0x03 设置帧（tag=设置项，value=值）。已验证：0x03=指示灯，0x02=某设置项 */
  function settingFrame(tag, value) {
    return buildFrame(0x03, tlv8(tag, value));
  }

  const LED_ON_FRAME = settingFrame(0x03, 1);
  const LED_OFF_FRAME = settingFrame(0x03, 0);

  /** 把状态帧解析成 {cmd, serial, fields:[{tag,label,int,ascii,confirmed}]} */
  function parseStatus(bytes) {
    const f = parseFrame(bytes);
    if (!f) return null;
    const out = { cmd: f.cmd, serial: null, fields: [] };
    for (const t of f.tlvs) {
      const meta = DEVICE_TAGS[t.tag] || { name: '?', label: '未知', confirmed: false };
      const isAscii = t.len > 0 && Array.from(t.value).every((b) => b >= 32 && b < 127);
      let int = null;
      if (t.len <= 8) {
        int = 0;
        for (let i = t.value.length - 1; i >= 0; i--) int = int * 256 + t.value[i];
      }
      const ascii = isAscii ? Array.from(t.value, (b) => String.fromCharCode(b)).join('') : null;
      out.fields.push({
        tag: t.tag, len: t.len, name: meta.name, label: meta.label,
        confirmed: meta.confirmed, int, ascii,
      });
      if (t.tag === 0x0f && ascii) out.serial = ascii.replace(/\0+$/, '');
    }
    return out;
  }


  // ---- 电量：0x04 是电池电压（0.05 V/LSB），用锂电静置曲线估算百分比 ----
  const VOLTS_PER_LSB = 0.05;
  const LI_CURVE = [
    [3.30, 0], [3.40, 3], [3.50, 8], [3.60, 14], [3.70, 25],
    [3.75, 35], [3.80, 45], [3.85, 53], [3.90, 60], [3.95, 68],
    [4.00, 75], [4.05, 83], [4.10, 90], [4.15, 96], [4.20, 100],
  ];

  function batteryVoltage(parsed) {
    if (!parsed) return null;
    const f = parsed.fields.find((x) => x.tag === 0x04);
    return f ? +(f.int * VOLTS_PER_LSB).toFixed(2) : null;
  }

  function batteryPercent(parsed) {
    const v = batteryVoltage(parsed);
    if (v == null) return null;
    if (v <= LI_CURVE[0][0]) return 0;
    if (v >= LI_CURVE[LI_CURVE.length - 1][0]) return 100;
    for (let i = 0; i < LI_CURVE.length - 1; i++) {
      const [v1, p1] = LI_CURVE[i];
      const [v2, p2] = LI_CURVE[i + 1];
      if (v >= v1 && v <= v2) return Math.round(p1 + ((p2 - p1) * (v - v1)) / (v2 - v1));
    }
    return null;
  }

  /** 缺纸？（tag 0x06：有纸 0 / 缺纸 1；实机验证过） */
  function paperOut(parsed) {
    if (!parsed) return null;
    const f = parsed.fields.find((x) => x.tag === 0x06);
    return f ? f.int === 1 : null;
  }

  /** 状态 → 人读文本行 */
  function formatStatus(parsed) {
    if (!parsed) return ['（不是合法的设备回包）'];
    const lines = [`cmd=0x${parsed.cmd.toString(16).padStart(2, '0')}`];
    if (parsed.serial) lines.push(`  序列号         : ${parsed.serial}`);
    for (const f of parsed.fields) {
      if (f.tag === 0x0f) continue;
      const val = f.int !== null ? f.int : (f.ascii || '(二进制)');
      lines.push(`  0x${f.tag.toString(16).padStart(2, '0')} ${f.label.padEnd(16)} ${String(val).padEnd(10)}${f.confirmed ? ' ✓' : ''}`);
    }
    return lines;
  }

  /** 把 GATT 树拍成文本（调试页展示/复制用） */
  async function dumpGatt(services) {
    const lines = [];
    for (const s of services || []) {
      lines.push(`service ${s.uuid}`);
      const chars = await serviceCharacteristics(s);
      for (const c of chars) {
        const props = Object.entries(c.properties || {}).filter(([, v]) => v).map(([k]) => k).join(',');
        lines.push(`   chr ${c.uuid}  [${props || '-'}]`);
      }
      if (!chars.length) lines.push('   (读不到特征值)');
    }
    return lines;
  }

  return {
    SVC_FF00, SVC_FF80, SVC_FEE7, SVC_ISSC, SVC_INFO,
    CHR_WRITE, CHR_NOTIFY, CHR_ISSC_WRITE, CHR_ISSC_NOTIFY,
    OPTIONAL_SERVICES,
    serviceCharacteristics, collectCharacteristics, pickWrite, parseFrame, dumpGatt,
    isWritable, isNotifiable,
    // 设备信息（cmd 0x01/0x09）与控制（cmd 0x03）
    DEVICE_TAGS, STATUS_FRAME, SERIAL_FRAME, COMMIT_FRAME, parseStatus, formatStatus, paperOut, batteryVoltage, batteryPercent,
    buildFrame, tlv8, settingFrame, LED_ON_FRAME, LED_OFF_FRAME,
    hexToBytes, bytesToHex, paperFromFrames,
  };
});

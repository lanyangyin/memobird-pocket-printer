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
  };
});

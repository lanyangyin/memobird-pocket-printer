/**
 * tests/test_ble_util.js — BLE 选特征值逻辑的单元测试（不需要真机）
 *
 *   node tests/test_ble_util.js
 *
 * 重点是回归这个真实故障：
 *   Chrome 新版把 BluetoothRemoteGATTService.characteristics（同步属性）移除了，
 *   只留 async getCharacteristics()，老代码直接抛 `s.characteristics is not iterable`。
 */
'use strict';

const path = require('path');
const ble = require(path.join(path.resolve(__dirname, '..'), 'web', 'ble-util.js'));

let pass = 0;
const fails = [];

function check(name, got, want) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g === w) { pass += 1; console.log(`  [OK ] ${name}`); }
  else { fails.push(name); console.log(`  [FAIL] ${name}\n         got  ${g}\n         want ${w}`); }
}

const chr = (uuid, props) => ({ uuid, properties: props || {} });

/** 新版 Chrome：只有 getCharacteristics()，没有 characteristics 属性 */
const svcNew = (uuid, chars) => ({
  uuid,
  getCharacteristics: async () => chars,
});

/** 老版 Chrome / 部分实现：只有同步 characteristics 属性 */
const svcOld = (uuid, chars) => ({ uuid, characteristics: chars });

/** 模拟 GT1 真实形状 */
function gt1(style) {
  const mk = style === 'new' ? svcNew : svcOld;
  return [
    mk(ble.SVC_FF00, [chr(ble.CHR_WRITE, { write: true, writeWithoutResponse: true }), chr(ble.CHR_NOTIFY, { notify: true })]),
    mk('0000180a-0000-1000-8000-00805f9b34fb', [chr('00002a29-0000-1000-8000-00805f9b34fb', { read: true })]),
  ];
}

(async function main() {
  console.log('1) 回归：Chrome 新版只有 getCharacteristics()');
  try {
    const r = await ble.pickWrite(gt1('new'));
    check('write 命中 ff02', r.write && r.write.uuid, ble.CHR_WRITE);
    check('notify 命中 ff01', r.notify && r.notify.uuid, ble.CHR_NOTIFY);
    check('读到 3 个特征值', r.all.length, 3);
  } catch (e) {
    fails.push('新版崩溃');
    console.log('  [FAIL] 新版崩溃：' + e.message);
  }

  console.log('\n2) 兼容：老版只有 characteristics 属性');
  const old = await ble.pickWrite(gt1('old'));
  check('write 命中 ff02', old.write && old.write.uuid, ble.CHR_WRITE);

  console.log('\n3) 两者都没有 → 不崩，给出原因');
  const none = await ble.pickWrite([{ uuid: 'x' }]);
  check('write 为 null', none.write, null);
  check('reason 非空', typeof none.reason === 'string' && none.reason.length > 0, true);

  console.log('\n4) getCharacteristics() 抛错 → 跳过该服务，不中断');
  const mixed = [
    { uuid: 'bad', getCharacteristics: async () => { throw new Error('GATT error'); } },
    svcNew(ble.SVC_FF00, [chr(ble.CHR_WRITE, { write: true })]),
  ];
  const m = await ble.pickWrite(mixed);
  check('仍然找到 ff02', m.write && m.write.uuid, ble.CHR_WRITE);

  console.log('\n5) 非标准 UUID → 退到"任意可写"');
  const custom = await ble.pickWrite([
    svcNew('0000abc0-0000-1000-8000-00805f9b34fb', [chr('0000abc1-0000-1000-8000-00805f9b34fb', { writeWithoutResponse: true })]),
  ]);
  check('选到自定义可写', custom.write && custom.write.uuid, '0000abc1-0000-1000-8000-00805f9b34fb');

  console.log('\n6) ISSC 透传兜底');
  const issc = await ble.pickWrite([
    svcNew(ble.SVC_ISSC, [chr(ble.CHR_ISSC_WRITE, { write: true }), chr(ble.CHR_ISSC_NOTIFY, { notify: true })]),
  ]);
  check('ISSC write', issc.write && issc.write.uuid, ble.CHR_ISSC_WRITE);
  check('ISSC notify', issc.notify && issc.notify.uuid, ble.CHR_ISSC_NOTIFY);

  console.log('\n7) dumpGatt 对两种实现都能出表');
  const t1 = await ble.dumpGatt(gt1('new'));
  const t2 = await ble.dumpGatt(gt1('old'));
  check('新版/老版表相同', t1.join('\n'), t2.join('\n'));
  check('表里含 ff02', t1.some((l) => l.includes(ble.CHR_WRITE)), true);

  console.log('\n8) parseFrame：解析设备回包');
  const f = Buffer.from('aa0500030301000149', 'hex');
  const p = ble.parseFrame(f);
  check('cmd', p.cmd, 3);
  check('tlv 个数', p.tlvs.length, 1);
  check('tlv tag', p.tlvs[0].tag, 3);
  check('校验和正确', p.sumOk, true);
  const bad = Buffer.from('aa0500030301000148', 'hex');
  check('错校验和能识别', ble.parseFrame(bad).sumOk, false);

  console.log();
  if (fails.length) { console.log(`失败 ${fails.length} 项: ${fails}`); process.exit(1); }
  console.log(`全部通过 ✅（${pass} 项）`);
})();

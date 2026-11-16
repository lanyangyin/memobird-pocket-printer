/**
 * tests/test_encoder_js.js — JS 编码器与 Python 实现的逐字节一致性测试
 *
 *   node tests/test_encoder_js.js
 *
 * 夹具由 tools/gen_fixtures.py 用 Python 侧（已验证）的实现生成，
 * 这里用 web/encoder.js + web/gbk.js 重算，要求 **hex 完全相同**。
 */
'use strict';

const path = require('path');
const fs = require('fs');

const ROOT = path.resolve(__dirname, '..');
const enc = require(path.join(ROOT, 'shared', 'web', 'encoder.js'));
const GBK = require(path.join(ROOT, 'shared', 'web', 'gbk.js'));
const fixtures = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures.json'), 'utf8'));

let failed = 0;
let passed = 0;

function check(name, got, want) {
  if (got === want) {
    passed += 1;
    console.log(`  [OK ] ${name}`);
  } else {
    failed += 1;
    console.log(`  [FAIL] ${name}`);
    console.log(`         got  ${String(got).slice(0, 120)}`);
    console.log(`         want ${String(want).slice(0, 120)}`);
  }
}

const hex = (bytes) => Buffer.from(bytes).toString('hex');

/* ---------------------------------------------------------------- 1. 帧 */
console.log('1) 帧构造（cmd + TLV → 整帧 hex）');
for (const c of fixtures.frames) {
  const parts = c.tlv.map(([tag, h]) => enc.tlv(tag, Uint8Array.from(Buffer.from(h, 'hex'))));
  const payload = parts.length ? enc.concat(parts) : new Uint8Array(0);
  check(`${c.name}`, hex(enc.buildFrame(c.cmd, payload)), c.hex);
}

/* ---------------------------------------------------------- 2. 文本任务 */
console.log('\n2) 文本任务（GBK 编码 + 样式 tag + 整帧）');
for (const c of fixtures.text_jobs) {
  const bytes = GBK.encode(c.text.endsWith('\n') ? c.text : c.text + '\n');
  check(`GBK 字节 ${JSON.stringify(c.text.slice(0, 10))}`, hex(bytes), c.gbk_hex);
  const job = enc.buildTextJob(bytes, { bold: c.bold, underline: c.underline, fontSize: c.fontSize });
  check(`整帧 ${JSON.stringify(c.text.slice(0, 10))} (${job.frames.length} 帧)`,
    job.frames.map(hex).join('|'), c.frames_hex.join('|'));
  check(`meta.chunks/bytes`,
    `${job.meta.chunks}/${job.meta.bytes}`,
    `${c.meta.chunks}/${c.meta.bytes}`);
}

/* -------------------------------------------------------------- 3. 抖动 */
console.log('\n3) 抖动（灰度 → 1bpp 裸位图，含浓度档位）');
for (const c of fixtures.dither) {
  const gray = Uint8Array.from(Buffer.from(c.gray_hex, 'hex'));
  const out = enc.ditherToRaw(gray, c.w, c.h, c.mode, c.threshold, c.darken || 0);
  check(`${c.name} ${c.mode} ${c.w}x${c.h} th=${c.threshold} darken=${c.darken || 0}`,
    hex(out.raw), c.raw_hex);
}

/* ---------------------------------------------------------------- 4. BMP */
console.log('\n4) BMP 封装（official / 规范两种都要一致）');
for (const c of fixtures.bmp) {
  const raw = Uint8Array.from(Buffer.from(c.raw_hex, 'hex'));
  const bmp = enc.rawToBmp(c.w, c.h, raw, c.top_down, c.official);
  check(`${c.w}x${c.h} topDown=${c.top_down} official=${c.official} (${bmp.length}B)`,
    hex(bmp), c.bmp_hex);
}

/* ---------------------------------------------------------------- 5. GBK */
console.log('\n5) GBK 码表');
for (const c of fixtures.gbk) {
  check(JSON.stringify(c.text), hex(GBK.encode(c.text)), c.hex);
}
check('emoji 不可编码 → null', String(GBK.encode('hi 😀')), 'null');

/* -------------------------------------------------------------- 6. 任务包 */
console.log('\n6) 完整任务（与 Python job 的帧数与总字节对齐）');
for (const c of fixtures.text_jobs) {
  const job = enc.jobFromText(c.text, GBK.encode);
  check(`jobFromText ${JSON.stringify(c.text.slice(0, 8))}`,
    `${job.frames.length}/${job.meta.bytes}`, `${c.meta.chunks}/${c.meta.bytes}`);
}


/* ------------------------------------------------------ 9. 走纸任务 */
console.log('\n9) 走纸（全白位图，8 点/mm）');
for (const [mm, dots, bytes, chunks] of [[20, 160, 7742, 8], [50, 400, 19262, 19], [1, 8, 446, 1]]) {
  const job = enc.blankJob(mm);
  check(`${mm}mm → ${dots} 点 / ${bytes}B / ${chunks} 帧`,
    `${job.meta.dots}/${job.meta.bytes}/${job.frames.length}`,
    `${dots}/${bytes}/${chunks}`);
}
const tickJob = enc.blankJob(10, { tick: true });
check('tick 会把首个字节置 0x80', tickJob.frames.length > 0, true);

/* ------------------------------------------------------------------ 汇总 */
console.log(`\n通过 ${passed} 项${failed ? `，失败 ${failed} 项` : ''}`);
process.exit(failed ? 1 : 0);

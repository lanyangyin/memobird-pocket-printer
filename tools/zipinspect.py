"""Inspect an APK/ZIP: entry inventory, EOCD, and any bytes appended after the central directory."""
import sys, zipfile, struct, collections

path = sys.argv[1]
data = open(path, 'rb').read()
print('file size:', len(data))

zf = zipfile.ZipFile(path)
infos = zf.infolist()
print('entries:', len(infos))
comp = sum(i.compress_size for i in infos)
raw = sum(i.file_size for i in infos)
print('sum compressed:', comp, ' sum uncompressed:', raw)

# EOCD
idx = data.rfind(b'PK\x05\x06')
print('EOCD offset:', idx)
if idx >= 0:
    eocd = data[idx:idx+22]
    (sig, disk, cd_disk, n_disk, n_total, cd_size, cd_off, clen) = struct.unpack('<IHHHHIIH', eocd)
    print(f'cd_size={cd_size} cd_off={cd_off} comment_len={clen}')
    end = idx + 22 + clen
    print('zip logical end:', end, ' trailing bytes:', len(data) - end)
    # local file records vs central directory offsets
    max_local_end = 0
    for i in infos:
        hdr = data[i.header_offset:i.header_offset+30]
        if hdr[:4] == b'PK\x03\x04':
            fname_len, extra_len = struct.unpack('<HH', hdr[26:30])
            start = i.header_offset + 30 + fname_len + extra_len
            max_local_end = max(max_local_end, start + i.compress_size)
    print('max local entry end:', max_local_end)
    gap = cd_off - max_local_end
    print('gap between last entry and central dir:', gap)
    if gap > 0:
        blob = data[max_local_end:cd_off]
        print('gap head hex:', blob[:64].hex())
        print('gap entropy-ish sample:', blob[:16])

# biggest entries
print('\n-- top 30 entries by compressed size --')
for i in sorted(infos, key=lambda x: -x.compress_size)[:30]:
    print(f'  {i.compress_size:>10} -> {i.file_size:>10}  {i.filename}')

# suspicious names
print('\n-- entries with odd extensions/names --')
odd = collections.Counter()
for i in infos:
    ext = i.filename.rsplit('.', 1)[-1].lower() if '.' in i.filename else '(none)'
    odd[ext] += 1
print(dict(odd.most_common(40)))

import math
def entropy(b):
    if not b: return 0
    c = collections.Counter(b)
    n = len(b)
    return -sum((v/n) * math.log2(v/n) for v in c.values())

print('\n-- high-entropy large entries (>200KB) --')
for i in sorted(infos, key=lambda x: -x.file_size):
    if i.file_size < 200_000:
        continue
    if i.filename.endswith(('.so', '.png', '.jpg', '.webp', '.mp3', '.ttf', '.ttc', '.otf', '.mp4')):
        continue
    try:
        b = zf.read(i.filename)
    except Exception:
        continue
    print(f'  {i.file_size:>10}  H={entropy(b[:200000]):.3f}  {i.filename}')

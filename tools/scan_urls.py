"""Scan every file in a directory tree for URL / host / API-key-ish strings."""
import os, re, sys, json, collections

root = sys.argv[1]
pat_url = re.compile(rb'(?:https?://|wss?://)[A-Za-z0-9\.\-_:/%\?=&@\#\+~]{4,160}')
pat_host = re.compile(rb'\b(?:[a-z0-9][a-z0-9\-]{1,40}\.)+(?:cn|com|net|org|io|cc|tv|me|top|xyz|vip|info|site|club|online)\b')
pat_ip = re.compile(rb'\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b')

urls = collections.Counter()
hosts = collections.Counter()
ips = collections.Counter()

skip_ext = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp3', '.ttf', '.otf', '.ttc', '.so', '.zip', '.mp4'}

for dirpath, dirnames, filenames in os.walk(root):
    for fn in filenames:
        p = os.path.join(dirpath, fn)
        ext = os.path.splitext(fn)[1].lower()
        if ext in skip_ext:
            continue
        try:
            if os.path.getsize(p) > 60 * 1024 * 1024:
                continue
            data = open(p, 'rb').read()
        except OSError:
            continue
        # UTF-16LE strings too
        for chunk in (data, data.replace(b'\x00', b'') if b'\x00' in data[:4096] else b''):
            if not chunk:
                continue
            for m in pat_url.finditer(chunk):
                urls[m.group().decode('utf-8', 'ignore')] += 1
            for m in pat_host.finditer(chunk):
                hosts[m.group().decode('utf-8', 'ignore').lower()] += 1
        for m in pat_ip.finditer(data):
            ips[m.group().decode('utf-8', 'ignore')] += 1

out = {
    'urls': [u for u, c in urls.most_common() if c >= 1],
    'hosts': [[h, c] for h, c in hosts.most_common(300)],
    'ips': [[i, c] for i, c in ips.most_common(300)],
}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scan_urls.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('urls:', len(urls), 'hosts:', len(hosts), 'ips:', len(ips))

kw = ('memobird', 'gugu', 'printer', 'print')
print('\n=== URLS (filtered) ===')
for u, c in urls.most_common():
    if any(k in u.lower() for k in kw):
        print(f'  {c:3d} {u}')
print('\n=== HOSTS (filtered) ===')
for h, c in hosts.most_common():
    if any(k in h for k in kw):
        print(f'  {c:3d} {h}')

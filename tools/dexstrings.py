"""Dump interesting ASCII strings from one or more files and grep them."""
import re, sys

pats = [re.compile(p.encode(), re.I) for p in sys.argv[2:]] if len(sys.argv) > 2 else []
data = open(sys.argv[1], 'rb').read()
# ASCII strings
strings = re.findall(rb'[\x20-\x7e]{4,200}', data)
seen = set()
n = 0
for s in strings:
    t = s.decode('ascii', 'ignore')
    if t in seen:
        continue
    seen.add(t)
    if pats and not any(p.search(s) for p in pats):
        continue
    n += 1
    print(t)
print(f'--- {n} matches / {len(seen)} unique strings ---', file=sys.stderr)

import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
d=ROOT/"dist/data";m=json.loads((d/"catalog.json").read_text())
n=0
for c in m.get("chunks",[]):
    p=d/c
    assert p.exists(),f"Missing {c}"
    rows=json.loads(p.read_text());assert isinstance(rows,list);n+=len(rows)
assert n==m.get("count"),f"Count mismatch: manifest={m.get('count')} chunks={n}"
print(f"OK: {n} public records.")

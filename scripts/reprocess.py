"""Reprocessa XMLs locais sem rede; preserva cursor de coleta e IDs."""
import json
import xml.etree.ElementTree as ET
from harvest import ROOT, NS, parse_record, save_json

directory = ROOT / 'dist/data'
catalog = json.loads((directory / 'articles.json').read_text())
journals = json.loads((directory / 'journals.json').read_text())
rows = {a['id']: a for a in catalog['articles']} if not catalog.get('demo') else {}
for journal in journals:
    for source in sorted((ROOT / 'harvest/raw' / journal['id']).glob('*.xml'), key=lambda p:p.stat().st_mtime):
        xml = ET.fromstring(source.read_bytes())
        for node in xml.findall('o:ListRecords/o:record', NS):
            row = parse_record(node, journal, catalog.get('updated') or '')
            if row and row.get('deleted'):
                rows.pop(row['id'], None)
            elif row:
                rows[row['id']] = row
catalog['articles'] = sorted(rows.values(), key=lambda a:(a['year'],a['id']), reverse=True)
catalog['partial'] = any(s['status'] != 'ok' for s in json.loads((directory/'status.json').read_text()).get('journals',[]))
save_json(directory / 'articles.json', catalog)
print(f'{len(rows)} registros reprocessados.')

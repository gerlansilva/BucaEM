"""Gera lotes pequenos para Cloudflare Pages; não publica traduções na interface."""
import json
from pathlib import Path
from harvest import ROOT, save_json, load_json

FIELDS = 'id journal title authors abstract keywords year language type doi url pdf openAccess oaiIdentifier source harvestedAt'.split()
def publish(root=ROOT):
    directory=root/'dist/data'
    source=root/'harvest/catalog.json.gz'
    if not source.exists():
        source=directory/'articles.json'
    catalog=load_json(source)
    chunks=[]
    for offset in range(0,len(catalog['articles']),500):
        name=f'records-{offset//500:03d}.json'
        rows=[{k:a.get(k) for k in FIELDS} for a in catalog['articles'][offset:offset+500]]
        save_json(directory/name,rows)
        chunks.append(name)
    manifest={k:v for k,v in catalog.items() if k!='articles'}
    manifest.update(chunks=chunks,count=len(catalog['articles']))
    save_json(directory/'catalog.json',manifest)
    for file in directory.glob('records-*.json'):
        if file.name not in chunks:file.unlink()
    print(f'Catálogo público: {manifest["count"]} registros, {len(chunks)} lotes.')
if __name__=='__main__':publish()

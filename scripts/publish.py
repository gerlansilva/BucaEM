"""Generate Cloudflare Pages chunks from the harvested multilingual catalogue."""
import json,gzip
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FIELDS='id journal title titleOriginal titleEn authors institutions abstract abstractOriginal abstractEn keywords keywordsOriginal keywordsEn metadataEnglishStatus year language languageCode type doi url pdf openAccess oaiIdentifier source harvestedAt'.split()
def load_json(path):
    if path.suffix=='.gz':
        with gzip.open(path,'rt',encoding='utf-8') as f:return json.load(f)
    return json.loads(path.read_text(encoding='utf-8'))
def save_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def migrate(a):
    lang=str(a.get('language') or '').lower()
    labels={'português':'Portuguese','portugues':'Portuguese','pt_br':'Portuguese','pt-br':'Portuguese','pt':'Portuguese','por':'Portuguese','inglês':'English','ingles':'English','en':'English','eng':'English','espanhol':'Spanish','es':'Spanish','spa':'Spanish','fra':'French','fr':'French'}
    if lang in labels: a['language']=labels[lang]
    is_en=lang in {'english','inglês','ingles','en','eng'} or lang.startswith('en-')
    title=a.get('title') or ''
    abstract=a.get('abstract') or ''
    kws=a.get('keywords') or []
    a.setdefault('titleOriginal',title)
    a.setdefault('titleEn',title if is_en else '')
    a.setdefault('abstractOriginal',abstract)
    a.setdefault('abstractEn',abstract if is_en else '')
    a.setdefault('keywordsOriginal',kws)
    a.setdefault('keywordsEn',kws if is_en else [])
    a.setdefault('institutions',[])
    a.setdefault('languageCode','en' if is_en else ('pt' if 'portugu' in lang else ('es' if 'espan' in lang or 'span' in lang else '')))
    a.setdefault('metadataEnglishStatus','source' if is_en else 'pending_translation')
    return a
def publish(root=ROOT):
    directory=root/'dist/data'; source=root/'harvest/catalog.json.gz'
    if not source.exists():source=directory/'articles.json'
    catalog=load_json(source); catalog['articles']=[migrate(a) for a in catalog['articles']]
    chunks=[]
    for offset in range(0,len(catalog['articles']),500):
        name=f'records-{offset//500:03d}.json'; rows=[{k:a.get(k) for k in FIELDS} for a in catalog['articles'][offset:offset+500]]
        save_json(directory/name,rows); chunks.append(name)
    manifest={k:v for k,v in catalog.items() if k!='articles'};manifest.update(chunks=chunks,count=len(catalog['articles']))
    save_json(directory/'catalog.json',manifest)
    for file in directory.glob('records-*.json'):
        if file.name not in chunks:file.unlink()
    print(f'Public catalog: {manifest["count"]} records, {len(chunks)} chunks.')
if __name__=='__main__':publish()

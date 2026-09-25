import json,gzip
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FIELDS='id journal title titleOriginal titleEn authors institutions abstract abstractOriginal abstractEn keywords keywordsOriginal keywordsEn metadataEnglishStatus year language languageCode type doi url pdf openAccess oaiIdentifier source provenance scieloUrl harvestedAt'.split()
def load_json(p):
    if p.suffix=='.gz':
        with gzip.open(p,'rt',encoding='utf-8') as f:return json.load(f)
    return json.loads(p.read_text(encoding='utf-8'))
def save_json(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def migrate(a):
    a=dict(a);lang=str(a.get('language') or a.get('languageCode') or '').lower()
    is_en=lang in {'english','en','eng'} or lang.startswith('en-');title=a.get('title') or '';abstract=a.get('abstract') or '';k=a.get('keywords') or []
    a.setdefault('titleOriginal',title);a.setdefault('titleEn',title if is_en else '')
    a.setdefault('abstractOriginal',abstract);a.setdefault('abstractEn',abstract if is_en else '')
    a.setdefault('keywordsOriginal',k);a.setdefault('keywordsEn',k if is_en else []);a.setdefault('institutions',[])
    a.setdefault('metadataEnglishStatus','source' if (is_en or a.get('titleEn') or a.get('abstractEn') or a.get('keywordsEn')) else 'pending_translation')
    a.setdefault('provenance',[a.get('source')] if a.get('source') else []);return a
def merge(*groups):
    merged={};dois={};oais={}
    for group in groups:
        for x0 in group:
            x=dict(x0);aid=x.get('id')
            if not aid:continue
            doi=str(x.get('doi') or '').strip().lower();oai=str(x.get('oaiIdentifier') or '').strip()
            eid=dois.get(doi) if doi else None
            if not eid and oai:eid=oais.get(oai)
            if eid:
                old=merged[eid]
                preferred={'titleEn','abstractEn','keywordsEn','titleOriginal','abstractOriginal','keywordsOriginal','authors','url','pdf','language','languageCode','oaiIdentifier'}
                for k,v in x.items():
                    if v not in (None,'',[],{}) and (k in preferred or old.get(k) in (None,'',[],{})):old[k]=v
                pr=[]
                for p in (old.get('provenance') or [])+(x.get('provenance') or []):
                    if p and p not in pr:pr.append(p)
                old['provenance']=pr;old['source']='; '.join(pr);continue
            merged[aid]=x
            if doi:dois[doi]=aid
            if oai:oais[oai]=aid
    return list(merged.values())
def publish(root=ROOT):
    d=root/'dist/data';main=root/'harvest/catalog.json.gz'
    if not main.exists():main=d/'articles.json'
    base=load_json(main) if main.exists() else {'articles':[]}
    groups=[base.get('articles',[])]
    for p in [root/'harvest/backfile_catalog.json',root/'harvest/ojs_catalog.json']:
        try:groups.append(load_json(p).get('articles',[]) if p.exists() else [])
        except Exception:groups.append([])
    articles=[migrate(x) for x in merge(*groups)];articles.sort(key=lambda a:(a.get('year') or 0,a.get('id') or ''),reverse=True)
    chunks=[]
    for off in range(0,len(articles),500):
        name=f'records-{off//500:03d}.json';save_json(d/name,[{k:a.get(k) for k in FIELDS} for a in articles[off:off+500]]);chunks.append(name)
    manifest={k:v for k,v in base.items() if k!='articles'};manifest.update(chunks=chunks,count=len(articles));save_json(d/'catalog.json',manifest)
    for f in d.glob('records-*.json'):
        if f.name not in chunks:f.unlink()
    print(f'Public catalog: {len(articles)} records')
if __name__=='__main__':publish()

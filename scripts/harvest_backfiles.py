#!/usr/bin/env python3
"""BuscaEM complete backfile harvester.

Goal: exhaust each configured journal, not sample it.
Priority:
  1) configured OAI-PMH / SciELO official adapters
  2) Crossref journal backfile (publisher deposits)
  3) publisher landing page enrichment per DOI
OpenAlex is never used as the bibliographic authority here.

The script is resumable and writes raw pages before normalization so every field
can be audited. It never marks a journal complete unless the source itself is
exhausted without errors.
"""
from __future__ import annotations

import argparse, hashlib, json, re, subprocess, sys, time, unicodedata, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from official_metadata import normalize_crossref, parse_publisher_html, normalize_doi, _request

CROSSREF = "https://api.crossref.org"


def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def norm(s):
    s = unicodedata.normalize("NFKD", clean(s)).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def load(path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def fetch_json(url, timeout=90):
    raw = _request(url, accept="application/json", timeout=timeout, retries=5)
    return raw, json.loads(raw)


def journal_candidates(title):
    q = urllib.parse.quote(title)
    raw, data = fetch_json(f"{CROSSREF}/journals?query={q}&rows=20")
    return data.get("message", {}).get("items", [])


def score_candidate(title, candidate):
    target = norm(title)
    names = [candidate.get("title", "")]
    for k in ("publisher",):
        if candidate.get(k): names.append(candidate[k])
    best = 0.0
    ta = set(target.split())
    for n in names:
        nb = set(norm(n).split())
        if not ta or not nb: continue
        inter = len(ta & nb)
        score = 2*inter/(len(ta)+len(nb))
        if norm(n) == target: score = 1.0
        best=max(best,score)
    return best


def resolve_crossref_journal(journal, registry):
    jid=journal['id']
    cached=registry.get(jid,{})
    if cached.get('issn'):
        return cached
    cands=journal_candidates(journal['name'])
    ranked=sorted(((score_candidate(journal['name'],c),c) for c in cands), reverse=True, key=lambda x:x[0])
    if not ranked or ranked[0][0] < .72:
        raise RuntimeError(f"Crossref journal identity unresolved for {journal['name']}")
    score,c=ranked[0]
    issns=c.get('ISSN') or []
    if not issns: raise RuntimeError('Crossref candidate has no ISSN')
    out={'issn':issns[0],'issns':issns,'title':c.get('title',''),'publisher':c.get('publisher',''),'matchScore':score,'resolvedAt':datetime.now(timezone.utc).isoformat()}
    registry[jid]=out
    return out


def date_parts(message):
    parts=(((message.get('published-print') or message.get('published-online') or message.get('issued') or {}).get('date-parts') or [[]])[0])
    return '-'.join(map(str,parts)) if parts else ''


def record_from_crossref(item,journal):
    c=normalize_crossref(item)
    doi=normalize_doi(c.get('doi'))
    if not doi or not c.get('title'): return None
    lang=(c.get('languageCode') or '').split('-')[0]
    kws=c.get('keywords') or []
    rid=hashlib.sha256((journal['id']+'|doi|'+doi.lower()).encode()).hexdigest()[:24]
    return {
      'id':rid,'journal':journal['id'],
      'title':c['title'],'titleOriginal':c['title'],'titleEn':c['title'] if lang=='en' else '',
      'titles':[c['title']],'titleVariants':[{'text':c['title'],'lang':lang}],
      'authors':c.get('authors') or [],'contributors':[],'institutions':[],
      'abstract':c.get('abstract') or '', 'abstractOriginal':c.get('abstract') or '', 'abstractEn':(c.get('abstract') or '') if lang=='en' else '',
      'abstracts':[c['abstract']] if c.get('abstract') else [], 'abstractVariants':([{'text':c['abstract'],'lang':lang}] if c.get('abstract') else []),
      'keywords':kws,'keywordsOriginal':kws,'keywordsEn':kws if lang=='en' else [],'keywordVariants':[{'text':x,'lang':lang} for x in kws],
      'metadataEnglishStatus':'source' if lang=='en' else 'pending_translation',
      'year':c.get('year') or 0,'dates':[c.get('date')] if c.get('date') else [],
      'language':{'en':'English','pt':'Portuguese','es':'Spanish','fr':'French','de':'German'}.get(lang,lang),'languageCode':lang,'languages':[lang] if lang else [],
      'type':item.get('type') or 'journal-article','types':[item.get('type') or 'journal-article'],
      'doi':doi,'url':c.get('url') or ('https://doi.org/'+doi),'pdf':'','volume':c.get('volume') or '', 'issue':c.get('issue') or '', 'pages':c.get('pages') or '',
      'rights':[], 'openAccess':None,
      'source':'Crossref publisher deposit','provenance':['Crossref publisher deposit'],'metadataAuthority':'crossref','harvestedAt':datetime.now(timezone.utc).isoformat()
    }


def enrich_official(record,journal,delay=.15):
    doi=record.get('doi')
    if not doi: return record
    url=record.get('url') or 'https://doi.org/'+doi
    try:
        raw=_request(url,accept='text/html,application/xhtml+xml',timeout=60,retries=3)
        base=ROOT/'harvest/raw'/journal['id']/'official'
        base.mkdir(parents=True,exist_ok=True)
        (base/(hashlib.sha256(doi.encode()).hexdigest()[:24]+'.html')).write_bytes(raw)
        p=parse_publisher_html(raw,url)
        # Official page wins when it actually exposes a field.
        mapping={'title':'titleOriginal','authors':'authors','abstract':'abstractOriginal','keywords':'keywordsOriginal','volume':'volume','issue':'issue','pages':'pages','pdf':'pdf','url':'url','year':'year','languageCode':'languageCode'}
        for src,dst in mapping.items():
            v=p.get(src)
            if v not in (None,'',[],0): record[dst]=v
        if p.get('title'):
            record['title']=p['title']; record['titles']=[p['title']]; record['metadataAuthority']='publisher'
        if p.get('abstract'):
            record['abstract']=p['abstract']; record['abstracts']=[p['abstract']]
        if p.get('keywords'):
            record['keywords']=p['keywords']
        record['provenance']=['Publisher landing page','Crossref publisher deposit']; record['source']='; '.join(record['provenance'])
    except Exception as exc:
        record['publisherMetadataError']=str(exc)
    if delay: time.sleep(delay)
    return record


def crossref_backfile(journal, registry, state, records, enrich, max_pages=0):
    jid=journal['id']; ident=resolve_crossref_journal(journal,registry); issn=ident['issn']
    st=state.setdefault(jid,{}).setdefault('crossref',{})
    cursor=st.get('cursor') or '*'; page=int(st.get('pages',0)); complete=False; processed=0
    while True:
        if max_pages and processed>=max_pages: break
        params={'rows':'1000','cursor':cursor,'filter':'type:journal-article'}
        url=f"{CROSSREF}/journals/{urllib.parse.quote(issn)}/works?"+urllib.parse.urlencode(params)
        raw,data=fetch_json(url,timeout=120)
        message=data.get('message',{}); items=message.get('items') or []
        outdir=ROOT/'harvest/raw'/jid/'crossref-backfile'; outdir.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256(raw).hexdigest(); (outdir/f'{page:06d}-{digest[:16]}.json').write_bytes(raw)
        for item in items:
            rec=record_from_crossref(item,journal)
            if not rec: continue
            if enrich: rec=enrich_official(rec,journal)
            records[rec['id']]=rec
        next_cursor=message.get('next-cursor') or ''
        page+=1; processed+=1
        st.update({'cursor':next_cursor,'pages':page,'itemsSeen':st.get('itemsSeen',0)+len(items),'lastRun':datetime.now(timezone.utc).isoformat(),'complete':False,'issn':issn})
        save(ROOT/'harvest/backfile_state.json',state); save(ROOT/'harvest/source_registry.json',registry)
        save(ROOT/'harvest/backfile_catalog.json',{'articles':list(records.values())})
        if len(items)<1000 or not next_cursor or next_cursor==cursor:
            complete=True; break
        cursor=next_cursor
    st['complete']=complete; st['completedAt']=datetime.now(timezone.utc).isoformat() if complete else st.get('completedAt')
    return {'id':jid,'method':'crossref+publisher' if enrich else 'crossref','complete':complete,'pagesThisRun':processed,'itemsSeen':st.get('itemsSeen',0),'issn':issn}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--journal', help='comma-separated ids; default all enabled journals')
    ap.add_argument('--max-pages',type=int,default=0,help='0 = exhaust source; positive = checkpointed batch')
    ap.add_argument('--no-official-enrichment',action='store_true',help='skip DOI landing-page enrichment (Crossref publisher deposit remains canonical fallback)')
    ap.add_argument('--crossref-only',action='store_true',help='use Crossref for every selected journal; otherwise configured OAI/SciELO should be run first by collect_all.sh')
    args=ap.parse_args()
    journals=load(ROOT/'dist/data/journals.json',[])
    wanted=set(args.journal.split(',')) if args.journal else None
    selected=[j for j in journals if j.get('enabled') and (wanted is None or j['id'] in wanted)]
    registry=load(ROOT/'harvest/source_registry.json',{})
    state=load(ROOT/'harvest/backfile_state.json',{})
    catalog=load(ROOT/'harvest/backfile_catalog.json',{'articles':[]})
    records={a['id']:a for a in catalog.get('articles',[]) if a.get('id')}
    status=load(ROOT/'harvest/FULL_BACKFILE_STATUS.json',{'generatedAt':'','journals':{}})
    for j in selected:
        try:
            rep=crossref_backfile(j,registry,state,records,not args.no_official_enrichment,args.max_pages)
        except Exception as exc:
            rep={'id':j['id'],'method':'crossref','complete':False,'error':str(exc)}
        status['journals'][j['id']]=rep; status['generatedAt']=datetime.now(timezone.utc).isoformat(); save(ROOT/'harvest/FULL_BACKFILE_STATUS.json',status)
        print(json.dumps(rep,ensure_ascii=False))
    save(ROOT/'harvest/source_registry.json',registry); save(ROOT/'harvest/backfile_state.json',state); save(ROOT/'harvest/backfile_catalog.json',{'articles':list(records.values())})

if __name__=='__main__': main()

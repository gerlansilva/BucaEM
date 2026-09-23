"""OpenAlex discovery adapter for BuscaEM.

IMPORTANT: OpenAlex is not a canonical metadata source in BuscaEM.
It is used to discover DOIs belonging to a journal and to attach citation metrics.
Every public record is resolved from the publisher landing page and/or Crossref
publisher deposit before entering the catalog.
"""
from __future__ import annotations
import hashlib, json, os, re, subprocess, time, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from official_metadata import canonical_record_from_doi, normalize_doi

BASE='https://api.openalex.org'

def _get_json(path, params, *, timeout=60):
    params=dict(params)
    key=os.getenv('OPENALEX_API_KEY','').strip()
    if key: params['api_key']=key
    url=BASE+path+'?'+urllib.parse.urlencode(params, doseq=True)
    last=None
    for attempt in range(4):
        try:
            p=subprocess.run(['curl','--fail','--location','--silent','--show-error','--max-time',str(timeout),'--connect-timeout','15','--proto','=https','--proto-redir','=https','--user-agent','BuscaEM/4.3 (DOI discovery only)',url],capture_output=True,timeout=timeout+5)
            if p.returncode: raise OSError(p.stderr.decode(errors='replace').strip())
            return json.loads(p.stdout), p.stdout
        except Exception as exc:
            last=exc
            if attempt<3: time.sleep(2**attempt)
    raise RuntimeError(str(last))

def _norm(s):
    import unicodedata
    s=unicodedata.normalize('NFKD',(s or '').casefold())
    s=''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]+',' ',s).strip()

def resolve_source(journal):
    if journal.get('openalexId'):
        return journal['openalexId'].split('/')[-1], {'id':journal['openalexId']}
    query=journal.get('openalexQuery') or journal['name'].split('—')[0].strip()
    data,_=_get_json('/sources',{'search':query,'per_page':25})
    candidates=data.get('results') or []
    targets=[_norm(x) for x in [journal.get('openalexName'), journal.get('name'), query] if x]
    for c in candidates:
        if _norm(c.get('display_name')) in targets:
            return c['id'].split('/')[-1], c
    for c in candidates:
        cn=_norm(c.get('display_name'))
        if any(t and (cn in t or t in cn) for t in targets):
            return c['id'].split('/')[-1], c
    raise RuntimeError(f"OpenAlex source não resolvida com segurança para {journal['name']}")

def harvest_journal(journal,root:Path,*,max_pages=0,full=False,cursor=None):
    now=datetime.now(timezone.utc).isoformat()
    source_id,source=resolve_source(journal)
    archive=root/'harvest/raw'/journal['id']/'openalex-discovery'; archive.mkdir(parents=True,exist_ok=True)
    queue_dir=root/'harvest/discovery'; queue_dir.mkdir(parents=True,exist_ok=True)
    current='*' if full or not cursor else cursor
    rows=[]; pages=0; total=None; next_cursor=current; skipped_no_doi=0; canonical_errors=[]; discovered=[]
    while current:
        params={
          'filter':f'primary_location.source.id:{source_id}',
          'per_page':100,'cursor':current,
          'select':'id,doi,publication_year,publication_date,primary_location,open_access,cited_by_count'
        }
        data,raw=_get_json('/works',params)
        pages+=1
        (archive/(f'{pages:05d}-'+hashlib.sha256(raw).hexdigest()[:16]+'.json')).write_bytes(raw)
        total=(data.get('meta') or {}).get('count',total)
        for work in data.get('results') or []:
            oid=(work.get('id') or '').split('/')[-1]
            doi=normalize_doi(work.get('doi'))
            item={
                'provider':'OpenAlex','openalexId':work.get('id'),'doi':doi,
                'year':work.get('publication_year'),'citedByCount':work.get('cited_by_count',0),
                'openAccess':(work.get('open_access') or {}).get('is_oa'),
                'journal':journal['id'],'discoveredAt':now,
            }
            discovered.append(item)
            if not doi:
                skipped_no_doi+=1
                continue
            try:
                row=canonical_record_from_doi(doi,journal,root,discovery=item)
                rows.append(row)
            except Exception as exc:
                canonical_errors.append({'doi':doi,'openalexId':work.get('id'),'error':str(exc)})
        next_cursor=(data.get('meta') or {}).get('next_cursor')
        if not data.get('results') or not next_cursor: break
        current=next_cursor
        if max_pages and pages>=max_pages: break
        time.sleep(.15)
    # Discovery queue is auditable and separate from the public catalog.
    qfile=queue_dir/(journal['id']+'.json')
    qfile.write_text(json.dumps({'journal':journal['id'],'updated':now,'items':discovered,'canonicalErrors':canonical_errors},ensure_ascii=False,indent=2))
    partial=bool(next_cursor and max_pages and pages>=max_pages)
    report={
        'adapter':'openalex-discovery+official-metadata','status':'partial' if partial else 'ok',
        'attemptedAt':now,'sourceId':source_id,'sourceName':source.get('display_name') or journal['name'],
        'responseTotal':total,'discovered':len(discovered),'processed':len(rows),'skippedNoDoi':skipped_no_doi,
        'canonicalErrors':len(canonical_errors),'pages':pages,
        'cursor':next_cursor if partial else '',
        'metadataPolicy':'Publisher landing page > Crossref publisher deposit; OpenAlex discovery/metrics only'
    }
    return rows,report

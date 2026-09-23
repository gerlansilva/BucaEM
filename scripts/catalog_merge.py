"""Catalog record merge/dedup helpers shared by ingestion adapters."""
from __future__ import annotations
import json
import re


def normalized_title_key(value):
    value = re.sub(r'[^a-z0-9]+', ' ', (value or '').casefold())
    return re.sub(r'\s+', ' ', value).strip()


def merge_source_record(old, new):
    """Enrich a stable record without discarding source provenance."""
    merged = dict(old)
    old_sources = old.get('provenance') or ([old.get('source')] if old.get('source') else [])
    new_sources = new.get('provenance') or ([new.get('source')] if new.get('source') else [])
    merged['provenance'] = list(dict.fromkeys([x for x in old_sources + new_sources if x]))
    for key in ('doi','url','pdf','openAccess','titleEn','abstractEn','metadataEnglishStatus','harvestedAt','scieloUrl'):
        if new.get(key) not in (None, '', []):
            merged[key] = new[key]
    for key in ('titleOriginal','abstractOriginal','language','languageCode','type','year'):
        if merged.get(key) in (None, '', 0, 'Not informed') and new.get(key) not in (None, '', 0):
            merged[key] = new[key]
    for key in ('authors','institutions','keywordsOriginal','keywordsEn','keywords','titles','abstracts','dates','languages','types'):
        vals=[]
        for seq in (merged.get(key) or [], new.get(key) or []):
            if isinstance(seq, list): vals.extend(seq)
        if vals:
            merged[key] = list(dict.fromkeys(vals))
    for key in ('titleVariants','abstractVariants','keywordVariants'):
        vals=[]; seen=set()
        for seq in (merged.get(key) or [], new.get(key) or []):
            if not isinstance(seq,list): continue
            for item in seq:
                sig=json.dumps(item,ensure_ascii=False,sort_keys=True)
                if sig not in seen:
                    seen.add(sig); vals.append(item)
        if vals: merged[key]=vals
    merged['title'] = merged.get('titleEn') or merged.get('titleOriginal') or merged.get('title') or ''
    merged['abstract'] = merged.get('abstractEn') or merged.get('abstractOriginal') or merged.get('abstract') or ''
    merged['keywords'] = merged.get('keywordsEn') or merged.get('keywordsOriginal') or merged.get('keywords') or []
    merged['source'] = '; '.join(merged.get('provenance', []))
    return merged


def integrate_records(records, incoming):
    """Deduplicate an adapter batch by DOI, then journal/year/title when DOI is absent."""
    doi_index={}
    title_index={}
    for rid,row in records.items():
        doi=(row.get('doi') or '').strip().lower()
        if doi: doi_index[(row.get('journal'),doi)] = rid
        title=normalized_title_key(row.get('titleOriginal') or row.get('title'))
        if title and row.get('year'):
            title_index[(row.get('journal'),row.get('year'),title)] = rid
    added=merged_count=0
    for row in incoming:
        doi=(row.get('doi') or '').strip().lower()
        title=normalized_title_key(row.get('titleOriginal') or row.get('title'))
        rid = doi_index.get((row.get('journal'),doi)) if doi else None
        if not rid and title and row.get('year'):
            rid = title_index.get((row.get('journal'),row.get('year'),title))
        if rid:
            records[rid]=merge_source_record(records[rid],row)
            merged_count+=1
        else:
            records[row['id']]=row
            rid=row['id']; added+=1
        if doi: doi_index[(row.get('journal'),doi)] = rid
        if title and row.get('year'): title_index[(row.get('journal'),row.get('year'),title)] = rid
    return added, merged_count

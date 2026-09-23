"""OAI-PMH -> catálogo estático. Python 3.11+ e curl."""
import argparse
import hashlib
import html
import json
import gzip
import re
import time
import itertools
import threading
import subprocess
from functools import lru_cache
from lingua import Language, LanguageDetectorBuilder
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = {'o': 'http://www.openarchives.org/OAI/2.0/', 'dc': 'http://purl.org/dc/elements/1.1/'}

DETECTOR = LanguageDetectorBuilder.from_languages(Language.PORTUGUESE, Language.ENGLISH, Language.SPANISH, Language.FRENCH).with_minimum_relative_distance(0.1).build()

@lru_cache(maxsize=50000)
def portuguese_text(value, declared=''):
    """Display only Portuguese; the detector catches mislabeled publisher data."""
    lang = declared.lower().replace('_', '-')
    if lang and not (lang.startswith('pt') or lang == 'por'):
        return False
    if lang and (value in {'BNCC','EJA','TDIC','TIC','STEM','STEAM','PNAIC','PCN','PIBID','ENEM','ENADE','PNLD','MTSK','TPACK'} or value.lower() in {'geogebra', 'scratch', 'tinkercad', 'minecraft', 'minecraft education', 'álgebra', 'geometria'}):
        return True
    return DETECTOR.detect_language_of(value) == Language.PORTUGUESE

def portuguese_fields(dc, name):
    result = []
    for e in dc.findall('.//dc:' + name, NS):
        text = clean(''.join(e.itertext()))
        text = re.split(r'\b(?:Abstract|Keywords|Key words|Resumen|Palabras clave|Résumé)\b\s*[:：]?', text, flags=re.I)[0].strip()
        declared = e.attrib.get('{http://www.w3.org/XML/1998/namespace}lang', '')
        # Classify each keyword separately, even in a mixed-language subject.
        for value in (re.split(r';|[-–—]{3,}|\.\s+(?=[A-ZÁÉÍÓÚÇ])', text) if name == 'subject' else [text]):
            value = value.strip()
            if value and portuguese_text(value, declared):
                result.append(value)
    return list(dict.fromkeys(result))

def clean(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', html.unescape(value or ''))).strip()


def declared_language(element, text=''):
    declared = element.attrib.get('{http://www.w3.org/XML/1998/namespace}lang', '').lower().replace('_','-')
    aliases = {'por':'pt','pt-br':'pt','pt':'pt','eng':'en','en-us':'en','en-gb':'en','en':'en','spa':'es','es':'es','fra':'fr','fr':'fr','deu':'de','ger':'de','de':'de'}
    if declared:
        base=declared.split('-')[0]
        return aliases.get(declared, aliases.get(base, base))
    detected = DETECTOR.detect_language_of(text) if text else None
    return {Language.PORTUGUESE:'pt',Language.ENGLISH:'en',Language.SPANISH:'es',Language.FRENCH:'fr'}.get(detected,'')

def multilingual_fields(dc, name, split_subject=False):
    out=[]
    for e in dc.findall('.//dc:'+name, NS):
        raw=clean(''.join(e.itertext()))
        if not raw: continue
        values = re.split(r';|[-–—]{3,}', raw) if split_subject else [raw]
        for value in values:
            value=value.strip()
            if value:
                out.append({'text':value,'lang':declared_language(e,value)})
    seen=set(); result=[]
    for item in out:
        key=(item['text'],item['lang'])
        if key not in seen:
            seen.add(key); result.append(item)
    return result

def pick_language(items, lang):
    return next((x['text'] for x in items if x.get('lang')==lang and x.get('text')), '')

def parse_xml(raw):
    # OJS occasionally emits XML 1.0 forbidden control characters from Word.
    # Keep the raw file unchanged; replace only these invalid bytes for parsing.
    return ET.fromstring(re.sub(rb'[\x00-\x08\x0b\x0c\x0e-\x1f]', b' ', raw))

def get_xml(endpoint, params):
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in ('https', 'http'):
        raise ValueError('Endpoint deve usar HTTP(S)')
    url = endpoint + ('&' if '?' in endpoint else '?') + urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):
        try:
            response = subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--max-time', '60', '--connect-timeout', '15', '--max-filesize', '20000000', '--proto', '=https,http', '--proto-redir', '=https,http', '--user-agent', 'BuscaEM/2.0 (OAI-PMH metadata harvester)', '--header', 'Accept: application/xml,text/xml', url], capture_output=True, timeout=65)
            if response.returncode:
                raise OSError(response.stderr.decode(errors='replace').strip())
            raw = response.stdout
            if len(raw) > 20_000_000:
                raise ValueError('Resposta excede 20 MB; ajustar lote na fonte')
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                raise ValueError('DTD e entidades XML não permitidas')
            xml = parse_xml(raw)
            if xml.tag != '{http://www.openarchives.org/OAI/2.0/}OAI-PMH':
                raise ValueError('A resposta não é OAI-PMH válido')
            errors = xml.findall('o:error', NS)
            for error in errors:
                if error.attrib.get('code') != 'noRecordsMatch':
                    raise ValueError(f"OAI-PMH {error.attrib.get('code')}: {error.text}")
            if not errors and xml.find('o:' + params['verb'], NS) is None:
                raise ValueError('Resposta OAI-PMH sem o resultado solicitado')
            return xml, raw
        except (OSError, ValueError, ET.ParseError, subprocess.TimeoutExpired) as exc:
            last = exc
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
    raise RuntimeError(str(last))

def parse_record(node, journal, now):
    header = node.find('o:header', NS)
    if header is None:
        return None
    identifier = header.findtext('o:identifier', '', NS)
    if not identifier:
        return None
    item_id = hashlib.sha256((journal['id'] + '|' + identifier).encode()).hexdigest()[:24]
    if header.attrib.get('status') == 'deleted':
        return {'id': item_id, 'deleted': True}
    dc = node.find('o:metadata', NS)
    if dc is None:
        return None
    def fields(name):
        return list(dict.fromkeys(clean(''.join(e.itertext())) for e in dc.findall('.//dc:' + name, NS) if clean(''.join(e.itertext()))))
    titles_ml = multilingual_fields(dc,'title')
    abstracts_ml = multilingual_fields(dc,'description')
    keywords_ml = multilingual_fields(dc,'subject',split_subject=True)
    title_en = pick_language(titles_ml,'en')
    title_original = titles_ml[0]['text'] if titles_ml else ''
    if not title_original:
        return None
    abstract_en = pick_language(abstracts_ml,'en')
    abstract_original = abstracts_ml[0]['text'] if abstracts_ml else ''
    keywords_en = list(dict.fromkeys(x['text'] for x in keywords_ml if x.get('lang')=='en'))
    keywords_original = list(dict.fromkeys(x['text'] for x in keywords_ml))
    # English fields are source-derived only. Missing translations remain explicit pending values.
    display_title = title_en or title_original
    display_abstract = abstract_en or abstract_original
    display_keywords = keywords_en or keywords_original
    identifiers = fields('identifier')
    urls = [u for u in identifiers if urllib.parse.urlparse(u).scheme in ('http','https')]
    doi = next((m.group(0).rstrip('.,;') for value in identifiers if (m:=re.search(r'10\.\d{4,9}/[^\s<>]+',value,re.I))), '')
    landing = next((u for u in urls if '/article/view/' in u), next((u for u in urls if 'doi.org/' not in u), ''))
    pdf = next((u for u in urls + fields('relation') if urllib.parse.urlparse(u).scheme in ('https','http') and (u.lower().endswith('.pdf') or '/article/download/' in u)), '')
    years=[m.group(0) for value in fields('date') if (m:=re.search(r'\b(?:19|20)\d{2}\b',value))]
    languages=fields('language')
    primary_lang=(titles_ml[0].get('lang') if titles_ml else '') or (languages[0] if languages else '')
    lang_map={'pt':'Portuguese','por':'Portuguese','pt-br':'Portuguese','en':'English','eng':'English','es':'Spanish','spa':'Spanish','fr':'French','fra':'French','de':'German','deu':'German','ger':'German'}
    language_code=str(primary_lang).lower().replace('_','-').split('-')[0]
    language=lang_map.get(str(primary_lang).lower(),lang_map.get(language_code,str(primary_lang)))
    types=fields('type'); rights=fields('rights')
    metadata_status='source' if title_en and (not abstract_original or abstract_en) else 'pending_translation'
    return {
      'id':item_id,'journal':journal['id'],
      'title':display_title,'titleOriginal':title_original,'titleEn':title_en,'titles':fields('title'),'titleVariants':titles_ml,
      'authors':fields('creator'),'contributors':fields('contributor'),'institutions':[],
      'abstract':display_abstract,'abstractOriginal':abstract_original,'abstractEn':abstract_en,'abstracts':fields('description'),'abstractVariants':abstracts_ml,
      'keywords':display_keywords,'keywordsOriginal':keywords_original,'keywordsEn':keywords_en,'keywordVariants':keywords_ml,
      'metadataEnglishStatus':metadata_status,
      'year':int(years[0]) if years else 0,'dates':fields('date'),
      'language':language,'languageCode':language_code,'languages':languages,
      'type':types[0] if types else 'Not informed','types':types,
      'doi':doi,'url':landing or ('https://doi.org/'+doi if doi else ''),'pdf':pdf,'rights':rights,
      'openAccess':True if any('creativecommons.org/licenses/' in r or 'creativecommons.org/publicdomain/' in r for r in rights) else None,
      'source':journal.get('oai',''),'oaiIdentifier':identifier,'oaiDatestamp':header.findtext('o:datestamp','',NS),'harvestedAt':now
    }

def load_json(path):
    if path.suffix == '.gz':
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            return json.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    content = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.suffix == '.gz':
        with gzip.open(temp, 'wt', encoding='utf-8', compresslevel=6) as stream:
            stream.write(content)
    else:
        temp.write_text(content, encoding='utf-8')
    temp.replace(path)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--journal', help='ID de uma revista; padrão: todas as habilitadas')
    parser.add_argument('--max-pages', type=int, default=0, help='0: até o último lote; valores positivos limitam a execução com retomada')
    parser.add_argument('--workers', type=int, default=3, help='Fontes consultadas em paralelo (1 a 4)')
    parser.add_argument('--full', action='store_true', help='Ignorar cursor anterior e recomeçar a coleta')
    args = parser.parse_args()
    if args.max_pages < 0:
        parser.error('--max-pages deve ser zero ou positivo')
    now = datetime.now(timezone.utc).isoformat()
    directory = ROOT / 'dist/data'
    journals = json.loads((directory / 'journals.json').read_text())
    selected = [j for j in journals if j.get('enabled') and (not args.journal or j['id'] in args.journal.split(','))]
    if not selected:
        parser.error('Nenhuma revista habilitada corresponde à seleção')
    catalog_file = ROOT / 'harvest/catalog.json.gz'
    input_file = catalog_file if catalog_file.exists() else directory / 'articles.json'
    old = load_json(input_file)
    records = {a['id']: a for a in old['articles']} if not old.get('demo') else {}
    state_file = ROOT / 'harvest/state.json'
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    old_status = json.loads((directory / 'status.json').read_text())
    statuses = {s['id']: s for s in old_status.get('journals', [])}
    any_success = False
    lock = threading.RLock()
    def collect(journal):
        nonlocal any_success
        jid = journal['id']
        prior = state.get(jid, {}) if not args.full else {}
        report = {**statuses.get(jid, {}), 'id': jid, 'attemptedAt': now, 'status': 'error', 'processed': 0}
        report.pop('error', None)
        try:
            get_xml(journal['oai'], {'verb': 'Identify'})
            formats, _ = get_xml(journal['oai'], {'verb': 'ListMetadataFormats'})
            if 'oai_dc' not in [e.text for e in formats.findall('.//o:metadataPrefix', NS)]:
                raise ValueError('A fonte não oferece oai_dc')
            params = {'verb': 'ListRecords', 'metadataPrefix': 'oai_dc'}
            if prior.get('cursor'):
                params = {'verb': 'ListRecords', 'resumptionToken': prior['cursor']}
            elif prior.get('since'):
                params['from'] = prior['since']
            batch = {}
            cursor = ''
            seen_tokens = set()
            for page_number in (range(args.max_pages) if args.max_pages else itertools.count()):
                xml, raw = get_xml(journal['oai'], params)
                archive = ROOT / 'harvest/raw' / jid
                archive.mkdir(parents=True, exist_ok=True)
                (archive / (hashlib.sha256(raw).hexdigest() + '.xml')).write_bytes(raw)
                for node in xml.findall('o:ListRecords/o:record', NS):
                    row = parse_record(node, journal, now)
                    if row:
                        batch[row['id']] = row
                cursor = xml.findtext('o:ListRecords/o:resumptionToken', '', NS).strip()
                token = xml.find('o:ListRecords/o:resumptionToken', NS)
                if token is not None and token.get('completeListSize'):
                    report['responseTotal'] = int(token.get('completeListSize'))
                with lock:
                    for key, value in batch.items():
                        if value.get('deleted'):
                            records.pop(key, None)
                        else:
                            records[key] = value
                    started = prior.get('started', now[:10])
                    state[jid] = {'cursor': cursor, 'started': started} if cursor else {'since': started}
                    report.update(status='partial' if cursor else 'ok', processed=len(batch), pages=page_number+1, completedAt=datetime.now(timezone.utc).isoformat())
                    report['recordsAvailable'] = sum(a['journal'] == jid for a in records.values())
                    if not cursor and not prior.get('since'):
                        report['fullHarvestCompletedAt'] = report['completedAt']
                    statuses[jid] = report.copy()
                    save_json(catalog_file, {'demo': False, 'partial': any(statuses.get(j['id'], {}).get('status') != 'ok' for j in journals if j.get('enabled')), 'updated': now, 'articles': sorted(records.values(), key=lambda a: (a['year'], a['id']), reverse=True)})
                    save_json(directory / 'status.json', {'updated': now, 'journals': list(statuses.values())})
                    save_json(state_file, state)
                    any_success = True
                print(f'{jid}: página {page_number+1}, {len(batch)} registros processados; ' + ('continua' if cursor else 'fim da paginação'), flush=True)
                if not cursor:
                    break
                if cursor in seen_tokens:
                    raise ValueError('Token de paginação repetido pela fonte')
                seen_tokens.add(cursor)
                params = {'verb': 'ListRecords', 'resumptionToken': cursor}
                time.sleep(1)
            with lock:
                for key, value in batch.items():
                    if value.get('deleted'):
                        records.pop(key, None)
                    else:
                        records[key] = value
                # The incremental watermark is the start of the initial batch, not
                # the completion date, so updates during a multi-run harvest survive.
                started = prior.get('started', now[:10])
                state[jid] = {'cursor': cursor, 'started': started} if cursor else {'since': started}
                report.update(status='partial' if cursor else 'ok', processed=len(batch), completedAt=datetime.now(timezone.utc).isoformat())
                any_success = True
        except Exception as exc:
            report['status'] = 'error'
            report['error'] = str(exc)
            # Expired tokens restart at the previous watermark, with stable IDs.
            if 'badResumptionToken' in str(exc):
                state[jid] = {'since': prior['since']} if prior.get('since') else {}
            print(f'{jid}: {exc}')
        with lock:
            statuses[jid] = report
    with ThreadPoolExecutor(max_workers=max(1,min(4,args.workers))) as pool:
        list(pool.map(collect, selected))
    if any_success:
        save_json(catalog_file, {'demo': False, 'partial': any(statuses.get(j['id'], {}).get('status') != 'ok' for j in journals if j.get('enabled')), 'updated': now, 'articles': sorted(records.values(), key=lambda a: (a['year'], a['id']), reverse=True)})
    save_json(directory / 'status.json', {'updated': now, 'journals': list(statuses.values())})
    save_json(state_file, state)
    # Same DOI across sources is retained, not silently merged. Stable OAI IDs
    # update the same record on repeat collections. Review cross-source duplicates.
    dois = {}
    for a in records.values():
        if a.get('doi'):
            dois.setdefault(a['doi'].lower(), []).append(a['id'])
    save_json(ROOT / 'harvest/duplicates.json', {k:v for k,v in dois.items() if len(v)>1})
    from publish import publish
    publish(ROOT)
    print(f'{len(records)} registros reais. Relatório: dist/data/status.json')
    if not any_success or any(statuses[j['id']]['status'] == 'error' for j in selected):
        raise SystemExit(1)

if __name__ == '__main__':
    main()

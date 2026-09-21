"""OAI-PMH -> catálogo estático. Python 3.11+, sem dependências externas."""
import argparse
import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NS = {'o': 'http://www.openarchives.org/OAI/2.0/', 'dc': 'http://purl.org/dc/elements/1.1/'}

def clean(value):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', '', html.unescape(value or ''))).strip()

def get_xml(endpoint, params):
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in ('https', 'http'):
        raise ValueError('Endpoint deve usar HTTP(S)')
    url = endpoint + ('&' if '?' in endpoint else '?') + urllib.parse.urlencode(params)
    last = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'BuscaEM/1.0 (OAI-PMH metadata harvester)', 'Accept': 'application/xml,text/xml'})
            with urllib.request.urlopen(request, timeout=40) as response:
                raw = response.read(20_000_001)
            if len(raw) > 20_000_000:
                raise ValueError('Resposta excede 20 MB; ajustar lote na fonte')
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                raise ValueError('DTD e entidades XML não permitidas')
            xml = ET.fromstring(raw)
            if xml.tag != '{http://www.openarchives.org/OAI/2.0/}OAI-PMH':
                raise ValueError('A resposta não é OAI-PMH válido')
            errors = xml.findall('o:error', NS)
            for error in errors:
                if error.attrib.get('code') != 'noRecordsMatch':
                    raise ValueError(f"OAI-PMH {error.attrib.get('code')}: {error.text}")
            return xml, raw
        except (OSError, ValueError, ET.ParseError) as exc:
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
    def preferred(name):
        values = dc.findall('.//dc:' + name, NS)
        # Retain every language variant below; prefer Portuguese only for display.
        values.sort(key=lambda e: 0 if e.attrib.get('{http://www.w3.org/XML/1998/namespace}lang', '').lower().startswith('pt') else 1)
        return next((clean(''.join(e.itertext())) for e in values if clean(''.join(e.itertext()))), '')
    title = preferred('title')
    if not title:
        return None
    identifiers = fields('identifier')
    urls = [s for s in identifiers if urllib.parse.urlparse(s).scheme in ('http', 'https')]
    doi = next((m.group(0).rstrip('.,;') for s in identifiers if (m := re.search(r'10\.\d{4,9}/[^\s<>]+', s, re.I))), '')
    landing = next((u for u in urls if '/article/view/' in u), next((u for u in urls if 'doi.org/' not in u), ''))
    pdf = next((u for u in urls + fields('relation') if urllib.parse.urlparse(u).scheme in ('https', 'http') and (u.lower().endswith('.pdf') or '/article/download/' in u)), '')
    years = [m.group(0) for s in fields('date') if (m := re.search(r'\b(?:19|20)\d{2}\b', s))]
    languages = fields('language')
    language = languages[0] if languages else ''
    lang_map = {'pt': 'Português', 'por': 'Português', 'pt-br': 'Português', 'en': 'Inglês', 'eng': 'Inglês', 'es': 'Espanhol', 'spa': 'Espanhol'}
    keywords = list(dict.fromkeys(k.strip() for subject in fields('subject') for k in subject.split(';') if k.strip()))
    types = fields('type')
    rights = fields('rights')
    return {'id': item_id, 'journal': journal['id'], 'title': title, 'titles': fields('title'), 'authors': fields('creator'), 'abstract': preferred('description'), 'abstracts': fields('description'), 'keywords': keywords, 'year': int(years[0]) if years else 0, 'dates': fields('date'), 'language': lang_map.get(language.lower(), language), 'languages': languages, 'type': types[0] if types else 'Não informado', 'types': types, 'doi': doi, 'url': landing or ('https://doi.org/' + doi if doi else ''), 'pdf': pdf, 'rights': rights, 'openAccess': True if any('creativecommons.org/licenses/' in r or 'creativecommons.org/publicdomain/' in r for r in rights) else None, 'source': journal['oai'], 'oaiIdentifier': identifier, 'oaiDatestamp': header.findtext('o:datestamp', '', NS), 'harvestedAt': now}

def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--journal', help='ID de uma revista; padrão: todas as habilitadas')
    parser.add_argument('--max-pages', type=int, default=20, help='Limite por revista nesta execução; retomada na próxima')
    parser.add_argument('--full', action='store_true', help='Ignorar cursor anterior e recomeçar a coleta')
    args = parser.parse_args()
    if args.max_pages < 1:
        parser.error('--max-pages deve ser positivo')
    now = datetime.now(timezone.utc).isoformat()
    directory = ROOT / 'dist/data'
    journals = json.loads((directory / 'journals.json').read_text())
    selected = [j for j in journals if j.get('enabled') and (not args.journal or j['id'] == args.journal)]
    if not selected:
        parser.error('Nenhuma revista habilitada corresponde à seleção')
    old = json.loads((directory / 'articles.json').read_text())
    records = {a['id']: a for a in old['articles']} if not old.get('demo') else {}
    state_file = ROOT / 'harvest/state.json'
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    old_status = json.loads((directory / 'status.json').read_text())
    statuses = {s['id']: s for s in old_status.get('journals', [])}
    any_success = False
    for journal in selected:
        jid = journal['id']
        prior = state.get(jid, {}) if not args.full else {}
        report = {'id': jid, 'attemptedAt': now, 'status': 'error', 'processed': 0}
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
            for page_number in range(args.max_pages):
                xml, raw = get_xml(journal['oai'], params)
                archive = ROOT / 'harvest/raw' / jid
                archive.mkdir(parents=True, exist_ok=True)
                (archive / (hashlib.sha256(raw).hexdigest() + '.xml')).write_bytes(raw)
                for node in xml.findall('o:ListRecords/o:record', NS):
                    row = parse_record(node, journal, now)
                    if row:
                        batch[row['id']] = row
                cursor = xml.findtext('o:ListRecords/o:resumptionToken', '', NS).strip()
                if not cursor:
                    break
                if cursor in seen_tokens:
                    raise ValueError('Token de paginação repetido pela fonte')
                seen_tokens.add(cursor)
                params = {'verb': 'ListRecords', 'resumptionToken': cursor}
                time.sleep(1)
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
            report['error'] = str(exc)
            # Expired tokens restart at the previous watermark, with stable IDs.
            if 'badResumptionToken' in str(exc):
                state[jid] = {'since': prior['since']} if prior.get('since') else {}
            print(f'{jid}: {exc}')
        statuses[jid] = report
    if any_success:
        save_json(directory / 'articles.json', {'demo': False, 'partial': any(s['status'] != 'ok' for s in statuses.values()), 'updated': now, 'articles': sorted(records.values(), key=lambda a: (a['year'], a['id']), reverse=True)})
    save_json(directory / 'status.json', {'updated': now, 'journals': list(statuses.values())})
    save_json(state_file, state)
    # Same DOI across sources is retained, not silently merged. Stable OAI IDs
    # update the same record on repeat collections. Review cross-source duplicates.
    dois = {}
    for a in records.values():
        if a.get('doi'):
            dois.setdefault(a['doi'].lower(), []).append(a['id'])
    save_json(ROOT / 'harvest/duplicates.json', {k:v for k,v in dois.items() if len(v)>1})
    print(f'{len(records)} registros reais. Relatório: dist/data/status.json')
    if not any_success:
        raise SystemExit(1)

if __name__ == '__main__':
    main()

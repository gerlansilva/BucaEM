"""Canonical metadata resolver for BuscaEM.

Policy:
1. Official publisher/journal landing-page metadata is preferred.
2. Crossref publisher-deposited metadata is the structured fallback.
3. Discovery services (OpenAlex) may contribute identifiers/citation counts only;
   they never overwrite canonical bibliographic fields.

Raw Crossref JSON and publisher HTML are archived for auditability.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

CROSSREF = "https://api.crossref.org/works/"


def _clean(value):
    if value is None:
        return ""
    if isinstance(value, list):
        value = " ".join(str(x) for x in value if x is not None)
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_doi(value):
    value = _clean(value)
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    return value.strip().rstrip(".,;)")


def _curl(url, *, accept="*/*", timeout=60):
    p = subprocess.run([
        "curl", "--fail", "--location", "--silent", "--show-error",
        "--max-time", str(timeout), "--connect-timeout", "15",
        "--proto", "=https,http", "--proto-redir", "=https,http",
        "--user-agent", "BuscaEM/4.3 (academic metadata harvester; contact via project page)",
        "--header", f"Accept: {accept}", url,
    ], capture_output=True, timeout=timeout + 5)
    if p.returncode:
        raise OSError(p.stderr.decode(errors="replace").strip())
    return p.stdout


def _request(url, *, accept="*/*", timeout=60, retries=3):
    last = None
    for attempt in range(retries):
        try:
            return _curl(url, accept=accept, timeout=timeout)
        except Exception as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(str(last))


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = []
        self.links = []
        self._in_jsonld = False
        self._jsonld = []
        self.jsonld_blocks = []

    def handle_starttag(self, tag, attrs):
        attrs = {str(k).lower(): (v or "") for k, v in attrs}
        t = tag.lower()
        if t == "meta":
            key = attrs.get("name") or attrs.get("property") or attrs.get("http-equiv")
            content = attrs.get("content")
            if key and content:
                self.meta.append((key.strip().lower(), content.strip()))
        elif t == "link":
            self.links.append(attrs)
        elif t == "script" and "ld+json" in attrs.get("type", "").lower():
            self._in_jsonld = True
            self._jsonld = []

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self._in_jsonld:
            self._in_jsonld = False
            value = "".join(self._jsonld).strip()
            if value:
                self.jsonld_blocks.append(value)
            self._jsonld = []

    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld.append(data)


def _meta_values(parser, *keys):
    keys = {k.lower() for k in keys}
    return [_clean(v) for k, v in parser.meta if k in keys and _clean(v)]


def _first(values):
    return next((x for x in values if x), "")


def _split_keywords(values):
    out = []
    for value in values:
        for item in re.split(r"\s*[;,|]\s*", value):
            item = _clean(item)
            if item and item.casefold() not in {x.casefold() for x in out}:
                out.append(item)
    return out


def _jsonld_article(parser):
    candidates = []
    for block in parser.jsonld_blocks:
        try:
            obj = json.loads(block)
        except Exception:
            continue
        stack = obj if isinstance(obj, list) else [obj]
        for item in stack:
            if isinstance(item, dict) and "@graph" in item and isinstance(item["@graph"], list):
                stack.extend(item["@graph"])
            if not isinstance(item, dict):
                continue
            typ = item.get("@type", "")
            types = typ if isinstance(typ, list) else [typ]
            if any(str(t).lower() in {"scholarlyarticle", "article", "newsarticle"} for t in types):
                candidates.append(item)
    return candidates[0] if candidates else {}


def parse_publisher_html(raw, final_url=""):
    text = raw.decode("utf-8", errors="replace")
    parser = MetaParser()
    parser.feed(text)
    ld = _jsonld_article(parser)

    title = _first(_meta_values(parser, "citation_title", "dc.title", "dcterms.title")) or _clean(ld.get("headline") or ld.get("name"))
    authors = _meta_values(parser, "citation_author", "dc.creator", "dcterms.creator")
    if not authors:
        raw_authors = ld.get("author") or []
        if isinstance(raw_authors, dict):
            raw_authors = [raw_authors]
        for item in raw_authors if isinstance(raw_authors, list) else []:
            name = _clean(item.get("name") if isinstance(item, dict) else item)
            if name:
                authors.append(name)

    abstract = _first(_meta_values(parser, "citation_abstract", "dc.description", "dcterms.abstract", "dcterms.description"))
    if not abstract:
        abstract = _clean(ld.get("abstract") or ld.get("description"))

    keywords = _split_keywords(_meta_values(parser, "citation_keywords", "keywords", "dc.subject", "dcterms.subject"))
    if not keywords:
        kw = ld.get("keywords")
        if isinstance(kw, str):
            keywords = _split_keywords([kw])
        elif isinstance(kw, list):
            keywords = [_clean(x) for x in kw if _clean(x)]

    doi = normalize_doi(_first(_meta_values(parser, "citation_doi", "dc.identifier", "dcterms.identifier")) or ld.get("identifier", ""))
    journal = _first(_meta_values(parser, "citation_journal_title", "prism.publicationname"))
    volume = _first(_meta_values(parser, "citation_volume", "prism.volume"))
    issue = _first(_meta_values(parser, "citation_issue", "prism.number"))
    first_page = _first(_meta_values(parser, "citation_firstpage", "prism.startingpage"))
    last_page = _first(_meta_values(parser, "citation_lastpage", "prism.endingpage"))
    pages = f"{first_page}-{last_page}" if first_page and last_page else first_page
    date = _first(_meta_values(parser, "citation_publication_date", "citation_date", "dc.date", "dcterms.issued", "prism.publicationdate")) or _clean(ld.get("datePublished"))
    year_match = re.search(r"\b(?:19|20)\d{2}\b", date or "")
    year = int(year_match.group()) if year_match else 0
    language = _first(_meta_values(parser, "citation_language", "dc.language", "dcterms.language")) or _clean(ld.get("inLanguage"))
    pdf = _first(_meta_values(parser, "citation_pdf_url"))
    if not pdf:
        for link in parser.links:
            rel = link.get("rel", "").lower()
            typ = link.get("type", "").lower()
            href = link.get("href", "")
            if href and ("alternate" in rel or "enclosure" in rel) and "pdf" in typ:
                pdf = urllib.parse.urljoin(final_url, href)
                break
    canonical = ""
    for link in parser.links:
        if "canonical" in link.get("rel", "").lower() and link.get("href"):
            canonical = urllib.parse.urljoin(final_url, link["href"])
            break
    return {
        "title": title, "authors": authors, "abstract": abstract, "keywords": keywords,
        "doi": doi, "journalTitle": journal, "volume": volume, "issue": issue,
        "pages": pages, "date": date, "year": year, "languageCode": language.lower() if language else "",
        "pdf": pdf, "url": canonical or final_url,
    }


def fetch_crossref(doi, archive_dir: Path):
    doi = normalize_doi(doi)
    url = CROSSREF + urllib.parse.quote(doi, safe="")
    raw = _request(url, accept="application/json")
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / (hashlib.sha256(doi.encode()).hexdigest()[:24] + ".json")).write_bytes(raw)
    data = json.loads(raw)
    return (data.get("message") or {})


def normalize_crossref(message):
    title = _clean(_first(message.get("title") or []))
    abstract = _clean(message.get("abstract"))
    authors = []
    for a in message.get("author") or []:
        name = _clean(" ".join(x for x in [a.get("given", ""), a.get("family", "")] if x))
        if name:
            authors.append(name)
    subjects = [_clean(x) for x in message.get("subject") or [] if _clean(x)]
    containers = [_clean(x) for x in message.get("container-title") or [] if _clean(x)]
    doi = normalize_doi(message.get("DOI"))
    url = _clean(message.get("URL")) or ("https://doi.org/" + doi if doi else "")
    volume = _clean(message.get("volume"))
    issue = _clean(message.get("issue"))
    pages = _clean(message.get("page") or message.get("article-number"))
    date_parts = (((message.get("published-print") or message.get("published-online") or message.get("issued") or {}).get("date-parts") or [[]])[0])
    year = int(date_parts[0]) if date_parts else 0
    date = "-".join(str(x) for x in date_parts) if date_parts else ""
    language = _clean(message.get("language")).lower()
    return {
        "title": title, "authors": authors, "abstract": abstract, "keywords": subjects,
        "doi": doi, "journalTitle": containers[0] if containers else "", "volume": volume,
        "issue": issue, "pages": pages, "date": date, "year": year,
        "languageCode": language, "url": url, "pdf": "",
    }


def _prefer(primary, fallback, key):
    value = primary.get(key)
    if value not in (None, "", [], 0):
        return value
    return fallback.get(key)


def canonical_record_from_doi(doi, journal, root: Path, *, discovery=None):
    """Resolve a DOI to publisher/Crossref metadata and return a catalog record.

    OpenAlex/discovery fields are retained only as supplemental provenance and metrics.
    """
    doi = normalize_doi(doi)
    now = datetime.now(timezone.utc).isoformat()
    base = root / "harvest/raw" / journal["id"]
    crossref_raw = fetch_crossref(doi, base / "crossref")
    cr = normalize_crossref(crossref_raw)

    publisher = {}
    landing_url = cr.get("url") or ("https://doi.org/" + doi)
    publisher_error = ""
    if landing_url:
        try:
            raw = _request(landing_url, accept="text/html,application/xhtml+xml")
            (base / "official").mkdir(parents=True, exist_ok=True)
            name = hashlib.sha256(doi.encode()).hexdigest()[:24] + ".html"
            (base / "official" / name).write_bytes(raw)
            publisher = parse_publisher_html(raw, landing_url)
        except Exception as exc:
            publisher_error = str(exc)

    canonical = {}
    for key in ("title", "authors", "abstract", "keywords", "doi", "journalTitle", "volume", "issue", "pages", "date", "year", "languageCode", "pdf", "url"):
        canonical[key] = _prefer(publisher, cr, key)

    # Require publisher-deposited/official bibliographic identity, not OpenAlex-only metadata.
    if not canonical.get("title") or not canonical.get("doi"):
        raise RuntimeError(f"Metadados canônicos insuficientes para DOI {doi}")

    lang = (canonical.get("languageCode") or "").lower().split("-")[0]
    lang_name = {"en":"English", "pt":"Portuguese", "es":"Spanish", "fr":"French", "de":"German", "it":"Italian"}.get(lang, lang)
    title = canonical["title"]
    abstract = canonical.get("abstract") or ""
    keywords = canonical.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = _split_keywords([str(keywords)])
    title_en = title if lang == "en" else ""
    abstract_en = abstract if lang == "en" else ""
    keywords_en = keywords if lang == "en" else []
    rid = hashlib.sha256((journal["id"] + "|doi|" + doi.lower()).encode()).hexdigest()[:24]

    discovery = discovery or {}
    provenance = ["Publisher landing page" if publisher.get("title") else "Crossref publisher deposit"]
    if publisher.get("title") and cr.get("title"):
        provenance.append("Crossref publisher deposit")
    if discovery.get("provider"):
        provenance.append(discovery["provider"] + " (discovery/metrics only)")

    record = {
        "id": rid, "journal": journal["id"],
        "title": title_en or title, "titleOriginal": title, "titleEn": title_en,
        "titles": [title], "titleVariants": [{"text": title, "lang": lang}],
        "authors": canonical.get("authors") or [], "contributors": [], "institutions": [],
        "abstract": abstract_en or abstract, "abstractOriginal": abstract, "abstractEn": abstract_en,
        "abstracts": [abstract] if abstract else [],
        "abstractVariants": ([{"text": abstract, "lang": lang}] if abstract else []),
        "keywords": keywords_en or keywords, "keywordsOriginal": keywords, "keywordsEn": keywords_en,
        "keywordVariants": [{"text": k, "lang": lang} for k in keywords],
        "metadataEnglishStatus": "source" if lang == "en" else "pending_translation",
        "year": int(canonical.get("year") or 0), "dates": [canonical.get("date")] if canonical.get("date") else [],
        "language": lang_name, "languageCode": lang, "languages": [lang] if lang else [],
        "type": "article", "types": ["article"],
        "doi": doi, "url": canonical.get("url") or landing_url, "pdf": canonical.get("pdf") or "",
        "volume": canonical.get("volume") or "", "issue": canonical.get("issue") or "", "pages": canonical.get("pages") or "",
        "rights": [], "openAccess": discovery.get("openAccess"),
        "source": "; ".join(provenance), "provenance": provenance,
        "metadataAuthority": "publisher" if publisher.get("title") else "crossref",
        "harvestedAt": now,
    }
    if publisher_error:
        record["publisherMetadataError"] = publisher_error
    if discovery.get("openalexId"):
        record["openalexId"] = discovery["openalexId"]
    if discovery.get("citedByCount") is not None:
        record["citedByCount"] = discovery["citedByCount"]
    return record

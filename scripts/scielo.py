"""SciELO journal harvester used by BuscaEM.

The adapter crawls a SciELO journal issue grid, follows issue pages and article
pages, and converts citation/DC meta tags to the BuscaEM multilingual record
schema. Raw HTML is preserved under harvest/raw/<journal>/scielo/.

It intentionally does not rely on a private SciELO API. The public HTML pages
are the provenance source, so the adapter remains auditable and can be replayed.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
import subprocess
import time
import urllib.parse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.meta: list[tuple[str, str]] = []
        self.html_lang = ""

    def handle_starttag(self, tag, attrs):
        attrs = {str(k).lower(): (v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "html":
            self.html_lang = attrs.get("lang", "")
        elif tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        elif tag == "meta":
            key = attrs.get("name") or attrs.get("property") or attrs.get("itemprop")
            value = attrs.get("content", "")
            if key and value:
                self.meta.append((key.strip(), value.strip()))


def clean(value: str) -> str:
    value = html_lib.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def unique(values: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        value = clean(value)
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def normalize_lang(value: str) -> str:
    value = (value or "").lower().replace("_", "-").split("-")[0]
    return {"pt": "pt", "por": "pt", "en": "en", "eng": "en", "es": "es", "spa": "es"}.get(value, value)


def meta_values(parser: PageParser, *keys: str) -> list[str]:
    wanted = {k.lower() for k in keys}
    return unique(v for k, v in parser.meta if k.lower() in wanted)


def first_meta(parser: PageParser, *keys: str) -> str:
    values = meta_values(parser, *keys)
    return values[0] if values else ""


def curl_get(url: str, *, user_agent: str = "BuscaEM/4.1 (metadata harvester; academic indexing)") -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        raise ValueError("SciELO URL must use HTTP(S)")
    last = None
    for attempt in range(4):
        try:
            proc = subprocess.run(
                [
                    "curl", "--fail", "--location", "--silent", "--show-error",
                    "--compressed", "--max-time", "75", "--connect-timeout", "20",
                    "--max-filesize", "15000000", "--retry", "2", "--retry-delay", "2",
                    "--proto", "=https,http", "--proto-redir", "=https,http",
                    "--user-agent", user_agent,
                    "--header", "Accept: text/html,application/xhtml+xml",
                    url,
                ],
                capture_output=True,
                timeout=90,
            )
            if proc.returncode:
                raise OSError(proc.stderr.decode(errors="replace").strip())
            if not proc.stdout:
                raise OSError("empty response")
            return proc.stdout
        except (OSError, subprocess.TimeoutExpired) as exc:
            last = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
    raise RuntimeError(str(last))


def parse_page(raw: bytes) -> PageParser:
    text = raw.decode("utf-8", errors="replace")
    parser = PageParser()
    parser.feed(text)
    return parser


def canonicalize(base: str, href: str) -> str:
    url = urllib.parse.urljoin(base, href)
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def article_identity(url: str) -> str:
    match = re.search(r"/a/([^/?#]+)/?", url)
    return match.group(1) if match else hashlib.sha256(url.encode()).hexdigest()[:20]


def doi_from_parser(parser: PageParser) -> str:
    raw = first_meta(parser, "citation_doi", "dc.identifier", "DC.Identifier")
    match = re.search(r"10\.\d{4,9}/[^\s<>\"']+", raw, re.I)
    return match.group(0).rstrip(".,;)") if match else ""


def parse_metadata(raw: bytes, url: str, lang_hint: str = "") -> dict:
    parser = parse_page(raw)
    title = first_meta(parser, "citation_title", "dc.title", "DC.Title", "og:title")
    abstract = first_meta(
        parser,
        "citation_abstract", "dc.description", "DC.Description", "description", "og:description",
    )
    keywords = meta_values(parser, "citation_keywords", "keywords", "dc.subject", "DC.Subject")
    expanded_keywords = []
    for value in keywords:
        expanded_keywords.extend(re.split(r"\s*[;|]\s*", value))
    authors = meta_values(parser, "citation_author", "dc.creator", "DC.Creator")
    date = first_meta(parser, "citation_publication_date", "citation_date", "dc.date", "DC.Date")
    year_match = re.search(r"\b(?:19|20)\d{2}\b", date)
    pdf = first_meta(parser, "citation_pdf_url")
    fulltext = first_meta(parser, "citation_fulltext_html_url", "og:url") or url
    section = first_meta(parser, "citation_section", "dc.type", "DC.Type", "citation_article_type")
    declared = normalize_lang(first_meta(parser, "citation_language", "dc.language", "DC.Language") or parser.html_lang or lang_hint)
    return {
        "title": clean(title),
        "abstract": clean(abstract),
        "keywords": unique(expanded_keywords),
        "authors": authors,
        "year": int(year_match.group(0)) if year_match else 0,
        "date": date,
        "doi": doi_from_parser(parser),
        "pdf": pdf,
        "url": fulltext,
        "type": clean(section) or "Article",
        "lang": declared,
    }


def is_probable_article(meta: dict) -> bool:
    """Reject known front matter while keeping research articles conservatively."""
    hay = " ".join([meta.get("type", ""), meta.get("title", "")]).casefold()
    blocked = ("nominata", "consultores ad hoc", "editorial", "erratum", "errata", "retraction", "retratação")
    return not any(term in hay for term in blocked)


def merge_variants(variants: list[dict]) -> dict:
    # First page is canonical. Requested-language pages may expose translated
    # abstracts without translating the article title, so keep both concepts.
    base = next((x for x in variants if not x.get("requestedLang") and x.get("title")), None)
    if base is None:
        base = next((x for x in variants if x.get("title")), variants[0] if variants else {})
    requested = {}
    for item in variants:
        req = normalize_lang(item.get("requestedLang", ""))
        if req:
            requested[req] = item
    return {"base": base, "requested": requested}

def record_from_variants(journal: dict, article_url: str, variants: list[dict], harvested_at: str) -> dict | None:
    merged = merge_variants(variants)
    base = merged["base"]
    if not base or not base.get("title") or not is_probable_article(base):
        return None
    requested = merged["requested"]
    original_lang = normalize_lang(base.get("lang")) or ""
    english = requested.get("en", {})
    spanish = requested.get("es", {})
    portuguese = requested.get("pt", {})
    doi = base.get("doi") or english.get("doi") or spanish.get("doi") or portuguese.get("doi")
    stable = doi.lower() if doi else article_identity(article_url)
    item_id = hashlib.sha256((journal["id"] + "|scielo|" + stable).encode()).hexdigest()[:24]
    title_original = base.get("title", "")
    abstract_original = base.get("abstract", "")
    keywords_original = base.get("keywords", [])
    title_en_candidate = english.get("title", "")
    title_en = title_en_candidate if (original_lang == "en" or (title_en_candidate and clean(title_en_candidate).casefold() != clean(title_original).casefold())) else ""
    abstract_en_candidate = english.get("abstract", "")
    abstract_en = abstract_en_candidate if (original_lang == "en" or (abstract_en_candidate and clean(abstract_en_candidate).casefold() != clean(abstract_original).casefold())) else ""
    keywords_en_candidate = english.get("keywords", [])
    keywords_en = keywords_en_candidate if (original_lang == "en" or keywords_en_candidate != keywords_original) else []
    variants_public=[]
    if title_original:
        variants_public.append({"text":title_original,"lang":original_lang})
    for req,item in requested.items():
        t=item.get("title","")
        if t and t.casefold()!=title_original.casefold():
            variants_public.append({"text":t,"lang":req})
    language_labels = {"pt": "Portuguese", "en": "English", "es": "Spanish"}
    year = base.get("year") or max((v.get("year", 0) for v in variants), default=0)
    authors = base.get("authors") or next((v.get("authors") for v in variants if v.get("authors")), [])
    pdf = base.get("pdf") or next((v.get("pdf") for v in variants if v.get("pdf")), "")
    landing = base.get("url") or article_url
    return {
        "id": item_id,
        "journal": journal["id"],
        "title": title_en or title_original,
        "titleOriginal": title_original,
        "titleEn": title_en,
        "titles": unique(v.get("title", "") for v in variants),
        "titleVariants": variants_public,
        "authors": authors,
        "contributors": [],
        "institutions": [],
        "abstract": abstract_en or abstract_original,
        "abstractOriginal": abstract_original,
        "abstractEn": abstract_en,
        "abstracts": unique(v.get("abstract", "") for v in variants),
        "abstractVariants": [{"text": v.get("abstract", ""), "lang": k} for k, v in requested.items() if v.get("abstract")],
        "keywords": keywords_en or keywords_original,
        "keywordsOriginal": keywords_original,
        "keywordsEn": keywords_en,
        "keywordVariants": [{"text": kw, "lang": k} for k, v in requested.items() for kw in v.get("keywords", [])],
        "metadataEnglishStatus": "source" if title_en and (not abstract_original or abstract_en) else "pending_translation",
        "year": year,
        "dates": unique(v.get("date", "") for v in variants),
        "language": language_labels.get(original_lang, original_lang or "Not informed"),
        "languageCode": original_lang,
        "languages": unique([language_labels.get(original_lang, original_lang)] + [language_labels.get(k, k) for k in requested]),
        "type": base.get("type") or "Article",
        "types": unique(v.get("type", "") for v in variants),
        "doi": doi,
        "url": landing,
        "pdf": pdf,
        "rights": ["SciELO Open Access"],
        "openAccess": True,
        "source": f"SciELO:{journal.get('scieloCode', journal['id'])}",
        "scieloUrl": article_url,
        "harvestedAt": harvested_at,
    }


def _save_raw(raw_dir: Path, category: str, url: str, raw: bytes) -> None:
    folder = raw_dir / category
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode()).hexdigest()[:20]
    (folder / f"{digest}.html").write_bytes(raw)
    (folder / f"{digest}.url.txt").write_text(url + "\n", encoding="utf-8")


def _extract_links(raw: bytes, base_url: str, pattern: re.Pattern[str]) -> list[str]:
    parser = parse_page(raw)
    return sorted({canonicalize(base_url, href) for href in parser.links if pattern.search(urllib.parse.urljoin(base_url, href))})


def harvest_journal(journal: dict, root: Path, *, max_issues: int = 0, max_articles: int = 0, delay: float = 0.35, known_articles: set[str] | None = None, full: bool = False) -> tuple[list[dict], dict]:
    """Harvest one SciELO journal and return records plus a status report."""
    code = journal.get("scieloCode") or journal["id"]
    base = journal.get("scieloUrl") or f"https://www.scielo.br/j/{code}/"
    grid_url = urllib.parse.urljoin(base, "grid")
    raw_dir = root / "harvest" / "raw" / journal["id"] / "scielo"
    now = datetime.now(timezone.utc).isoformat()

    grid_raw = curl_get(grid_url)
    _save_raw(raw_dir, "grid", grid_url, grid_raw)
    issue_pattern = re.compile(rf"/j/{re.escape(code)}/i/", re.I)
    issue_urls = _extract_links(grid_raw, grid_url, issue_pattern)
    if max_issues:
        issue_urls = issue_urls[:max_issues]

    article_pattern = re.compile(rf"/j/{re.escape(code)}/a/[^/?#]+", re.I)
    article_urls: set[str] = set()
    for idx, issue_url in enumerate(issue_urls, 1):
        raw = curl_get(issue_url)
        _save_raw(raw_dir, "issues", issue_url, raw)
        article_urls.update(_extract_links(raw, issue_url, article_pattern))
        print(f"{journal['id']}/SciELO: issue {idx}/{len(issue_urls)}, {len(article_urls)} article URLs", flush=True)
        if delay:
            time.sleep(delay)

    discovered = sorted(article_urls)
    known_articles = known_articles or set()
    article_list = discovered if full else [u for u in discovered if u not in known_articles]
    if max_articles:
        article_list = article_list[:max_articles]
    records: list[dict] = []
    errors: list[dict] = []
    for idx, article_url in enumerate(article_list, 1):
        try:
            variants = []
            # Canonical plus three explicit UI languages. Deduplication removes identical metadata.
            for lang in ("", "en", "pt", "es"):
                sep = "&" if "?" in article_url else "?"
                url = article_url if not lang else f"{article_url}{sep}lang={lang}"
                raw = curl_get(url)
                _save_raw(raw_dir, "articles", url, raw)
                item = parse_metadata(raw, url, lang)
                item["requestedLang"] = lang
                fingerprint = (item.get("title"), item.get("abstract"), tuple(item.get("keywords", [])))
                if fingerprint not in {(x.get("title"), x.get("abstract"), tuple(x.get("keywords", []))) for x in variants}:
                    variants.append(item)
                if delay:
                    time.sleep(delay)
            record = record_from_variants(journal, article_url, variants, now)
            if record:
                records.append(record)
        except Exception as exc:
            errors.append({"url": article_url, "error": str(exc)})
        if idx % 10 == 0 or idx == len(article_list):
            print(f"{journal['id']}/SciELO: articles {idx}/{len(article_list)}, accepted {len(records)}", flush=True)

    report = {
        "id": journal["id"],
        "adapter": "scielo",
        "source": grid_url,
        "attemptedAt": now,
        "status": "ok" if not errors else ("partial" if records else "error"),
        "issuesFound": len(issue_urls),
        "articleUrlsFound": len(discovered),
        "articleUrlsFetched": len(article_list),
        "articleUrlsSkippedAsKnown": len(discovered) - len(article_list),
        "discoveredArticles": discovered,
        "processed": len(records),
        "errors": errors[:50],
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }
    return records, report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal-config", required=True)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--max-issues", type=int, default=0)
    parser.add_argument("--max-articles", type=int, default=0)
    args = parser.parse_args()
    journal = json.loads(Path(args.journal_config).read_text(encoding="utf-8"))
    rows, status = harvest_journal(journal, Path(args.root), max_issues=args.max_issues, max_articles=args.max_articles)
    print(json.dumps({"count": len(rows), "status": status}, ensure_ascii=False, indent=2))

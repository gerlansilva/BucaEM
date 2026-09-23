"""Canonical and multilingual metadata resolver for BuscaEM.

Policy
------
1. Official publisher / journal metadata is preferred.
2. Crossref publisher-deposited metadata is the structured fallback.
3. OpenAlex may contribute identifiers / citation metrics only.
4. English metadata is NEVER machine-translated here.
5. titleEn / abstractEn / keywordsEn are populated only when the
   official source or publisher metadata explicitly provides English.

Supported sources include generic publisher pages, OJS-style metadata,
SciELO-style metadata, Dublin Core, Highwire citation metadata and JSON-LD.
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


# ---------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------

def _clean(value):
    if value is None:
        return ""

    if isinstance(value, list):
        value = " ".join(
            str(x)
            for x in value
            if x is not None
        )

    value = html.unescape(str(value))
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_doi(value):
    value = _clean(value)

    value = re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        value,
        flags=re.I,
    )

    value = re.sub(
        r"^doi:\s*",
        "",
        value,
        flags=re.I,
    )

    return value.strip().rstrip(".,;)")


def _normalize_lang(value):
    value = _clean(value).lower().replace("_", "-")

    if not value:
        return ""

    aliases = {
        "eng": "en",
        "english": "en",
        "en-us": "en",
        "en-gb": "en",

        "por": "pt",
        "portuguese": "pt",
        "português": "pt",
        "portugues": "pt",
        "pt-br": "pt",
        "pt-pt": "pt",

        "spa": "es",
        "spanish": "es",
        "español": "es",
        "espanol": "es",
        "es-es": "es",
        "es-mx": "es",

        "fra": "fr",
        "fre": "fr",
        "french": "fr",

        "deu": "de",
        "ger": "de",
        "german": "de",

        "ita": "it",
        "italian": "it",
    }

    if value in aliases:
        return aliases[value]

    return value.split("-")[0]


def _unique(values):
    out = []
    seen = set()

    for value in values:
        cleaned = _clean(value)

        if not cleaned:
            continue

        key = cleaned.casefold()

        if key in seen:
            continue

        seen.add(key)
        out.append(cleaned)

    return out


def _first(values):
    return next(
        (
            value
            for value in values
            if value
        ),
        "",
    )


def _split_keywords(values):
    out = []
    seen = set()

    for value in values:
        if isinstance(value, list):
            parts = value
        else:
            parts = re.split(
                r"\s*[;,|]\s*",
                str(value),
            )

        for item in parts:
            item = _clean(item)

            if not item:
                continue

            key = item.casefold()

            if key in seen:
                continue

            seen.add(key)
            out.append(item)

    return out


# ---------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------

def _curl(url, *, accept="*/*", timeout=60):
    p = subprocess.run(
        [
            "curl",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--max-time",
            str(timeout),
            "--connect-timeout",
            "15",
            "--proto",
            "=https,http",
            "--proto-redir",
            "=https,http",
            "--user-agent",
            (
                "BuscaEM/4.7 "
                "(academic metadata harvester; "
                "https://github.com/gerlansilva/BucaEM)"
            ),
            "--header",
            f"Accept: {accept}",
            url,
        ],
        capture_output=True,
        timeout=timeout + 5,
    )

    if p.returncode:
        raise OSError(
            p.stderr.decode(
                errors="replace"
            ).strip()
        )

    return p.stdout


def _request(
    url,
    *,
    accept="*/*",
    timeout=60,
    retries=3,
):
    last = None

    for attempt in range(retries):
        try:
            return _curl(
                url,
                accept=accept,
                timeout=timeout,
            )

        except Exception as exc:
            last = exc

            if attempt + 1 < retries:
                time.sleep(2 ** attempt)

    raise RuntimeError(str(last))


# ---------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------

class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(
            convert_charrefs=True
        )

        self.meta = []
        self.links = []

        self.html_lang = ""

        self._in_jsonld = False
        self._jsonld = []
        self.jsonld_blocks = []


    def handle_starttag(
        self,
        tag,
        attrs,
    ):
        attrs = {
            str(k).lower(): (
                v or ""
            )
            for k, v in attrs
        }

        t = tag.lower()

        if t == "html":
            self.html_lang = _normalize_lang(
                attrs.get("lang")
                or attrs.get("xml:lang")
                or ""
            )

        elif t == "meta":
            key = (
                attrs.get("name")
                or attrs.get("property")
                or attrs.get("http-equiv")
            )

            content = attrs.get(
                "content"
            )

            lang = _normalize_lang(
                attrs.get("lang")
                or attrs.get("xml:lang")
                or attrs.get("content-language")
                or ""
            )

            if key and content:
                self.meta.append(
                    {
                        "key": key.strip().lower(),
                        "content": content.strip(),
                        "lang": lang,
                        "attrs": attrs,
                    }
                )

        elif t == "link":
            self.links.append(
                attrs
            )

        elif (
            t == "script"
            and "ld+json"
            in attrs.get(
                "type",
                "",
            ).lower()
        ):
            self._in_jsonld = True
            self._jsonld = []


    def handle_endtag(
        self,
        tag,
    ):
        if (
            tag.lower() == "script"
            and self._in_jsonld
        ):
            self._in_jsonld = False

            value = "".join(
                self._jsonld
            ).strip()

            if value:
                self.jsonld_blocks.append(
                    value
                )

            self._jsonld = []


    def handle_data(
        self,
        data,
    ):
        if self._in_jsonld:
            self._jsonld.append(
                data
            )


# ---------------------------------------------------------------------
# Meta helpers
# ---------------------------------------------------------------------

def _meta_entries(
    parser,
    *keys,
):
    wanted = {
        key.lower()
        for key in keys
    }

    return [
        item
        for item in parser.meta
        if item["key"] in wanted
        and _clean(
            item["content"]
        )
    ]


def _meta_values(
    parser,
    *keys,
    lang=None,
):
    entries = _meta_entries(
        parser,
        *keys,
    )

    if lang:
        lang = _normalize_lang(
            lang
        )

        entries = [
            item
            for item in entries
            if _normalize_lang(
                item.get("lang")
            ) == lang
        ]

    return _unique(
        [
            item["content"]
            for item in entries
        ]
    )


def _entries_to_variants(
    entries,
    default_lang="",
):
    variants = []
    seen = set()

    for item in entries:
        text = _clean(
            item.get("content")
        )

        if not text:
            continue

        lang = _normalize_lang(
            item.get("lang")
            or default_lang
        )

        key = (
            text.casefold(),
            lang,
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        variants.append(
            {
                "text": text,
                "lang": lang,
            }
        )

    return variants


def _variant_for_language(
    variants,
    lang,
):
    lang = _normalize_lang(
        lang
    )

    for variant in variants:
        if (
            _normalize_lang(
                variant.get("lang")
            )
            == lang
        ):
            return _clean(
                variant.get("text")
            )

    return ""


# ---------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------

def _jsonld_articles(
    parser,
):
    candidates = []

    for block in parser.jsonld_blocks:
        try:
            obj = json.loads(
                block
            )
        except Exception:
            continue

        stack = (
            obj
            if isinstance(
                obj,
                list,
            )
            else [obj]
        )

        pos = 0

        while pos < len(stack):
            item = stack[pos]
            pos += 1

            if not isinstance(
                item,
                dict,
            ):
                continue

            graph = item.get(
                "@graph"
            )

            if isinstance(
                graph,
                list,
            ):
                stack.extend(
                    graph
                )

            typ = item.get(
                "@type",
                "",
            )

            types = (
                typ
                if isinstance(
                    typ,
                    list,
                )
                else [typ]
            )

            if any(
                str(t).lower()
                in {
                    "scholarlyarticle",
                    "article",
                    "newsarticle",
                }
                for t in types
            ):
                candidates.append(
                    item
                )

    return candidates


def _jsonld_language(
    item,
):
    value = item.get(
        "inLanguage"
    )

    if isinstance(
        value,
        dict,
    ):
        value = (
            value.get("name")
            or value.get("@id")
            or ""
        )

    return _normalize_lang(
        value
    )


def _jsonld_text_variants(
    articles,
    field_names,
):
    variants = []
    seen = set()

    for item in articles:
        lang = _jsonld_language(
            item
        )

        value = ""

        for field in field_names:
            value = item.get(
                field
            )

            if value:
                break

        if isinstance(
            value,
            dict,
        ):
            value_lang = _normalize_lang(
                value.get("@language")
                or value.get("language")
                or lang
            )

            value = (
                value.get("@value")
                or value.get("value")
                or value.get("name")
                or ""
            )

            lang = (
                value_lang
                or lang
            )

        text = _clean(
            value
        )

        if not text:
            continue

        key = (
            text.casefold(),
            lang,
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        variants.append(
            {
                "text": text,
                "lang": lang,
            }
        )

    return variants


def _jsonld_keyword_variants(
    articles,
):
    result = []

    for item in articles:
        lang = _jsonld_language(
            item
        )

        kw = item.get(
            "keywords"
        )

        if not kw:
            continue

        if isinstance(
            kw,
            str,
        ):
            values = _split_keywords(
                [kw]
            )

        elif isinstance(
            kw,
            list,
        ):
            values = []

            for x in kw:
                if isinstance(
                    x,
                    dict,
                ):
                    x = (
                        x.get("name")
                        or x.get("@value")
                        or ""
                    )

                cleaned = _clean(
                    x
                )

                if cleaned:
                    values.append(
                        cleaned
                    )

            values = _split_keywords(
                values
            )

        else:
            values = []

        if values:
            result.append(
                {
                    "lang": lang,
                    "values": values,
                }
            )

    return result


# ---------------------------------------------------------------------
# Publisher HTML parsing
# ---------------------------------------------------------------------

def parse_publisher_html(
    raw,
    final_url="",
):
    text = raw.decode(
        "utf-8",
        errors="replace",
    )

    parser = MetaParser()
    parser.feed(
        text
    )

    jsonld_articles = _jsonld_articles(
        parser
    )

    page_lang = parser.html_lang


    # -------------------------------------------------------------
    # Titles
    # -------------------------------------------------------------

    title_entries = _meta_entries(
        parser,
        "citation_title",
        "dc.title",
        "dcterms.title",
        "og:title",
    )

    title_variants = _entries_to_variants(
        title_entries,
        page_lang,
    )

    jsonld_title_variants = (
        _jsonld_text_variants(
            jsonld_articles,
            [
                "headline",
                "name",
            ],
        )
    )

    existing_title_keys = {
        (
            x["text"].casefold(),
            x.get("lang", ""),
        )
        for x in title_variants
    }

    for variant in jsonld_title_variants:
        key = (
            variant["text"].casefold(),
            variant.get("lang", ""),
        )

        if key not in existing_title_keys:
            title_variants.append(
                variant
            )

            existing_title_keys.add(
                key
            )


    # -------------------------------------------------------------
    # Abstracts
    # -------------------------------------------------------------

    abstract_entries = _meta_entries(
        parser,
        "citation_abstract",
        "dc.description",
        "dcterms.abstract",
        "dcterms.description",
        "description",
        "og:description",
    )

    abstract_variants = (
        _entries_to_variants(
            abstract_entries,
            page_lang,
        )
    )

    jsonld_abstract_variants = (
        _jsonld_text_variants(
            jsonld_articles,
            [
                "abstract",
                "description",
            ],
        )
    )

    existing_abstract_keys = {
        (
            x["text"].casefold(),
            x.get("lang", ""),
        )
        for x in abstract_variants
    }

    for variant in jsonld_abstract_variants:
        key = (
            variant["text"].casefold(),
            variant.get("lang", ""),
        )

        if key not in existing_abstract_keys:
            abstract_variants.append(
                variant
            )

            existing_abstract_keys.add(
                key
            )


    # -------------------------------------------------------------
    # Keywords
    # -------------------------------------------------------------

    keyword_entries = _meta_entries(
        parser,
        "citation_keywords",
        "keywords",
        "dc.subject",
        "dcterms.subject",
    )

    keyword_groups = {}

    for item in keyword_entries:
        lang = _normalize_lang(
            item.get("lang")
            or page_lang
        )

        keyword_groups.setdefault(
            lang,
            [],
        )

        keyword_groups[lang].extend(
            _split_keywords(
                [
                    item.get(
                        "content",
                        "",
                    )
                ]
            )
        )

    for item in _jsonld_keyword_variants(
        jsonld_articles
    ):
        lang = _normalize_lang(
            item.get("lang")
            or page_lang
        )

        keyword_groups.setdefault(
            lang,
            [],
        )

        keyword_groups[lang].extend(
            item.get(
                "values",
                [],
            )
        )

    keyword_groups = {
        lang: _unique(values)
        for lang, values
        in keyword_groups.items()
        if values
    }


    # -------------------------------------------------------------
    # Detect main language
    # -------------------------------------------------------------

    language = _first(
        _meta_values(
            parser,
            "citation_language",
            "dc.language",
            "dcterms.language",
            "content-language",
        )
    )

    language = _normalize_lang(
        language
        or page_lang
    )

    if not language:
        explicit_langs = [
            item.get("lang")
            for item in title_variants
            if item.get("lang")
        ]

        if explicit_langs:
            language = _normalize_lang(
                explicit_langs[0]
            )


    # -------------------------------------------------------------
    # Main and English fields
    # -------------------------------------------------------------

    title_en = _variant_for_language(
        title_variants,
        "en",
    )

    abstract_en = _variant_for_language(
        abstract_variants,
        "en",
    )

    keywords_en = (
        keyword_groups.get(
            "en",
            [],
        )
    )

    title_original = ""

    if language:
        title_original = (
            _variant_for_language(
                title_variants,
                language,
            )
        )

    if not title_original:
        title_original = _first(
            [
                x.get("text")
                for x in title_variants
            ]
        )

    abstract_original = ""

    if language:
        abstract_original = (
            _variant_for_language(
                abstract_variants,
                language,
            )
        )

    if not abstract_original:
        abstract_original = _first(
            [
                x.get("text")
                for x in abstract_variants
            ]
        )

    keywords_original = (
        keyword_groups.get(
            language,
            [],
        )
        if language
        else []
    )

    if not keywords_original:
        for values in keyword_groups.values():
            if values:
                keywords_original = values
                break


    # -------------------------------------------------------------
    # Authors
    # -------------------------------------------------------------

    authors = _meta_values(
        parser,
        "citation_author",
        "dc.creator",
        "dcterms.creator",
    )

    if not authors:
        for ld in jsonld_articles:
            raw_authors = (
                ld.get("author")
                or []
            )

            if isinstance(
                raw_authors,
                dict,
            ):
                raw_authors = [
                    raw_authors
                ]

            if not isinstance(
                raw_authors,
                list,
            ):
                continue

            for item in raw_authors:
                if isinstance(
                    item,
                    dict,
                ):
                    name = _clean(
                        item.get("name")
                    )

                else:
                    name = _clean(
                        item
                    )

                if name:
                    authors.append(
                        name
                    )

    authors = _unique(
        authors
    )


    # -------------------------------------------------------------
    # Bibliographic fields
    # -------------------------------------------------------------

    doi = normalize_doi(
        _first(
            _meta_values(
                parser,
                "citation_doi",
                "dc.identifier",
                "dcterms.identifier",
                "prism.doi",
            )
        )
    )

    if not doi:
        for ld in jsonld_articles:
            ident = ld.get(
                "identifier"
            )

            if isinstance(
                ident,
                dict,
            ):
                ident = (
                    ident.get("value")
                    or ident.get("@id")
                    or ident.get("name")
                    or ""
                )

            candidate = normalize_doi(
                ident
            )

            if candidate.startswith(
                "10."
            ):
                doi = candidate
                break


    journal = _first(
        _meta_values(
            parser,
            "citation_journal_title",
            "prism.publicationname",
            "dc.source",
        )
    )


    volume = _first(
        _meta_values(
            parser,
            "citation_volume",
            "prism.volume",
        )
    )


    issue = _first(
        _meta_values(
            parser,
            "citation_issue",
            "prism.number",
        )
    )


    first_page = _first(
        _meta_values(
            parser,
            "citation_firstpage",
            "prism.startingpage",
        )
    )


    last_page = _first(
        _meta_values(
            parser,
            "citation_lastpage",
            "prism.endingpage",
        )
    )


    pages = (
        f"{first_page}-{last_page}"
        if first_page
        and last_page
        else first_page
    )


    date = _first(
        _meta_values(
            parser,
            "citation_publication_date",
            "citation_date",
            "dc.date",
            "dcterms.issued",
            "prism.publicationdate",
        )
    )

    if not date:
        for ld in jsonld_articles:
            date = _clean(
                ld.get(
                    "datePublished"
                )
            )

            if date:
                break


    year_match = re.search(
        r"\b(?:19|20)\d{2}\b",
        date or "",
    )

    year = (
        int(
            year_match.group()
        )
        if year_match
        else 0
    )


    # -------------------------------------------------------------
    # PDF
    # -------------------------------------------------------------

    pdf = _first(
        _meta_values(
            parser,
            "citation_pdf_url",
        )
    )

    if not pdf:
        for link in parser.links:
            rel = link.get(
                "rel",
                "",
            ).lower()

            typ = link.get(
                "type",
                "",
            ).lower()

            href = link.get(
                "href",
                "",
            )

            if (
                href
                and (
                    "alternate" in rel
                    or "enclosure" in rel
                )
                and "pdf" in typ
            ):
                pdf = urllib.parse.urljoin(
                    final_url,
                    href,
                )
                break


    # -------------------------------------------------------------
    # Canonical URL
    # -------------------------------------------------------------

    canonical = ""

    for link in parser.links:
        if (
            "canonical"
            in link.get(
                "rel",
                "",
            ).lower()
            and link.get(
                "href"
            )
        ):
            canonical = urllib.parse.urljoin(
                final_url,
                link["href"],
            )

            break


    # -------------------------------------------------------------
    # Output
    # -------------------------------------------------------------

    return {
        "title": title_original,
        "titleOriginal": title_original,
        "titleEn": title_en,
        "titles": _unique(
            [
                x.get("text")
                for x in title_variants
            ]
        ),
        "titleVariants": title_variants,

        "authors": authors,

        "abstract": abstract_original,
        "abstractOriginal": abstract_original,
        "abstractEn": abstract_en,
        "abstracts": _unique(
            [
                x.get("text")
                for x in abstract_variants
            ]
        ),
        "abstractVariants": abstract_variants,

        "keywords": keywords_original,
        "keywordsOriginal": keywords_original,
        "keywordsEn": keywords_en,

        "keywordVariants": [
            {
                "text": keyword,
                "lang": lang,
            }
            for lang, values
            in keyword_groups.items()
            for keyword in values
        ],

        "doi": doi,

        "journalTitle": journal,

        "volume": volume,
        "issue": issue,
        "pages": pages,

        "date": date,
        "year": year,

        "languageCode": language,

        "pdf": pdf,

        "url": (
            canonical
            or final_url
        ),
    }


# ---------------------------------------------------------------------
# Crossref
# ---------------------------------------------------------------------

def fetch_crossref(
    doi,
    archive_dir: Path,
):
    doi = normalize_doi(
        doi
    )

    url = (
        CROSSREF
        + urllib.parse.quote(
            doi,
            safe="",
        )
    )

    raw = _request(
        url,
        accept="application/json",
    )

    archive_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        hashlib.sha256(
            doi.encode()
        ).hexdigest()[:24]
        + ".json"
    )

    (
        archive_dir
        / filename
    ).write_bytes(
        raw
    )

    data = json.loads(
        raw
    )

    return (
        data.get(
            "message"
        )
        or {}
    )


def normalize_crossref(
    message,
):
    title = _clean(
        _first(
            message.get(
                "title"
            )
            or []
        )
    )

    abstract = _clean(
        message.get(
            "abstract"
        )
    )

    authors = []

    for author in (
        message.get(
            "author"
        )
        or []
    ):
        name = _clean(
            " ".join(
                x
                for x in [
                    author.get(
                        "given",
                        "",
                    ),
                    author.get(
                        "family",
                        "",
                    ),
                ]
                if x
            )
        )

        if name:
            authors.append(
                name
            )

    authors = _unique(
        authors
    )

    subjects = [
        _clean(x)
        for x in (
            message.get(
                "subject"
            )
            or []
        )
        if _clean(x)
    ]

    containers = [
        _clean(x)
        for x in (
            message.get(
                "container-title"
            )
            or []
        )
        if _clean(x)
    ]

    doi = normalize_doi(
        message.get(
            "DOI"
        )
    )

    url = (
        _clean(
            message.get(
                "URL"
            )
        )
        or (
            "https://doi.org/"
            + doi
            if doi
            else ""
        )
    )

    volume = _clean(
        message.get(
            "volume"
        )
    )

    issue = _clean(
        message.get(
            "issue"
        )
    )

    pages = _clean(
        message.get(
            "page"
        )
        or message.get(
            "article-number"
        )
    )

    date_parts = (
        (
            (
                message.get(
                    "published-print"
                )
                or message.get(
                    "published-online"
                )
                or message.get(
                    "issued"
                )
                or {}
            ).get(
                "date-parts"
            )
            or [[]]
        )[0]
    )

    year = (
        int(
            date_parts[0]
        )
        if date_parts
        else 0
    )

    date = (
        "-".join(
            str(x)
            for x in date_parts
        )
        if date_parts
        else ""
    )

    language = _normalize_lang(
        message.get(
            "language"
        )
    )

    title_en = (
        title
        if language == "en"
        else ""
    )

    abstract_en = (
        abstract
        if language == "en"
        else ""
    )

    keywords_en = (
        subjects
        if language == "en"
        else []
    )

    return {
        "title": title,
        "titleOriginal": title,
        "titleEn": title_en,

        "titles": (
            [title]
            if title
            else []
        ),

        "titleVariants": (
            [
                {
                    "text": title,
                    "lang": language,
                }
            ]
            if title
            else []
        ),

        "authors": authors,

        "abstract": abstract,
        "abstractOriginal": abstract,
        "abstractEn": abstract_en,

        "abstracts": (
            [abstract]
            if abstract
            else []
        ),

        "abstractVariants": (
            [
                {
                    "text": abstract,
                    "lang": language,
                }
            ]
            if abstract
            else []
        ),

        "keywords": subjects,
        "keywordsOriginal": subjects,
        "keywordsEn": keywords_en,

        "keywordVariants": [
            {
                "text": keyword,
                "lang": language,
            }
            for keyword in subjects
        ],

        "doi": doi,

        "journalTitle": (
            containers[0]
            if containers
            else ""
        ),

        "volume": volume,
        "issue": issue,
        "pages": pages,

        "date": date,
        "year": year,

        "languageCode": language,

        "url": url,
        "pdf": "",
    }


# ---------------------------------------------------------------------
# Prefer official metadata
# ---------------------------------------------------------------------

def _prefer(
    primary,
    fallback,
    key,
):
    value = primary.get(
        key
    )

    if value not in (
        None,
        "",
        [],
        {},
        0,
    ):
        return value

    return fallback.get(
        key
    )


def _merge_variants(
    first,
    second,
):
    out = []
    seen = set()

    for values in [
        first or [],
        second or [],
    ]:
        for item in values:
            if not isinstance(
                item,
                dict,
            ):
                continue

            text = _clean(
                item.get(
                    "text"
                )
            )

            if not text:
                continue

            lang = _normalize_lang(
                item.get(
                    "lang"
                )
            )

            key = (
                text.casefold(),
                lang,
            )

            if key in seen:
                continue

            seen.add(
                key
            )

            out.append(
                {
                    "text": text,
                    "lang": lang,
                }
            )

    return out


# ---------------------------------------------------------------------
# Canonical DOI record
# ---------------------------------------------------------------------

def canonical_record_from_doi(
    doi,
    journal,
    root: Path,
    *,
    discovery=None,
):
    """Resolve DOI to official + Crossref metadata.

    Publisher metadata has priority.
    English fields are populated only when they are explicitly present
    in the source metadata.
    """

    doi = normalize_doi(
        doi
    )

    now = datetime.now(
        timezone.utc
    ).isoformat()

    base = (
        root
        / "harvest/raw"
        / journal["id"]
    )


    # -------------------------------------------------------------
    # Crossref
    # -------------------------------------------------------------

    crossref_raw = fetch_crossref(
        doi,
        base / "crossref",
    )

    cr = normalize_crossref(
        crossref_raw
    )


    # -------------------------------------------------------------
    # Publisher
    # -------------------------------------------------------------

    publisher = {}

    landing_url = (
        cr.get("url")
        or (
            "https://doi.org/"
            + doi
        )
    )

    publisher_error = ""

    if landing_url:
        try:
            raw = _request(
                landing_url,
                accept=(
                    "text/html,"
                    "application/xhtml+xml"
                ),
            )

            official_dir = (
                base
                / "official"
            )

            official_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            name = (
                hashlib.sha256(
                    doi.encode()
                ).hexdigest()[:24]
                + ".html"
            )

            (
                official_dir
                / name
            ).write_bytes(
                raw
            )

            publisher = (
                parse_publisher_html(
                    raw,
                    landing_url,
                )
            )

        except Exception as exc:
            publisher_error = str(
                exc
            )


    # -------------------------------------------------------------
    # Core canonical metadata
    # -------------------------------------------------------------

    canonical = {}

    for key in (
        "title",
        "titleOriginal",
        "authors",
        "abstract",
        "abstractOriginal",
        "keywords",
        "keywordsOriginal",
        "doi",
        "journalTitle",
        "volume",
        "issue",
        "pages",
        "date",
        "year",
        "languageCode",
        "pdf",
        "url",
    ):
        canonical[key] = _prefer(
            publisher,
            cr,
            key,
        )


    if (
        not canonical.get(
            "title"
        )
        or not canonical.get(
            "doi"
        )
    ):
        raise RuntimeError(
            "Metadados canônicos insuficientes "
            f"para DOI {doi}"
        )


    # -------------------------------------------------------------
    # Multilingual variants
    # -------------------------------------------------------------

    title_variants = _merge_variants(
        publisher.get(
            "titleVariants"
        ),
        cr.get(
            "titleVariants"
        ),
    )

    abstract_variants = _merge_variants(
        publisher.get(
            "abstractVariants"
        ),
        cr.get(
            "abstractVariants"
        ),
    )

    keyword_variants = _merge_variants(
        publisher.get(
            "keywordVariants"
        ),
        cr.get(
            "keywordVariants"
        ),
    )


    title_en = (
        publisher.get(
            "titleEn"
        )
        or cr.get(
            "titleEn"
        )
        or _variant_for_language(
            title_variants,
            "en",
        )
        or ""
    )

    abstract_en = (
        publisher.get(
            "abstractEn"
        )
        or cr.get(
            "abstractEn"
        )
        or _variant_for_language(
            abstract_variants,
            "en",
        )
        or ""
    )

    keywords_en = (
        publisher.get(
            "keywordsEn"
        )
        or cr.get(
            "keywordsEn"
        )
        or [
            item["text"]
            for item
            in keyword_variants
            if _normalize_lang(
                item.get("lang")
            ) == "en"
        ]
    )

    keywords_en = _unique(
        keywords_en
    )


    # -------------------------------------------------------------
    # Main language
    # -------------------------------------------------------------

    lang = _normalize_lang(
        canonical.get(
            "languageCode"
        )
    )

    lang_name = {
        "en": "English",
        "pt": "Portuguese",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
    }.get(
        lang,
        lang,
    )


    title_original = (
        canonical.get(
            "titleOriginal"
        )
        or canonical.get(
            "title"
        )
        or ""
    )

    abstract_original = (
        canonical.get(
            "abstractOriginal"
        )
        or canonical.get(
            "abstract"
        )
        or ""
    )

    keywords_original = (
        canonical.get(
            "keywordsOriginal"
        )
        or canonical.get(
            "keywords"
        )
        or []
    )

    if not isinstance(
        keywords_original,
        list,
    ):
        keywords_original = (
            _split_keywords(
                [
                    str(
                        keywords_original
                    )
                ]
            )
        )


    # -------------------------------------------------------------
    # Metadata status
    # -------------------------------------------------------------

    if (
        title_en
        or abstract_en
        or keywords_en
    ):
        metadata_english_status = (
            "source"
        )

    elif lang == "en":
        metadata_english_status = (
            "source"
        )

    else:
        metadata_english_status = (
            "pending_translation"
        )


    # -------------------------------------------------------------
    # ID
    # -------------------------------------------------------------

    rid = (
        hashlib.sha256(
            (
                journal["id"]
                + "|doi|"
                + doi.lower()
            ).encode()
        )
        .hexdigest()[:24]
    )


    # -------------------------------------------------------------
    # Provenance
    # -------------------------------------------------------------

    discovery = (
        discovery
        or {}
    )

    provenance = []

    if publisher.get(
        "title"
    ):
        provenance.append(
            "Publisher landing page"
        )

    if cr.get(
        "title"
    ):
        provenance.append(
            "Crossref publisher deposit"
        )

    if discovery.get(
        "provider"
    ):
        provenance.append(
            discovery["provider"]
            + " (discovery/metrics only)"
        )

    provenance = _unique(
        provenance
    )


    # -------------------------------------------------------------
    # Final record
    # -------------------------------------------------------------

    record = {
        "id": rid,

        "journal": journal["id"],

        "title": (
            title_original
        ),

        "titleOriginal": (
            title_original
        ),

        "titleEn": (
            title_en
        ),

        "titles": _unique(
            [
                item.get(
                    "text"
                )
                for item
                in title_variants
            ]
            + [
                title_original,
                title_en,
            ]
        ),

        "titleVariants": (
            title_variants
        ),

        "authors": (
            canonical.get(
                "authors"
            )
            or []
        ),

        "contributors": [],

        "institutions": [],

        "abstract": (
            abstract_original
        ),

        "abstractOriginal": (
            abstract_original
        ),

        "abstractEn": (
            abstract_en
        ),

        "abstracts": _unique(
            [
                item.get(
                    "text"
                )
                for item
                in abstract_variants
            ]
            + [
                abstract_original,
                abstract_en,
            ]
        ),

        "abstractVariants": (
            abstract_variants
        ),

        "keywords": (
            keywords_original
        ),

        "keywordsOriginal": (
            keywords_original
        ),

        "keywordsEn": (
            keywords_en
        ),

        "keywordVariants": (
            keyword_variants
        ),

        "metadataEnglishStatus": (
            metadata_english_status
        ),

        "year": int(
            canonical.get(
                "year"
            )
            or 0
        ),

        "dates": (
            [
                canonical.get(
                    "date"
                )
            ]
            if canonical.get(
                "date"
            )
            else []
        ),

        "language": lang_name,

        "languageCode": lang,

        "languages": _unique(
            [
                lang,
                *[
                    item.get(
                        "lang"
                    )
                    for item
                    in title_variants
                ],
                *[
                    item.get(
                        "lang"
                    )
                    for item
                    in abstract_variants
                ],
            ]
        ),

        "type": "article",

        "types": [
            "article"
        ],

        "doi": doi,

        "url": (
            canonical.get(
                "url"
            )
            or landing_url
        ),

        "pdf": (
            canonical.get(
                "pdf"
            )
            or ""
        ),

        "volume": (
            canonical.get(
                "volume"
            )
            or ""
        ),

        "issue": (
            canonical.get(
                "issue"
            )
            or ""
        ),

        "pages": (
            canonical.get(
                "pages"
            )
            or ""
        ),

        "rights": [],

        "openAccess": (
            discovery.get(
                "openAccess"
            )
        ),

        "source": "; ".join(
            provenance
        ),

        "provenance": (
            provenance
        ),

        "metadataAuthority": (
            "publisher"
            if publisher.get(
                "title"
            )
            else "crossref"
        ),

        "harvestedAt": now,
    }


    if publisher_error:
        record[
            "publisherMetadataError"
        ] = publisher_error


    if discovery.get(
        "openalexId"
    ):
        record[
            "openalexId"
        ] = discovery[
            "openalexId"
        ]


    if (
        discovery.get(
            "citedByCount"
        )
        is not None
    ):
        record[
            "citedByCount"
        ] = discovery[
            "citedByCount"
        ]


    return record

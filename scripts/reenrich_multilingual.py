#!/usr/bin/env python3
"""Re-enrich existing BuscaEM backfile records with multilingual metadata.

This script does NOT recollect the Crossref backfile.

It:
1. opens records already stored in harvest/backfile_catalog.json;
2. reuses archived publisher HTML whenever available;
3. only accesses the publisher page again when the archived HTML is missing;
4. extracts source-provided multilingual metadata;
5. updates titleEn, abstractEn, keywordsEn and language variants;
6. republishes the public BuscaEM catalogue.

No automatic translation is performed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(
    0,
    str(ROOT / "scripts"),
)

from official_metadata import (
    parse_publisher_html,
    normalize_doi,
    _request,
)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def clean(value):
    if value is None:
        return ""

    return " ".join(
        str(value).split()
    ).strip()


def normalize_lang(value):
    value = clean(
        value
    ).lower().replace(
        "_",
        "-",
    )

    aliases = {
        "eng": "en",
        "english": "en",

        "por": "pt",
        "portuguese": "pt",
        "português": "pt",
        "portugues": "pt",

        "spa": "es",
        "spanish": "es",
        "español": "es",
        "espanol": "es",

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

    if value:
        return value.split("-")[0]

    return ""


def unique(values):
    result = []
    seen = set()

    for value in values:

        if value in (
            None,
            "",
            [],
            {},
        ):
            continue

        if isinstance(
            value,
            str,
        ):
            key = (
                "str",
                value.strip().casefold(),
            )

        else:
            key = (
                type(value).__name__,
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )

        if key in seen:
            continue

        seen.add(
            key
        )

        result.append(
            value
        )

    return result


def merge_variants(
    first,
    second,
):
    result = []
    seen = set()

    for group in (
        first or [],
        second or [],
    ):
        for item in group:

            if not isinstance(
                item,
                dict,
            ):
                continue

            text = clean(
                item.get(
                    "text"
                )
            )

            if not text:
                continue

            lang = normalize_lang(
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

            result.append(
                {
                    "text": text,
                    "lang": lang,
                }
            )

    return result


def values_for_language(
    variants,
    language,
):
    language = normalize_lang(
        language
    )

    return unique(
        [
            item.get(
                "text"
            )
            for item
            in (
                variants
                or []
            )
            if isinstance(
                item,
                dict,
            )
            and normalize_lang(
                item.get(
                    "lang"
                )
            ) == language
            and clean(
                item.get(
                    "text"
                )
            )
        ]
    )


def load_json(
    path,
    default,
):
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return default


def save_json(
    path,
    value,
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix
        + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(
        path
    )


# ---------------------------------------------------------------------
# Apply publisher metadata
# ---------------------------------------------------------------------

def apply_publisher_metadata(
    record,
    publisher,
):

    changed = False


    # -------------------------------------------------------------
    # Core fields
    # -------------------------------------------------------------

    mapping = {
        "authors": "authors",
        "volume": "volume",
        "issue": "issue",
        "pages": "pages",
        "pdf": "pdf",
        "url": "url",
        "year": "year",
        "languageCode": "languageCode",
    }

    for source_key, target_key in mapping.items():

        value = publisher.get(
            source_key
        )

        if value not in (
            None,
            "",
            [],
            {},
            0,
        ):

            if record.get(
                target_key
            ) != value:

                record[
                    target_key
                ] = value

                changed = True


    # -------------------------------------------------------------
    # Original title
    # -------------------------------------------------------------

    title_original = (
        publisher.get(
            "titleOriginal"
        )
        or publisher.get(
            "title"
        )
        or ""
    )

    if title_original:

        if record.get(
            "titleOriginal"
        ) != title_original:

            record[
                "titleOriginal"
            ] = title_original

            changed = True

        if record.get(
            "title"
        ) != title_original:

            record[
                "title"
            ] = title_original

            changed = True


    # -------------------------------------------------------------
    # English title
    # -------------------------------------------------------------

    title_en = (
        publisher.get(
            "titleEn"
        )
        or ""
    )

    if (
        title_en
        and record.get(
            "titleEn"
        ) != title_en
    ):
        record[
            "titleEn"
        ] = title_en

        changed = True


    # -------------------------------------------------------------
    # Title variants
    # -------------------------------------------------------------

    title_variants = merge_variants(
        publisher.get(
            "titleVariants"
        ),
        record.get(
            "titleVariants"
        ),
    )

    if (
        title_variants
        != record.get(
            "titleVariants",
            [],
        )
    ):
        record[
            "titleVariants"
        ] = title_variants

        changed = True


    record[
        "titles"
    ] = unique(
        [
            record.get(
                "titleOriginal"
            ),
            record.get(
                "titleEn"
            ),
            *[
                item.get(
                    "text"
                )
                for item
                in record.get(
                    "titleVariants",
                    [],
                )
                if isinstance(
                    item,
                    dict,
                )
            ],
        ]
    )


    # -------------------------------------------------------------
    # Original abstract
    # -------------------------------------------------------------

    abstract_original = (
        publisher.get(
            "abstractOriginal"
        )
        or publisher.get(
            "abstract"
        )
        or ""
    )

    if abstract_original:

        if (
            record.get(
                "abstractOriginal"
            )
            != abstract_original
        ):
            record[
                "abstractOriginal"
            ] = abstract_original

            changed = True

        if (
            record.get(
                "abstract"
            )
            != abstract_original
        ):
            record[
                "abstract"
            ] = abstract_original

            changed = True


    # -------------------------------------------------------------
    # English abstract
    # -------------------------------------------------------------

    abstract_en = (
        publisher.get(
            "abstractEn"
        )
        or ""
    )

    if (
        abstract_en
        and record.get(
            "abstractEn"
        ) != abstract_en
    ):

        record[
            "abstractEn"
        ] = abstract_en

        changed = True


    # -------------------------------------------------------------
    # Abstract variants
    # -------------------------------------------------------------

    abstract_variants = merge_variants(
        publisher.get(
            "abstractVariants"
        ),
        record.get(
            "abstractVariants"
        ),
    )

    if (
        abstract_variants
        != record.get(
            "abstractVariants",
            [],
        )
    ):
        record[
            "abstractVariants"
        ] = abstract_variants

        changed = True


    record[
        "abstracts"
    ] = unique(
        [
            record.get(
                "abstractOriginal"
            ),
            record.get(
                "abstractEn"
            ),
            *[
                item.get(
                    "text"
                )
                for item
                in record.get(
                    "abstractVariants",
                    [],
                )
                if isinstance(
                    item,
                    dict,
                )
            ],
        ]
    )


    # -------------------------------------------------------------
    # Original keywords
    # -------------------------------------------------------------

    keywords_original = (
        publisher.get(
            "keywordsOriginal"
        )
        or publisher.get(
            "keywords"
        )
        or []
    )

    if keywords_original:

        if (
            record.get(
                "keywordsOriginal"
            )
            != keywords_original
        ):

            record[
                "keywordsOriginal"
            ] = keywords_original

            changed = True

        if (
            record.get(
                "keywords"
            )
            != keywords_original
        ):

            record[
                "keywords"
            ] = keywords_original

            changed = True


    # -------------------------------------------------------------
    # English keywords
    # -------------------------------------------------------------

    keywords_en = (
        publisher.get(
            "keywordsEn"
        )
        or []
    )

    if (
        keywords_en
        and record.get(
            "keywordsEn"
        ) != keywords_en
    ):
        record[
            "keywordsEn"
        ] = keywords_en

        changed = True


    # -------------------------------------------------------------
    # Keyword variants
    # -------------------------------------------------------------

    keyword_variants = merge_variants(
        publisher.get(
            "keywordVariants"
        ),
        record.get(
            "keywordVariants"
        ),
    )

    if (
        keyword_variants
        != record.get(
            "keywordVariants",
            [],
        )
    ):
        record[
            "keywordVariants"
        ] = keyword_variants

        changed = True


    if not record.get(
        "keywordsEn"
    ):

        recovered_keywords_en = (
            values_for_language(
                record.get(
                    "keywordVariants"
                ),
                "en",
            )
        )

        if recovered_keywords_en:

            record[
                "keywordsEn"
            ] = recovered_keywords_en

            changed = True


    # -------------------------------------------------------------
    # Language
    # -------------------------------------------------------------

    lang = normalize_lang(
        record.get(
            "languageCode"
        )
    )

    record[
        "languageCode"
    ] = lang

    record[
        "language"
    ] = {
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


    languages = unique(
        [
            lang,

            *[
                normalize_lang(
                    item.get(
                        "lang"
                    )
                )
                for item
                in record.get(
                    "titleVariants",
                    [],
                )
                if isinstance(
                    item,
                    dict,
                )
            ],

            *[
                normalize_lang(
                    item.get(
                        "lang"
                    )
                )
                for item
                in record.get(
                    "abstractVariants",
                    [],
                )
                if isinstance(
                    item,
                    dict,
                )
            ],

            *[
                normalize_lang(
                    item.get(
                        "lang"
                    )
                )
                for item
                in record.get(
                    "keywordVariants",
                    [],
                )
                if isinstance(
                    item,
                    dict,
                )
            ],
        ]
    )

    record[
        "languages"
    ] = languages


    # -------------------------------------------------------------
    # English metadata status
    # -------------------------------------------------------------

    old_status = record.get(
        "metadataEnglishStatus"
    )

    if (
        record.get(
            "titleEn"
        )
        or record.get(
            "abstractEn"
        )
        or record.get(
            "keywordsEn"
        )
        or lang == "en"
    ):
        new_status = "source"

    else:
        new_status = (
            "pending_translation"
        )

    if old_status != new_status:

        record[
            "metadataEnglishStatus"
        ] = new_status

        changed = True


    # -------------------------------------------------------------
    # Provenance
    # -------------------------------------------------------------

    provenance = unique(
        [
            "Publisher landing page",
            *(
                record.get(
                    "provenance"
                )
                or []
            ),
        ]
    )

    record[
        "provenance"
    ] = provenance

    record[
        "source"
    ] = "; ".join(
        provenance
    )

    if publisher.get(
        "title"
    ):
        record[
            "metadataAuthority"
        ] = "publisher"


    record[
        "multilingualEnrichedAt"
    ] = datetime.now(
        timezone.utc
    ).isoformat()


    return changed


# ---------------------------------------------------------------------
# Load publisher HTML
# ---------------------------------------------------------------------

def publisher_metadata_for_record(
    record,
    journal_id,
    fetch_missing=True,
):

    doi = normalize_doi(
        record.get(
            "doi"
        )
    )

    if not doi:
        raise RuntimeError(
            "record has no DOI"
        )


    official_dir = (
        ROOT
        / "harvest/raw"
        / journal_id
        / "official"
    )


    filename = (
        hashlib.sha256(
            doi.encode()
        ).hexdigest()[:24]
        + ".html"
    )


    html_path = (
        official_dir
        / filename
    )


    # -------------------------------------------------------------
    # Prefer archived publisher HTML
    # -------------------------------------------------------------

    if html_path.exists():

        raw = html_path.read_bytes()

        return (
            parse_publisher_html(
                raw,
                record.get(
                    "url"
                )
                or (
                    "https://doi.org/"
                    + doi
                ),
            ),
            "archive",
        )


    # -------------------------------------------------------------
    # Fetch publisher page only if necessary
    # -------------------------------------------------------------

    if not fetch_missing:
        raise FileNotFoundError(
            str(
                html_path
            )
        )


    url = (
        record.get(
            "url"
        )
        or (
            "https://doi.org/"
            + doi
        )
    )


    raw = _request(
        url,
        accept=(
            "text/html,"
            "application/xhtml+xml"
        ),
        timeout=60,
        retries=3,
    )


    official_dir.mkdir(
        parents=True,
        exist_ok=True,
    )


    html_path.write_bytes(
        raw
    )


    return (
        parse_publisher_html(
            raw,
            url,
        ),
        "network",
    )


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():

    parser = argparse.ArgumentParser()


    parser.add_argument(
        "--journal",
        help=(
            "Comma-separated journal IDs. "
            "Default: all records currently in "
            "harvest/backfile_catalog.json"
        ),
    )


    parser.add_argument(
        "--no-network",
        action="store_true",
        help=(
            "Use only publisher HTML already "
            "archived in harvest/raw."
        ),
    )


    parser.add_argument(
        "--delay",
        type=float,
        default=0.20,
        help=(
            "Delay between network requests. "
            "Default: 0.20 seconds."
        ),
    )


    parser.add_argument(
        "--checkpoint",
        type=int,
        default=50,
        help=(
            "Save backfile_catalog.json every N "
            "processed records."
        ),
    )


    args = parser.parse_args()


    catalog_path = (
        ROOT
        / "harvest/backfile_catalog.json"
    )


    catalog = load_json(
        catalog_path,
        {
            "articles": []
        },
    )


    articles = catalog.get(
        "articles",
        [],
    )


    wanted = None

    if args.journal:
        wanted = {
            value.strip()
            for value
            in args.journal.split(
                ","
            )
            if value.strip()
        }


    selected = [
        article
        for article
        in articles
        if (
            wanted is None
            or article.get(
                "journal"
            ) in wanted
        )
    ]


    print(
        f"Records selected: {len(selected)}"
    )


    stats = {
        "processed": 0,
        "updated": 0,
        "englishFound": 0,
        "archiveUsed": 0,
        "networkUsed": 0,
        "errors": 0,
    }


    errors = []


    for index, record in enumerate(
        selected,
        start=1,
    ):

        journal_id = record.get(
            "journal"
        )

        doi = normalize_doi(
            record.get(
                "doi"
            )
        )


        if (
            not journal_id
            or not doi
        ):
            continue


        try:

            publisher, source = (
                publisher_metadata_for_record(
                    record,
                    journal_id,
                    fetch_missing=(
                        not args.no_network
                    ),
                )
            )


            if source == "archive":
                stats[
                    "archiveUsed"
                ] += 1

            else:
                stats[
                    "networkUsed"
                ] += 1


            changed = (
                apply_publisher_metadata(
                    record,
                    publisher,
                )
            )


            if changed:
                stats[
                    "updated"
                ] += 1


            if (
                record.get(
                    "titleEn"
                )
                or record.get(
                    "abstractEn"
                )
                or record.get(
                    "keywordsEn"
                )
            ):
                stats[
                    "englishFound"
                ] += 1


            stats[
                "processed"
            ] += 1


        except Exception as exc:

            stats[
                "errors"
            ] += 1

            errors.append(
                {
                    "journal": journal_id,
                    "doi": doi,
                    "error": str(
                        exc
                    ),
                }
            )


        # ---------------------------------------------------------
        # Checkpoint
        # ---------------------------------------------------------

        if (
            args.checkpoint > 0
            and index
            % args.checkpoint
            == 0
        ):

            save_json(
                catalog_path,
                {
                    "articles": articles
                },
            )

            print(
                f"Checkpoint {index}/{len(selected)} "
                f"| updated={stats['updated']} "
                f"| english={stats['englishFound']} "
                f"| errors={stats['errors']}"
            )


        if (
            stats["networkUsed"] > 0
            and args.delay > 0
        ):
            time.sleep(
                args.delay
            )


    # -----------------------------------------------------------------
    # Save enriched backfile
    # -----------------------------------------------------------------

    save_json(
        catalog_path,
        {
            "articles": articles
        },
    )


    report = {
        "generatedAt": datetime.now(
            timezone.utc
        ).isoformat(),

        "journals": (
            sorted(
                wanted
            )
            if wanted
            else "all-backfile-records"
        ),

        **stats,

        "errors": errors,
    }


    report_path = (
        ROOT
        / "harvest/"
        "MULTILINGUAL_ENRICHMENT_STATUS.json"
    )


    save_json(
        report_path,
        report,
    )


    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )


    # -----------------------------------------------------------------
    # Rebuild public catalogue
    # -----------------------------------------------------------------

    print(
        "\nRebuilding public BuscaEM catalogue..."
    )


    import publish

    publish.publish(
        ROOT
    )


    print(
        "\nMultilingual re-enrichment complete."
    )


if __name__ == "__main__":
    main()

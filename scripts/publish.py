"""Generate Cloudflare Pages chunks from the harvested multilingual catalogue."""

import json
import gzip
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FIELDS = """
id journal title titleOriginal titleEn authors institutions abstract
abstractOriginal abstractEn keywords keywordsOriginal keywordsEn
metadataEnglishStatus year language languageCode type doi url pdf
openAccess oaiIdentifier source provenance scieloUrl harvestedAt
""".split()


def load_json(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)

    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8"
    )


def migrate(a):
    lang = str(a.get("language") or "").lower()

    labels = {
        "português": "Portuguese",
        "portugues": "Portuguese",
        "pt_br": "Portuguese",
        "pt-br": "Portuguese",
        "pt": "Portuguese",
        "por": "Portuguese",
        "inglês": "English",
        "ingles": "English",
        "en": "English",
        "eng": "English",
        "espanhol": "Spanish",
        "es": "Spanish",
        "spa": "Spanish",
        "fra": "French",
        "fr": "French"
    }

    if lang in labels:
        a["language"] = labels[lang]

    is_en = (
        lang in {"english", "inglês", "ingles", "en", "eng"}
        or lang.startswith("en-")
    )

    title = a.get("title") or ""
    abstract = a.get("abstract") or ""
    kws = a.get("keywords") or []

    a.setdefault("titleOriginal", title)
    a.setdefault("titleEn", title if is_en else "")

    a.setdefault("abstractOriginal", abstract)
    a.setdefault("abstractEn", abstract if is_en else "")

    a.setdefault("keywordsOriginal", kws)
    a.setdefault("keywordsEn", kws if is_en else [])

    a.setdefault("institutions", [])

    a.setdefault(
        "languageCode",
        "en" if is_en
        else (
            "pt" if "portugu" in lang
            else (
                "es"
                if "espan" in lang or "span" in lang
                else ""
            )
        )
    )

    a.setdefault(
        "metadataEnglishStatus",
        "source" if is_en else "pending_translation"
    )

    a.setdefault(
        "provenance",
        [a.get("source")] if a.get("source") else []
    )

    return a


def merge_catalogs(main_articles, backfile_articles):
    merged = {}

    # Primeiro entram os registros já existentes
    for article in main_articles:
        article_id = article.get("id")
        if article_id:
            merged[article_id] = article

    # Depois entram os novos backfiles
    # DOI é usado também para evitar duplicação entre fontes.
    doi_index = {}

    for article_id, article in merged.items():
        doi = str(article.get("doi") or "").strip().lower()
        if doi:
            doi_index[doi] = article_id

    for article in backfile_articles:
        article_id = article.get("id")

        if not article_id:
            continue

        doi = str(article.get("doi") or "").strip().lower()

        if doi and doi in doi_index:
            existing_id = doi_index[doi]

            # O registro do backfile pode complementar campos faltantes.
            existing = merged[existing_id]

            for key, value in article.items():
                if value not in (None, "", [], {}):
                    if existing.get(key) in (None, "", [], {}):
                        existing[key] = value

            continue

        merged[article_id] = article

        if doi:
            doi_index[doi] = article_id

    return list(merged.values())


def publish(root=ROOT):
    directory = root / "dist/data"

    main_source = root / "harvest/catalog.json.gz"

    if not main_source.exists():
        main_source = directory / "articles.json"

    main_catalog = load_json(main_source)

    main_articles = main_catalog.get("articles", [])

    backfile_path = root / "harvest/backfile_catalog.json"

    if backfile_path.exists():
        try:
            backfile_catalog = load_json(backfile_path)
            backfile_articles = backfile_catalog.get("articles", [])
        except Exception:
            backfile_articles = []
    else:
        backfile_articles = []

    articles = merge_catalogs(
        main_articles,
        backfile_articles
    )

    articles = [
        migrate(article)
        for article in articles
    ]

    articles.sort(
        key=lambda a: (
            a.get("year") or 0,
            a.get("id") or ""
        ),
        reverse=True
    )

    chunks = []

    for offset in range(0, len(articles), 500):
        name = f"records-{offset // 500:03d}.json"

        rows = [
            {
                k: article.get(k)
                for k in FIELDS
            }
            for article in articles[offset:offset + 500]
        ]

        save_json(
            directory / name,
            rows
        )

        chunks.append(name)

    manifest = {
        k: v
        for k, v in main_catalog.items()
        if k != "articles"
    }

    manifest.update(
        chunks=chunks,
        count=len(articles)
    )

    save_json(
        directory / "catalog.json",
        manifest
    )

    for file in directory.glob("records-*.json"):
        if file.name not in chunks:
            file.unlink()

    print(
        f"Public catalog: {manifest['count']} records, "
        f"{len(chunks)} chunks."
    )

    print(
        f"Main catalogue: {len(main_articles)} records."
    )

    print(
        f"Backfile catalogue: {len(backfile_articles)} records."
    )


if __name__ == "__main__":
    publish()

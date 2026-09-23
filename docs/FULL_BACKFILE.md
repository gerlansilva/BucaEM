# Full-backfile collection

This project no longer treats samples/seeds as journal integration.

`python3 scripts/harvest_backfiles.py` paginates until the source is exhausted. It stores each raw Crossref page under `harvest/raw/<journal>/crossref-backfile/` and, for each DOI, attempts to archive the publisher landing page under `harvest/raw/<journal>/official/`.

Crossref is used here as the publisher-deposit fallback, not as an OpenAlex-style discovery substitute. The official landing page wins field-by-field whenever it exposes metadata. OpenAlex is not used by this script.

A journal is `complete: true` in `harvest/FULL_BACKFILE_STATUS.json` only when pagination reaches the end without an error. Interrupted runs preserve `harvest/backfile_state.json` and resume from the saved cursor.

Run every configured source and rebuild the public BuscaEM index with:

```bash
bash scripts/collect_all_backfiles.sh
```

For repositories where a single Action run is too short, use `--max-pages 5`; the next run resumes from the checkpoint. Never infer completeness from the presence of a folder: use `FULL_BACKFILE_STATUS.json`.

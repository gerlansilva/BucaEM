#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Exhaust every configured OAI-PMH source (official repositories).
python3 scripts/harvest.py --full --skip-openalex || true

# 2. Exhaust Bolema's SciELO complement if available in this build.
# harvest.py invokes the SciELO adapter unless --skip-scielo is supplied.

# 3. Exhaust publisher-deposited Crossref backfiles for ALL enabled journals.
#    This catches international publishers and fills historical gaps. Every DOI
#    is then resolved to its official landing page when possible.
python3 scripts/harvest_backfiles.py

# 4. Rebuild the public index from the harvested catalogs.
python3 scripts/reprocess.py || true
python3 scripts/publish.py
python3 scripts/validate.py

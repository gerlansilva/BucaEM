# International harvesting

International and Ibero-American journals configured in `dist/data/journals.json` use the OpenAlex adapter when no preferred native adapter is available.

OpenAlex raw files are created only after a real request succeeds:

`harvest/raw/<journal-id>/openalex/*.json`

Do not commit empty directories to represent coverage.

The adapter stores source provenance (`openalexId`, `source`, `provenance`), DOI, title, abstract when available, author names, institutions, keywords/topics, language, year, OA status, landing page and OA PDF URL when OpenAlex exposes one.

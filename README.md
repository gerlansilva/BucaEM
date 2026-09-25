# BuscaEM — código completo (estrutura pronta para GitHub + Cloudflare Pages)

Este pacote contém um site estático funcional e o novo pipeline genérico OJS/OAI-PMH.

## Estrutura
- `dist/`: site publicado no Cloudflare Pages.
- `dist/data/`: manifesto, revistas e chunks de artigos gerados.
- `scripts/audit_sources.py`: detecta OAI-PMH.
- `scripts/ojs_harvester.py`: coleta OJS/OAI com `resumptionToken`.
- `scripts/publish.py`: une catálogo principal, backfile Crossref e OJS.
- `scripts/validate.py`: valida o índice público.
- `.github/workflows/ojs-harvest.yml`: auditoria/coleta automática.
- `.github/workflows/rebuild.yml`: republicação manual rápida.

## Para usar no repositório existente
Não apague os seus dados atuais. Copie os arquivos de código e mantenha:
- `dist/data/journals.json`
- `harvest/catalog.json.gz`
- `harvest/backfile_catalog.json`
- `harvest/source_registry.json`
- diretórios `harvest/raw/`

Depois execute:
1. `python scripts/audit_sources.py`
2. `python scripts/ojs_harvester.py --max-pages 1`
3. `python scripts/publish.py`
4. `python scripts/validate.py`

## Cloudflare Pages
Diretório de saída: `dist`
Não há etapa de build obrigatória para o frontend estático.

## Política de metadados
Fonte preferencial: OAI/OJS ou SciELO oficial; Crossref como fallback.
O inglês só é preenchido quando a fonte fornece a variante em inglês.

# Cobertura da entrega — BuscaEM v4.1

## Catálogo-base incluído no ZIP

O pacote contém **10.367 registros reais de 15 revistas**, provenientes da coleta OAI-PMH já consolidada. Esses registros são mantidos para que a atualização do código não apague o acervo existente.

## Bolema

A versão 4.1 corrige a lacuna da Bolema no código de ingestão:

- **UNESP OAI-PMH**: fonte histórica já presente no catálogo-base;
- **SciELO**: adaptador novo em `scripts/scielo.py`, configurado para `https://www.scielo.br/j/bolema/grid`;
- **Cobertura SciELO**: coleção disponível desde 2012;
- **Deduplicação**: DOI em primeiro lugar; na ausência de DOI, revista + ano + título normalizado;
- **Proveniência**: fontes mescladas são registradas no campo `provenance`;
- **Raw**: HTMLs de grade, fascículos e artigos são arquivados em `harvest/raw/bolema/scielo/`.

O ZIP não declara como já coletados os artigos SciELO que ainda não puderam ser baixados no ambiente de geração. A primeira execução conectada de `python3 scripts/harvest.py --journal bolema --full` realiza essa ingestão e atualiza `harvest/catalog.json.gz`, `dist/data/status.json` e os `records-*.json`.

## Cadastro internacional

`dist/data/journals.json` contém 63 periódicos. O campo `collectionStatus` diferencia fontes realmente integradas de periódicos apenas catalogados. Um periódico internacional não entra na contagem pública até que exista um adaptador/endpoint de ingestão executado com sucesso.

## Validação

A entrega inclui testes específicos do adaptador SciELO para extração de metadados, exclusão de front matter e fusão por DOI sem alterar o ID histórico do registro.

## v4.2 — cobertura internacional

As revistas antes marcadas apenas como `catalogued` passam a `configured` com um adaptador OpenAlex. Isso inclui os periódicos internacionais e ibero-americanos cadastrados no BuscaEM. A integração efetiva ocorre na primeira coleta bem-sucedida e os JSON brutos ficam em `harvest/raw/<id>/openalex/`.

A ordem de preferência de fontes é: fonte editorial estruturada/OAI-PMH > SciELO quando aplicável > OpenAlex como camada bibliográfica comum. A deduplicação é feita por DOI e, na ausência dele, por periódico + ano + título normalizado.

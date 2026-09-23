# BuscaEM · versão 4.1 — buscador internacional e coleta SciELO

Busca integrada em periódicos nacionais e internacionais especializados em Educação Matemática. A interface e o modelo público de metadados são multilíngues, com camada normalizada em inglês quando a própria fonte fornece essa variante. Site estático para GitHub + Cloudflare Pages, sem contas ou recursos de rede social.

## Correção da distribuição das colunas

Se os filtros apareceram na coluna larga e os cards ficaram estreitos, substitua somente `dist/styles.css` por este arquivo atualizado. O conflito entre `.btn` e `.filter-toggle` foi corrigido e as colunas receberam áreas explícitas. Os dados e as configurações do Cloudflare não precisam ser alterados.

## Atualizar apenas o visual, preservando seus dados atuais

Se você já publicou a versão 2, substitua somente estes cinco arquivos da pasta `dist`: `index.html`, `styles.css`, `app.js`, `icons.svg` e `LUCIDE-LICENSE.txt`. Os dois últimos são novos. Não precisa substituir `dist/data` nem executar a coleta para aplicar o redesign. A configuração do Cloudflare permanece igual.

## Instalação completa / atualização da versão inicial

1. Extraia o ZIP e substitua os arquivos do projeto no seu repositório pelos arquivos desta pasta.
2. **Apague o antigo `dist/data/articles.json`**, caso ainda exista no GitHub. A versão 2 usa `catalog.json` e arquivos `records-*.json`; o arquivo antigo deixa de ser necessário e pode exceder o limite de tamanho do Cloudflare.
3. Inclua também `scripts`, `harvest` e `.github/workflows/collect.yml` para manter a atualização automática.
4. Faça o commit. O Cloudflare Pages conectado ao GitHub deve iniciar uma nova publicação.

Configuração do Pages: framework **None**, comando de build **vazio**, saída **dist**. Raiz vazia se `dist` está na raiz do repositório; use `buscaem` se a pasta externa foi enviada inteira. Não precisa de D1, R2 ou senhas no código.

## Dados desta entrega

**10.367 registros reais de 15 revistas** permanecem como catálogo-base desta entrega. O código agora inclui coleta complementar da **Bolema via SciELO (2012+)**, além do OAI histórico da UNESP. A primeira execução conectada do coletor incorpora os registros SciELO e deduplica automaticamente por DOI e, quando necessário, por revista + ano + título normalizado. Consulte `COBERTURA.md`.

## Redesign desta versão

- Área de conteúdo ampliada até 1.680 px, com busca compacta e filtros laterais.
- Cards arredondados em duas colunas nas telas largas; opção de uma coluna.
- Trecho do resumo já visível, com expansão para leitura completa.
- Identidade de cor fixa para cada uma das 15 revistas, com nome/sigla nas etiquetas.
- Ícones Lucide em SVG, incluídos localmente com a licença do projeto.
- Palavras-chave em pequenas etiquetas, com acesso ao registro completo.
- Adaptação para celular com filtros recolhíveis e cards em uma coluna.

O acervo e o coletor desta entrega são os mesmos da versão 2. Os testes DOM incluem a troca entre uma e duas colunas. A prévia no navegador remoto foi bloqueada pela política de acesso a arquivos locais; por isso não se afirma validação visual concluída. `BuscaEM_previa.html`, na raiz do pacote, é uma captura HTML estática da primeira página para visualizar o layout; os controles de busca dessa prévia não são interativos. O site funcional fica em `dist`.

## Interface

- Marca tipográfica BuscaEM, fundo branco, Open Sans, títulos e resumos justificados.
- Busca em título, título original/inglês, autor, resumo original/inglês, palavras-chave original/inglês, DOI e periódico. Suporta `AND`, `OR`, `NOT`, frases entre aspas e parênteses.
- Filtros por **Journal, Year, Country, Region, Language, Document type e Open Access**.
- Ordenação por ano ou título, paginação e resumos expansíveis.
- Registro com endereço compartilhável, referência e exportação RIS, BibTeX e CSV.
- Links para leitura na revista e PDF quando fornecido pela fonte.
- Páginas Revistas, Acervo e Sobre; nenhum filtro de idioma ou palavras-chave.


## Bolema + SciELO (v4.1)

A Bolema possui duas fontes complementares configuradas em `dist/data/journals.json`:

- OAI-PMH histórico da UNESP, preservado para a cobertura anterior;
- `https://www.scielo.br/j/bolema/grid`, usado pelo novo adaptador `scripts/scielo.py` para a coleção SciELO (2012+).

O coletor percorre a grade de fascículos, abre cada fascículo, identifica as páginas de artigos e captura metatags bibliográficas/DC. As páginas brutas são preservadas em `harvest/raw/bolema/scielo/` (`grid/`, `issues/` e `articles/`). Para cada artigo, são consultadas também as interfaces `lang=en`, `lang=pt` e `lang=es` para recuperar variantes fornecidas pela própria SciELO. O código não inventa traduções: uma variante inglesa só é armazenada quando a página correspondente fornece conteúdo diferente ou quando o artigo é originalmente em inglês.

Na integração, DOI é a chave prioritária. Um artigo SciELO já existente no OAI é **mesclado no mesmo registro**, preservando o ID antigo e acrescentando proveniência, URL/PDF e metadados multilíngues. Sem DOI, usa-se revista + ano + título normalizado como chave secundária. Front matter conhecido (`Editorial`, `Nominata`, `Errata`, retratação) é excluído pelo adaptador SciELO.

Execução completa da Bolema:

```sh
python3 scripts/harvest.py --journal bolema --full
```

Somente para testar rapidamente o adaptador SciELO:

```sh
python3 scripts/harvest.py --journal bolema --full --scielo-max-issues 1 --scielo-max-articles 5
```

Para executar apenas o OAI, sem SciELO:

```sh
python3 scripts/harvest.py --journal bolema --skip-scielo
```

## Metadados multilíngues

O catálogo mantém os metadados no idioma original e campos específicos em inglês (`titleEn`, `abstractEn`, `keywordsEn`) quando a fonte os fornece. A ausência de tradução fica marcada como `pending_translation`; o pipeline não produz traduções automáticas silenciosas. Isso permite pesquisar simultaneamente a camada original e a camada inglesa sem perder a forma publicada.

## Coleta integral e atualização

Requer **Python 3.11+ e curl**. Instale o detector local de idioma com `python3 -m pip install -r requirements.txt`. O GitHub Actions em Ubuntu já fornece curl.

```sh
python3 scripts/harvest.py
```

O padrão percorre a paginação até a revista deixar de retornar `resumptionToken`, sem limite de 100 registros nem de páginas. Fontes distintas são consultadas em paralelo, com intervalo entre páginas da mesma fonte. Cada lote salva dados e cursor; interrupções permitem retomar a coleta. Registros já coletados não são apagados por erro de conexão. Exclusões explícitas da fonte são respeitadas.

```sh
# Uma fonte
python3 scripts/harvest.py --journal revemat
# Releitura desde o início de uma fonte
python3 scripts/harvest.py --journal revemat --full
# Lotes limitados somente para diagnóstico, com retomada
python3 scripts/harvest.py --journal revemat --max-pages 2
```

`--full` não apaga automaticamente registros antigos que a fonte deixou de listar sem sinalizar exclusão. Token expirado é registrado como erro e limpo para recomeçar na execução seguinte. A execução retorna erro se qualquer fonte selecionada falhar, mesmo que as outras tenham sido atualizadas.

**“Paginação OAI concluída” significa que todos os lotes retornados pelo endpoint foram percorridos. Não comprova que a editora expôs todas as edições de sua história.** Migrações entre portais, como OJS e SciELO, podem produzir diferenças. O catálogo inclui os tipos disponibilizados pela revista; Dublin Core frequentemente não distingue artigos, resenhas e editoriais. Não se faz exclusão especulativa desses registros.

O workflow executa diariamente e pode ser acionado em **Actions → Atualizar metadados → Run workflow**. Precisa de permissão `contents: write`; proteções da branch continuam valendo. Ele salva o catálogo e a retomada no GitHub, gera os lotes públicos e registra falhas. O agendamento depende da disponibilidade e das regras do GitHub Actions.

## Conferir a cobertura

A página **Acervo** mostra contagens e situação de cada revista. `dist/data/status.json` contém o diagnóstico, datas e falhas. As contagens de registros disponíveis podem diferir do número processado porque a fonte também devolve exclusões. Consulte `COBERTURA.md` para o retrato desta entrega.

## Abrir e testar localmente

```sh
python3 -m http.server 8000 --directory dist
```

Abra http://localhost:8000. No Windows use `python` no lugar de `python3`. Não abra o HTML por duplo clique.

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/validate.py
npm install
npm test
```

Node/jsdom são usados **apenas para os testes**; não são necessários para publicar o site. Os testes de DOM verificam busca, filtros, ordenação, paginação, registro, exportações e navegação. Eles não substituem inspeção visual em navegador. A prévia remota não ficou acessível neste ambiente, portanto não foi concluída validação visual em desktop/celular.

## Arquivos e procedência

- `dist/`: arquivos publicáveis; os lotes têm 500 registros para manter cada arquivo pequeno.
- `dist/data/catalog.json`: manifesto do catálogo público.
- `dist/data/records-*.json`: dados em português utilizados pela interface.
- `dist/data/journals.json`: cadastro e endpoints.
- `dist/data/status.json`: estado da coleta.
- `harvest/catalog.json.gz`: catálogo completo com variantes originais, não publicado no site.
- `harvest/state.json`: cursores e datas incrementais; não apague em atualizações normais.
- `harvest/raw/`: XMLs originais; no Actions, artefatos com retenção de 30 dias. Arquive-os separadamente para preservação permanente.
- `harvest/duplicates.json`: mesmo DOI em fontes distintas para revisão; não há fusão automática.
- `scripts/reprocess.py`: reprocessa os XMLs locais sem rede e gera os lotes públicos.
- `scripts/publish.py`: gera os lotes públicos a partir do catálogo coletado.

Os XMLs com caracteres de controle inválidos são mantidos intactos; apenas a cópia usada pelo parser substitui esses caracteres por espaços. O site escapa textos externos e restringe links a HTTP(S). Open Sans usa Google Fonts, com Arial de reserva.

A busca é nos metadados, não dentro de PDFs. PDFs não são copiados. Não inclui servidor OAI-PMH de saída, API externa ou garantia de indexação pelo Google Scholar. O navegador carrega os lotes do catálogo para pesquisar; volumes muito maiores exigem medir desempenho e avaliar um índice no servidor.

Esta entrega contém código e dados: não altera automaticamente seu repositório nem a publicação existente.


## International metadata model (v4)

BuscaEM now keeps original-language metadata and dedicated English fields (`titleEn`, `abstractEn`, `keywordsEn`). The public search indexes both layers and supports `AND`, `OR`, `NOT`, quoted phrases and parentheses. The journal registry includes integrated and catalogued sources; catalogued sources are never counted as indexed until an ingestion adapter succeeds.

## Coleta internacional (OpenAlex)

A partir da v4.2, os periódicos sem OAI-PMH/SciELO próprio configurado são coletados pelo OpenAlex. O adaptador resolve o periódico na entidade `source` e pagina os trabalhos usando `primary_location.source.id`. As respostas JSON originais são preservadas em `harvest/raw/<journal>/openalex/`.

- Primeira carga completa de uma revista: `python scripts/harvest.py --journal zdm --full`
- Diagnóstico de duas páginas: `python scripts/harvest.py --journal zdm --full --openalex-max-pages 2`
- Todas as fontes configuradas: `python scripts/harvest.py --workers 3 --openalex-max-pages 20`
- `OPENALEX_API_KEY` é opcional no código. Para coleta em escala no GitHub Actions, cadastre a chave gratuita como secret com esse nome; sem a chave, o adaptador continua tentando a cota pública.

O cadastro em `dist/data/journals.json` distingue `configured` de `integrated`: um periódico só deve ser considerado integrado depois que uma execução real produzir registros. Não crie pastas `raw` artificiais; elas surgem quando a fonte responde.

## Política de autoridade dos metadados (v4.3)

O BuscaEM **não usa OpenAlex como fonte canônica de metadados bibliográficos**. Para periódicos internacionais, o OpenAlex é utilizado somente para descoberta de DOI, identificação do periódico e métricas de citação. Antes de um registro entrar no catálogo público, o DOI é resolvido e os metadados são obtidos nesta ordem:

1. **Página oficial do artigo no periódico/editora** (metatags Highwire/Dublin Core/PRISM ou JSON-LD);
2. **Crossref**, como depósito estruturado do publisher;
3. **OpenAlex**, apenas como camada suplementar de descoberta e `citedByCount`.

Se um item descoberto no OpenAlex não tiver DOI ou não puder ser confirmado em uma fonte canônica, ele é salvo em `harvest/discovery/<journal>.json` e **não entra nos resultados públicos**.

Os arquivos auditáveis ficam separados por origem:

- `harvest/raw/<journal>/official/` — HTML da página oficial;
- `harvest/raw/<journal>/crossref/` — JSON depositado no Crossref;
- `harvest/raw/<journal>/openalex-discovery/` — respostas usadas apenas para descoberta;
- `harvest/discovery/` — fila dos itens ainda não canonizados.

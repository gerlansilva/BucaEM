# BuscaEM

Agregador de periódicos brasileiros de Educação Matemática. Código sem frameworks ou dependências de execução no navegador. GitHub + Cloudflare Pages.

## O que está pronto

- Layout responsivo em Open Sans, marca tipográfica e títulos/resumos justificados (inclusive no registro).
- Busca sem distinção de acentos em título, autoria, resumo, palavras-chave, DOI e revista.
- Filtros combinados, ordenação, paginação, catálogo de revistas, temas e contagens do acervo.
- Registro individual em janela acessível, com endereço compartilhável `#artigo/ID`.
- Referência simples, exportação RIS, BibTeX e CSV por registro.
- Coletor OAI-PMH Python, paginação com retomada, atualização incremental, tratamento de exclusões informadas pela fonte, XML original e relatório de falhas.
- Rotina semanal no GitHub Actions. Não há contas, curtidas ou rede social.

## Acervo incluído nesta entrega

O pacote abre com **300 registros reais coletados via OAI-PMH em 21/09/2026**: 100 da Zetetiké, 100 da Educação Matemática Pesquisa e 100 da REVEMAT. É UMA AMOSTRA PARCIAL, não o acervo integral nem necessariamente as publicações mais recentes das revistas. Os exemplos fictícios do mockup foram removidos. As contagens são calculadas a partir dos dados.

O cadastro possui 15 periódicos candidatos. Os três endpoints preenchidos (Zetetiké, EMP e REVEMAT) responderam a Identify, ListMetadataFormats e ListRecords nesta execução. Os outros 12 estão desativados até conferir seus endereços OAI-PMH e condições de coleta. Campos de cadastro desses periódicos precisam de validação editorial antes de lançar o catálogo como definitivo.

Se TODAS as fontes falharem, os dados anteriores permanecem intactos, o relatório é atualizado e o comando retorna erro. Consulte `dist/data/status.json` para saber se a coleta está parcial ou concluída. Os nomes de autores repetidos de forma idêntica foram deduplicados; as variantes não foram fundidas.

## Abrir no computador

Instale Python 3.11 ou superior. Dentro da pasta `buscaem`, execute:

```sh
python3 -m http.server 8000 --directory dist
```

No Windows, use `python` no lugar de `python3`. Abra http://localhost:8000 no navegador. Não abra index.html por duplo clique: o navegador pode bloquear o carregamento dos JSONs por `file://`.

Open Sans é carregada pelo Google Fonts; se a rede bloquear, Arial será usada. Para uma instalação sem requisições externas de fontes, hospede os arquivos WOFF2 licenciados e troque o link por `@font-face`.

## Subir no GitHub

1. Crie um repositório, por exemplo `buscaem`.
2. Envie TODO o conteúdo desta pasta, incluindo `.github/workflows/collect.yml` e `.gitignore`, não apenas `dist`.
3. Confirme que `dist/index.html`, `scripts/harvest.py` e `.github/workflows/collect.yml` aparecem no repositório. Arquivos iniciados por ponto podem ficar ocultos no gerenciador de arquivos.
4. Em Settings → Actions → General, permita escrita do workflow apenas se deseja que o robô atualize a branch. Branch protegida pode exigir um fluxo com pull request; este pacote não contorna essa proteção.

## Publicar no Cloudflare Pages

1. No Cloudflare, crie um projeto **Pages** conectado ao repositório GitHub.
2. Escolha a branch `main` (ou a branch que você utiliza).
3. Framework: **None / Nenhum**.
4. Comando de build: deixe vazio. Se o formulário exigir comando, use `exit 0`.
5. Diretório de saída: **dist**.
6. Diretório raiz: a raiz do repositório; se você enviou a pasta externa inteira, configure `buscaem` como raiz.
7. Publique. Não precisa de D1, R2, Node, senha administrativa ou token no código.

O projeto é destinado a **Pages**, não ao assistente de criação de Workers que exige comando de deploy. Após conectar o GitHub, novos commits atualizam a publicação conforme a configuração da integração.

## Coletar dados

```sh
python3 scripts/harvest.py --journal revemat --max-pages 2
python3 scripts/harvest.py --max-pages 20
```

Ou no GitHub: Actions → Atualizar metadados → Run workflow. O agendamento semanal começa após o workflow estar na branch padrão, sujeito às condições do GitHub Actions. O cron usa UTC. Não há credenciais de revistas armazenadas.

### Adicionar uma revista

Edite `dist/data/journals.json`. Cada objeto tem `id`, `name`, `publisher`, `scope`, `url`, `oai`, `enabled`. IDs precisam ser únicos e estáveis. Obtenha a URL OAI-PMH oficial com o portal/editor e defina `enabled: true`. Não use a página comum da revista como endpoint. Endpoints já contendo parâmetros não são recomendados.

O limite de páginas não limita o acervo definitivamente: o `resumptionToken` fica em `harvest/state.json` e a próxima execução continua. Se expirar, o coletor reporta e limpa o cursor; execute outra vez. Não remova `harvest/state.json` para uma coleta normal. `--full` recomeça a leitura sem excluir registros antigos; fontes que não informam exclusões exigem reconciliação editorial separada.

Se houver erro, leia `dist/data/status.json`. Nunca desative a validação TLS ou tente contornar bloqueios dos portais. O endpoint pode estar errado, indisponível ou exigir contato com o editor.

### Procedência, duplicidades e limites

- XMLs ficam em `harvest/raw/` no computador. No Actions, são artefatos com retenção de 30 dias, NÃO preservação permanente. Baixe/arquive-os para auditoria de longo prazo. Eles não são publicados no site.
- IDs estáveis por revista + identificador OAI evitam duplicar o mesmo registro em coletas repetidas.
- Mesmo DOI em fontes distintas não é fundido automaticamente: verifique `harvest/duplicates.json`.
- Resumos multilíngues são preservados em `abstracts`; português é preferido na exibição quando `xml:lang` está presente.
- O coletor não inventa ORCID, instituições, métodos, tipos, resumos, acesso aberto ou DOI. OAI Dublin Core pode não oferecer vários desses campos.
- Tipos documentais vêm da fonte. Um valor genérico `Text` não permite separar artigos e editoriais com segurança. A curadoria dessa distinção ainda é necessária.
- PDFs só são apontados se a fonte fornecer um link identificável. Não são baixados ou hospedados.
- Dados externos são escapados antes de renderizar. URLs são restritas a HTTP(S).
- Esta versão carrega o catálogo JSON no navegador. É adequada ao piloto, não uma promessa de desempenho para centenas de milhares de registros. A migração para D1/índice de busca deve ocorrer com medição do volume real.
- Não inclui busca dentro dos PDFs, leitor incorporado, servidor OAI-PMH de saída, API de produção, páginas HTML individuais indexáveis ou garantia de indexação no Google Scholar. Registros são rotas de fragmento no navegador. Essas capacidades exigem uma segunda etapa de implementação.
- Esta entrega não cria repositório, recursos Cloudflare, assinaturas ou publicação em seu nome.

## Testes

```sh
python3 -m unittest discover -s scripts -p 'test_*.py'
node --input-type=module --check < dist/app.js
```

## Estrutura

```text
dist/                    site publicável
  index.html
  styles.css
  app.js
  favicon.svg
  _headers
  data/
    articles.json        catálogo / demonstração identificada
    journals.json        cadastro das fontes
    status.json          diagnóstico da coleta
scripts/
  harvest.py             coletor OAI-PMH
  test_harvest.py         testes do parser
harvest/
  state.json             retomada e datas incrementais
  duplicates.json        possíveis duplicidades entre fontes
.github/workflows/
  collect.yml            atualização semanal
```

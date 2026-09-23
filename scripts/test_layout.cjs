const {JSDOM}=require('jsdom');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const css=fs.readFileSync(path.resolve(__dirname,'../dist/styles.css'),'utf8');
const dom=new JSDOM('<style>'+css+'</style><div class="workspace"><button class="btn filter-toggle">Filtros</button><aside class="filters"></aside><section class="results"></section></div>');
const w=dom.window;
assert.equal(w.getComputedStyle(w.document.querySelector('.filter-toggle')).display,'none','Mobile button must not occupy the desktop grid');
assert.equal(w.getComputedStyle(w.document.querySelector('.filters')).gridArea,'filters');
assert.equal(w.getComputedStyle(w.document.querySelector('.results')).gridArea,'results');
dom.window.close();console.log('OK: cascata CSS e posicionamento explícito das colunas.');

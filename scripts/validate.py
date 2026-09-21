"""Sanity checks for the distributable, no third-party packages."""
import json
from html.parser import HTMLParser
from pathlib import Path

root = Path(__file__).resolve().parents[1]
public = root / 'dist'
class Links(HTMLParser):
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'link'):
            value = attrs.get('src') or attrs.get('href', '')
            if value and not value.startswith(('http:', 'https:', 'data:', '#')):
                assert (public / value).exists(), value
Links().feed((public / 'index.html').read_text())
data = json.loads((public / 'data/articles.json').read_text())
journals = json.loads((public / 'data/journals.json').read_text())
ids = [j['id'] for j in journals]
assert len(ids) == len(set(ids)), 'Duplicate journal IDs'
article_ids = []
for a in data['articles']:
    assert a['journal'] in ids
    assert a['title'] and isinstance(a['authors'], list)
    assert isinstance(a['keywords'], list)
    article_ids.append(a['id'])
assert len(article_ids) == len(set(article_ids)), 'Duplicate article IDs'
styles = (public / 'styles.css').read_text()
assert 'text-align:justify' in styles and "'Open Sans'" in styles
assert (root / '.github/workflows/collect.yml').exists()
print(f"OK: local assets, {len(journals)} journal IDs, {len(article_ids)} article IDs, typography, workflow.")

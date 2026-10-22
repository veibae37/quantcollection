"""Verify shared-page integration without touching market calculations."""
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter
import json
import re

class Document(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.assets = []
        self.links = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'a':
            self.links.append(attrs)
        if tag in ('script', 'link'):
            url = attrs.get('src', attrs.get('href', ''))
            if url.startswith('/'):
                self.assets.append(url)

root = Path(__file__).parent / 'public'
for name in ('index', 'en', 'backtest', 'market-sentiment', 'hk-factor-lab'):
    content = (root / f'{name}.html').read_text(encoding='utf-8')
    doc = Document()
    doc.feed(content)
    assert not [key for key, count in Counter(doc.ids).items() if count > 1], name
    assert all((root / url.lstrip('/')).exists() for url in doc.assets), name
    assert '/editorial.css' in content, name
    if name != 'chart-example':
        assert content.count('class="editorial-header"') == 1, name
        assert 'editorial-sidebar' in content, name
    script_name = 'app' if name in ('index', 'en') else name
    script = (root / f'{script_name}.js').read_text(encoding='utf-8')
    # IDs in literal selectors must remain present after the header/layout change.
    missing = set(re.findall(r'\$\("#([\w-]+)"\)', script)) - set(doc.ids)
    assert not missing, (name, missing)
    if name in ('index', 'en'):
        destination = '/en' if name == 'index' else '/'
        assert any(link.get('href') == destination and 'language-toggle' in link.get('class', '').split() for link in doc.links), name
    print(f'{name}: IDs, assets, theme and script hooks OK')

configuration = json.loads((root.parent / 'vercel.json').read_text(encoding='utf-8'))
routes = {route['source']: route['destination'] for route in configuration['rewrites']}
for route, page in (('/', 'index'), ('/en', 'en'), ('/backtest', 'backtest'), ('/market-sentiment', 'market-sentiment'), ('/hk-factor-lab', 'hk-factor-lab')):
    assert routes.get(route) == f'/{page}.html', route
print('Production routes and language links OK')

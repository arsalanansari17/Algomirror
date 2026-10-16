import sys
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
env = Environment(loader=ChoiceLoader([
    DictLoader({'layout.html': '<!doctype html><html data-theme="light"><body>{% block content %}{% endblock %}</body></html>'}),
    FileSystemLoader('app/templates'),
]), autoescape=True)
env.globals['asset_version'] = lambda f: 'x'
env.globals['url_for'] = lambda endpoint, **k: '/static/' + k.get('filename', endpoint) if endpoint == 'static' else '/' + endpoint
class A:
    def __init__(self, i, n): self.id = i; self.account_name = n
html = env.get_template('trading/pnl_analysis.html').render(accounts=[A(1, 'Arsalan'), A(2, 'Iram')], selected_account_ids=[])
open(sys.argv[1], 'w', encoding='utf-8').write(html)
print('rendered', len(html))

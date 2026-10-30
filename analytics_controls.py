"""An explicit vocabulary shared with the browser; never accept DOM text."""
import json
import re
from pathlib import Path

CONTROLS = json.loads(Path(__file__).with_name('analytics_controls.json').read_text())


def public_path(value):
    """Keep public routes only, without query strings or fragments."""
    if not isinstance(value, str) or len(value) > 2000:
        return None
    path = re.split(r'[?#]', value, maxsplit=1)[0]
    path = re.sub(r'^/(ru|uz|en)(?=/)', '', path)
    if path in ('/', '/market', '/catalog', '/news', '/heatmap', '/login'):
        return path
    if re.fullmatch(r'/(company|chart|bond)/[A-Za-z0-9._-]{1,32}', path):
        return path
    # Article URLs may contain titles; report the section, not arbitrary text.
    if path.startswith('/news/') and len(path) <= 200:
        return '/news/article'
    return None

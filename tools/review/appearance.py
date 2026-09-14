"""Apply the consumer's reviewer title and stylesheets from workspace.json."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
import re

ROUTE = '/bunko-theme/'


def load(config=None):
    """Return the configured title and stylesheet paths, resolved inside the workspace."""
    path = Path(config or os.environ.get('BUNKO_CONFIG', 'workspace.json')).resolve()
    try:
        review = json.loads(path.read_text()).get('review', {})
    except OSError:
        return None, []
    root = path.parent
    sheets = []
    for item in review.get('stylesheets', []):
        sheet = (root / item).resolve()
        if sheet.is_relative_to(root) and sheet.suffix == '.css':
            sheets.append(sheet)
    return review.get('title'), sheets


def render(document, title, count):
    """Link consumer stylesheets after the built ones, so their tokens win."""
    if title:
        document = re.sub(r'<title>.*?</title>', f'<title>{html.escape(title)}</title>', document, count=1)
    links = ''.join(f'<link rel="stylesheet" href="{ROUTE}{index}.css" />' for index in range(count))
    return document.replace('</head>', links + '</head>', 1)

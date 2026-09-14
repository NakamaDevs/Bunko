"""Build a Zensical view of configured roots without editing maintained sources.

Two modes exist. By default each documentation root is copied into a generated
site with its own navigation. When ``site.config`` names the consumer's MkDocs
configuration, that configuration is rendered in place instead: its navigation,
theme, plugins, hooks, and extensions apply unchanged, and Bunko contributes its
palette, notes, and code viewer through a generated theme overlay.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import quote

import yaml

from palette_index import _read, _page_url

ROOT = Path(os.environ.get('BUNKO_ROOT', Path.cwd())).resolve()
CONFIG = Path(os.environ.get('BUNKO_CONFIG', ROOT / 'workspace.json')).resolve()
BUILD = Path(os.environ.get('BUNKO_STATE', ROOT / '_build/bunko')) / 'docs'
SOURCE = BUILD / 'source'
ASSETS = Path(__file__).parent / 'assets'
OVERRIDES = Path(__file__).parent / 'overrides'
STYLESHEETS = ['palette', 'annotations', 'codeview', 'diagram-viewer', 'course-navigation']
SCRIPTS = ['palette', 'annotations', 'codeview']
# Zensical requires docs_dir inside the configuration's directory, so the
# rendered configuration is written beside the consumer's and must be ignored.
SITE_CONFIGS = {True: '.bunko-site.yml', False: '.bunko-site.build.yml'}


class Tagged:
    """A YAML node with an application tag, such as ``!!python/name`` or ``!ENV``."""

    def __init__(self, tag, value):
        self.tag, self.value = tag, value


class Loader(yaml.SafeLoader):
    pass


class Dumper(yaml.SafeDumper):
    pass


def _construct_tagged(loader, tag, node):
    if isinstance(node, yaml.ScalarNode):
        return Tagged(tag, loader.construct_scalar(node))
    if isinstance(node, yaml.SequenceNode):
        return Tagged(tag, loader.construct_sequence(node, deep=True))
    return Tagged(tag, loader.construct_mapping(node, deep=True))


def _represent_tagged(dumper, data):
    if isinstance(data.value, list):
        return dumper.represent_sequence(data.tag, data.value)
    if isinstance(data.value, dict):
        return dumper.represent_mapping(data.tag, data.value)
    return dumper.represent_scalar(data.tag, data.value)


Loader.add_multi_constructor('', _construct_tagged)
Dumper.add_representer(Tagged, _represent_tagged)


def ignored(directory, names):
    """Keep metadata, runtime output, and symlinks out of the published view."""
    result = []
    for name in names:
        path = Path(directory) / name
        if (name.startswith('.') or name in {'_build', 'node_modules', '__pycache__'}
                or path.is_symlink() or path.resolve() == BUILD.parent.resolve()):
            result.append(name)
    return result


def source_files(folder):
    for directory, dirs, files in os.walk(folder, followlinks=False):
        excluded = set(ignored(directory, dirs + files))
        dirs[:] = sorted(name for name in dirs if name not in excluded)
        for name in sorted(files):
            if name not in excluded:
                yield Path(directory) / name


def write_if_changed(path, text):
    """Rewrite generated files only on change, so watchers do not rebuild in a loop."""
    if not path.exists() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def nav_sections(nav, trail=()):
    """Map each page path in a MkDocs navigation to its section trail."""
    sections = {}
    if isinstance(nav, list):
        for entry in nav:
            sections.update(nav_sections(entry, trail))
    elif isinstance(nav, dict):
        for title, value in nav.items():
            if isinstance(value, str):
                sections[value] = ' › '.join(trail)
            else:
                sections.update(nav_sections(value, (*trail, str(title))))
    return sections


class Sources:
    """Map rendered pages back to their repository file and optional hosted URL."""

    def __init__(self, config):
        self.config, self.revisions = config, {}

    def entry(self, repository, repo, path):
        source = {'repository': repository, 'path': path.relative_to(repo).as_posix()}
        repository_url = self.config.get('repository_urls', {}).get(repository)
        if repository_url:
            if repo not in self.revisions:
                self.revisions[repo] = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
            source['url'] = repository_url.rstrip('/') + '/blob/' + self.revisions[repo] + '/' + quote(source['path'])
        return source


def palette_extras(config, site_settings=None):
    """Application links and the Linear workspace offered by the palette."""
    palette = config.get('palette', {})
    applications = [list(entry) for entry in palette.get('applications', [])]
    if palette.get('applications_file'):
        path = CONFIG.parent / palette['applications_file']
        try:
            listed = json.loads(path.read_text())
        except (OSError, ValueError):
            listed = []
        if isinstance(listed, dict):
            listed = listed.get('applications', [])
        applications.extend([str(entry[0]), str(entry[1])] for entry in listed
                            if isinstance(entry, list) and len(entry) == 2)
    extra = (site_settings or {}).get('extra') or {}
    linear = palette.get('linear_workspace') or ((extra.get('palette') or {}).get('linear_workspace') or '')
    return {'repositories': list(config.get('repository_urls', {}).items()), 'applications': applications, 'linear': linear}


def prepare(dev=False):
    config = json.loads(CONFIG.read_text())
    if config.get('site'):
        return prepare_site(config, dev)
    ids = [item['id'] for item in config['documentation']]
    reserved = {'assets', 'stylesheets', 'javascripts'}
    if len(set(ids)) != len(ids) or set(ids) & reserved:
        raise ValueError('Documentation IDs must be unique and must not use asset directory names')
    SOURCE.mkdir(parents=True, exist_ok=True)
    for child in SOURCE.iterdir():
        if child.is_dir() and child.name not in set(ids) | reserved:
            shutil.rmtree(child)
    shutil.copytree(ASSETS, SOURCE, dirs_exist_ok=True)
    entries, sources, nav, landing_links = [], {}, [], []
    resolver = Sources(config)
    for item in config['documentation']:
        ident = item['id']
        if not ident.isidentifier():
            raise ValueError('Documentation IDs must be identifiers')
        repo = (CONFIG.parent / config['repositories'][item['repository']]).resolve()
        folder = (repo / item['path']).resolve()
        folder.relative_to(repo)
        target = SOURCE / ident
        shutil.copytree(folder, target, dirs_exist_ok=True, ignore=ignored)
        live = {p.relative_to(folder) for p in source_files(folder)}
        for p in target.rglob('*'):
            if p.is_file() and p.relative_to(target) not in live:
                p.unlink()
        pages = []
        for path in sorted(p for p in source_files(folder) if p.suffix == '.md'):
            relative = path.relative_to(folder)
            mounted = Path(ident) / relative
            title, headings = _read(path)
            title = title or path.stem
            url = _page_url(mounted)
            entries.append([0, title, url, item['label'], mounted.as_posix()])
            sources[mounted.as_posix()] = resolver.entry(item['repository'], repo, path)
            entries.extend([1, text, url + '#' + slug, title] for text, slug in headings)
            pages.append({title: mounted.as_posix()})
        pages.sort(key=lambda p: 0 if Path(next(iter(p.values()))).name in {'README.md', 'index.md'} else 1)
        if pages:
            landing_links.append(f"- [{item['label']}]({next(iter(pages[0].values()))})")
        nav.append({item['label']: pages})
    (SOURCE / 'index.md').write_text('# ' + config['name'] + '\n\n' + '\n'.join(landing_links) + '\n')
    (SOURCE / 'assets').mkdir(exist_ok=True)
    (SOURCE / 'assets/palette-index.json').write_text(json.dumps({'entries':entries,'sources':sources,'origin':'',**palette_extras(config)},ensure_ascii=False))
    theme = {'name':'material','variant':'classic','custom_dir':str(OVERRIDES),'font':False,'palette':[{'scheme':'default','toggle':{'icon':'material/weather-night','name':'Dark mode'}},{'scheme':'slate','toggle':{'icon':'material/weather-sunny','name':'Light mode'}}],'features':['navigation.tabs','navigation.sections','navigation.top','search.highlight','search.suggest']}
    settings = {'site_name':config['name'],'docs_dir':'source','site_dir':'site','use_directory_urls':True,'nav':[{'Home':'index.md'},*nav],'theme':theme,'markdown_extensions':['admonition','attr_list','md_in_html','tables',{'toc':{'permalink':True}},'pymdownx.details',{'pymdownx.highlight':{'pygments_lang_class':True,'anchor_linenums':True,'line_spans':'__span'}},'pymdownx.superfences'],'extra_css':[f'stylesheets/{name}.css' for name in ['sdlc',*STYLESHEETS]],'extra_javascript':[f'javascripts/{name}.js' for name in SCRIPTS]}
    if dev:
        # The dev server loads the Tidewave toolbar. Static builds stay free of it.
        if os.environ.get('BUNKO_DEV_TOOLS') == '1':
            settings['extra'] = {'tidewave_root': str(ROOT)}
        settings['site_dir'] = 'site-dev'
    text = yaml.safe_dump(settings,sort_keys=False,allow_unicode=True)
    text = text.replace('- pymdownx.superfences\n', '- pymdownx.superfences:\n    custom_fences:\n    - name: mermaid\n      class: mermaid\n      format: !!python/name:pymdownx.superfences.fence_code_format\n')
    # Separate files let a static build run beside the dev server.
    (BUILD / ('mkdocs.yml' if dev else 'mkdocs.build.yml')).write_text(text)
    return BUILD / ('mkdocs.yml' if dev else 'mkdocs.build.yml')


def site_paths(config):
    """The consumer configuration, its settings, and the one documentation root."""
    site = (CONFIG.parent / config['site']['config']).resolve()
    settings = yaml.load(site.read_text(encoding='utf-8'), Loader=Loader) or {}
    item = config['documentation'][0]
    repo = (CONFIG.parent / config['repositories'][item['repository']]).resolve()
    folder = (repo / item['path']).resolve()
    if (site.parent / settings.get('docs_dir', 'docs')).resolve() != folder:
        raise ValueError('The site configuration docs_dir must be the configured documentation root')
    return site, settings, item, repo, folder


def unique(values):
    return list(dict.fromkeys(values))


def prepare_site(config, dev=False):
    site, settings, item, repo, folder = site_paths(config)
    rendered = site.parent / SITE_CONFIGS[dev]
    check = subprocess.run(['git', '-C', str(site.parent), 'check-ignore', '-q', rendered.name])
    if check.returncode == 1:
        raise ValueError(f'Add {rendered.name} and {SITE_CONFIGS[not dev]} to .gitignore beside {site.name}')
    provided = [path.relative_to(ASSETS) for path in ASSETS.rglob('*') if path.is_file()]
    shadowed = sorted(str(path) for path in provided if (folder / path).exists())
    if shadowed:
        raise ValueError('Documentation files replace Bunko assets; remove them: ' + ', '.join(shadowed))

    # The overlay holds Bunko's templates and assets, then the consumer's own
    # custom_dir on top, so a consumer override wins.
    theme_dir = BUILD / 'theme'
    shutil.copytree(OVERRIDES, theme_dir, dirs_exist_ok=True)
    shutil.copytree(ASSETS, theme_dir, dirs_exist_ok=True)
    theme = dict(settings.get('theme') or {'name': 'material'})
    if theme.get('custom_dir'):
        shutil.copytree(site.parent / theme['custom_dir'], theme_dir, dirs_exist_ok=True)
    theme['custom_dir'] = str(theme_dir)

    sections = nav_sections(settings.get('nav'))
    resolver, entries, sources = Sources(config), [], {}
    for path in (p for p in source_files(folder) if p.suffix == '.md'):
        relative = path.relative_to(folder).as_posix()
        title, headings = _read(path)
        title = title or path.stem
        url = _page_url(Path(relative))
        entries.append([0, title, url, sections.get(relative, ''), relative])
        sources[relative] = resolver.entry(item['repository'], repo, path)
        entries.extend([1, text, url + '#' + slug, title] for text, slug in headings)
    index = {'entries': entries, 'sources': sources, 'origin': '', **palette_extras(config, settings)}
    write_if_changed(theme_dir / 'assets/palette-index.json', json.dumps(index, ensure_ascii=False))

    settings['theme'] = theme
    settings['site_dir'] = str(BUILD / ('site-dev' if dev else 'site'))
    settings['extra_css'] = unique([f'stylesheets/{name}.css' for name in STYLESHEETS] + list(settings.get('extra_css') or []))
    settings['extra_javascript'] = unique([f'javascripts/{name}.js' for name in SCRIPTS] + list(settings.get('extra_javascript') or []))
    extra = dict(settings.get('extra') or {})
    extra.pop('tidewave_root', None)
    if dev and os.environ.get('BUNKO_DEV_TOOLS') == '1':
        extra['tidewave_root'] = str(ROOT)
    if extra:
        settings['extra'] = extra
    header = f'# Generated by Bunko from {site.name}; do not edit.\n'
    write_if_changed(rendered, header + yaml.dump(settings, Dumper=Dumper, sort_keys=False, allow_unicode=True))
    return rendered


def signature():
    config = json.loads(CONFIG.read_text())
    paths = [CONFIG, *ASSETS.rglob('*')]
    if config.get('site'):
        site, settings, _, _, folder = site_paths(config)
        paths.extend([site, *(p for p in source_files(folder) if p.suffix == '.md')])
        if (settings.get('theme') or {}).get('custom_dir'):
            paths.extend((site.parent / settings['theme']['custom_dir']).rglob('*'))
        if config.get('palette', {}).get('applications_file'):
            paths.append(CONFIG.parent / config['palette']['applications_file'])
    else:
        for item in config['documentation']:
            paths.extend(source_files(CONFIG.parent / config['repositories'][item['repository']] / item['path']))
    return [(str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths if p.is_file()]


def watch():
    previous = signature()
    while True:
        time.sleep(1)
        current = signature()
        if current != previous:
            prepare(dev=True)
            previous = current


if __name__ == '__main__':
    executable = str(Path(sys.executable).parent / 'zensical')
    if '--build' in sys.argv:
        rendered = prepare()
        raise SystemExit(subprocess.call([executable, 'build', '-f', str(rendered)]))
    rendered = prepare(dev=True)
    threading.Thread(target=watch, daemon=True).start()
    raise SystemExit(subprocess.call([executable, 'serve', '-f', str(rendered), '--dev-addr', f"127.0.0.1:{os.environ['PORT']}"]))

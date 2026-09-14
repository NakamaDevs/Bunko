"""Serve the built reviewer without a JavaScript development server."""
import os
from pathlib import Path
from aiohttp import web

import appearance

ROOT = Path(__file__).resolve().parent / 'web/dist'


async def serve(request):
    relative = request.match_info.get('path', '') or 'index.html'
    title, sheets = appearance.load()
    if request.path.startswith(appearance.ROUTE):
        name = request.path.removeprefix(appearance.ROUTE).removesuffix('.css')
        if not name.isdigit() or int(name) >= len(sheets) or not sheets[int(name)].is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(sheets[int(name)], headers={'Content-Type': 'text/css', 'Cache-Control': 'no-cache'})
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise web.HTTPNotFound()
    if relative == 'index.html':
        document = appearance.render(path.read_text(), title, len(sheets))
        return web.Response(text=document, content_type='text/html', headers={'Cache-Control': 'no-cache'})
    return web.FileResponse(path)


app = web.Application()
app.router.add_get('/{path:.*}', serve)
if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=int(os.environ['PORT']))

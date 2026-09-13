"""Serve the built reviewer without a JavaScript development server."""
import os
from pathlib import Path
from aiohttp import web

ROOT = Path(__file__).resolve().parent / 'web/dist'


async def serve(request):
    relative = request.match_info.get('path', '') or 'index.html'
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)


app = web.Application()
app.router.add_get('/{path:.*}', serve)
if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=int(os.environ['PORT']))

"""Loopback gateway for the docs and review localhost subdomains."""
import asyncio
import os
from aiohttp import ClientSession, WSMsgType, web

HOP = {'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade','content-length','content-encoding'}
DOMAIN = os.environ.get('BUNKO_DOMAIN', 'sdlc.localhost')
SESSION = web.AppKey('session', ClientSession)

async def proxy(request):
    hostname = request.host.split(':')[0]
    if hostname not in {f'docs.{DOMAIN}', f'review.{DOMAIN}', '127.0.0.1', 'localhost'}:
        raise web.HTTPForbidden(text='Unknown workspace host')
    if request.path == '/health':
        return web.json_response({'status':'ok'})
    if request.path == '/notes' or request.path.startswith('/notes/'):
        upstream = os.environ['NOTES_URL']
    elif request.path.startswith('/api/'):
        upstream = os.environ['REVIEW_API_URL']
    elif request.path == '/tidewave' or request.path.startswith('/tidewave/'):
        upstream = os.environ['REVIEW_WEB_URL']
    else:
        upstream = os.environ['REVIEW_WEB_URL'] if hostname.startswith('review.') else os.environ['DOCS_URL']
    origin = request.headers.get('Origin')
    if origin and origin != f'{request.scheme}://{request.host}':
        raise web.HTTPForbidden(text='Unexpected request origin')
    target = upstream.rstrip('/') + request.rel_url.path_qs
    headers = {k:v for k,v in request.headers.items() if k.lower() not in HOP | {'host','origin'}}
    session = request.app[SESSION]
    if request.headers.get('Upgrade','').lower() == 'websocket':
        protocols = request.headers.get('Sec-WebSocket-Protocol', '').split(',')
        protocols = [p.strip() for p in protocols if p.strip()]
        async with session.ws_connect(target,protocols=protocols) as remote:
            local = web.WebSocketResponse(protocols=protocols)
            await local.prepare(request)
            async def forward(source,dest):
                async for msg in source:
                    if msg.type == WSMsgType.TEXT: await dest.send_str(msg.data)
                    elif msg.type == WSMsgType.BINARY: await dest.send_bytes(msg.data)
                await dest.close()
            await asyncio.gather(forward(local,remote),forward(remote,local))
            return local
    async with session.request(request.method,target,headers=headers,data=await request.read(),allow_redirects=False) as response:
        return web.Response(status=response.status,body=await response.read(),headers={k:v for k,v in response.headers.items() if k.lower() not in HOP})

async def lifecycle(app):
    async with ClientSession() as session:
        app[SESSION] = session
        yield

app = web.Application(client_max_size=8*1024*1024)
app.cleanup_ctx.append(lifecycle)
app.router.add_route('*','/{path:.*}',proxy)
if __name__ == '__main__':
    web.run_app(app,host='127.0.0.1',port=int(os.environ['PORT']))

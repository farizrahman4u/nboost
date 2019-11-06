
from aiohttp import web, web_exceptions, client
from . import BaseServer
import aiohttp
from ..base import pformat
from ..base.types import *
from typing import Callable
import asyncio
from urllib.parse import urlencode


class AioHttpServer(BaseServer):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.error_handler = None
        self.not_found_handler = None

    def create_app(self, routes):
        self.app = web.Application(middlewares=[self.middleware])
        self.app.add_routes([
            web.route(*routes[Route.SEARCH]),
            web.route(*routes[Route.TRAIN]),
            web.route(*routes[Route.STATUS])
        ])

        self.error_handler = routes[Route.ERROR][2]
        self.not_found_handler = routes[Route.NOT_FOUND][2]

    async def run_app(self):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

    def run(self):
        try:
            self.loop = asyncio.get_event_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

        self.loop.run_until_complete(self.run_app())
        self.logger.critical('LISTENING: %s:%d' % (self.host, self.port))
        self.logger.info('\nROUTES:\n%s' % pformat(self.handler.routes, width=1))
        self.is_ready.set()
        self.loop.run_forever()
        self.is_ready.clear()

    @staticmethod
    async def format_response(response: client.ClientResponse) -> Response:
        return Response(dict(response.headers), await response.read(), response.status)

    @staticmethod
    async def format_request(request: web.BaseRequest) -> Request:
        return Request(
                request.method,
                request.path,
                dict(request.headers),
                dict(request.query),
                await request.read()
        )

    @web.middleware
    async def middleware(self, request: web.BaseRequest, handler: Callable) -> web.Response:
        try:
            req = await self.format_request(request)
            res = await handler(req)
        except web_exceptions.HTTPNotFound:
            self.logger.info('NOT FOUND: %s' % request)
            url = 'http://%s:%s%s?%s' % (self.ext_host, self.ext_port, request.path, request.query_string)
            raise web.HTTPTemporaryRedirect(url)
        except Exception as e:
            self.logger.error(repr(e), exc_info=True)
            res = await self.error_handler(e)

        self.logger.info(res.status)
        self.logger.debug(res)
        return web.Response(body=res.body, status=res.status)

    async def ask(self, req):
        url = 'http://%s:%s%s?%s' % (self.ext_host, self.ext_port, req.path, urlencode(req.params))

        async with aiohttp.request(req.method, url, data=req.body) as response:
            return await self.format_response(response)

    async def forward(self, req):
        url = 'http://%s:%s%s?%s' % (self.ext_host, self.ext_port, req.path, req.params)

        raise web.HTTPTemporaryRedirect(url)

    def close(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.join()
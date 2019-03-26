#!/usr/bin/env python
import os
import sys
import asyncio
import importlib
import traceback

import aiohttp
from aiohttp import web
import cachetools
from gidgethub import aiohttp as gh_aiohttp
from gidgethub import routing
from gidgethub import sansio


router = routing.Router()
cache = cachetools.LRUCache(maxsize=500)


@router.register('push', ref='refs/heads/dev')
def pushed_to_dev(event, gh, *arg, **kwargs):
    print(event)


@router.register("pull_request", action="opened")
async def opened_pr(event, gh, *arg, **kwargs):
    """Mark new PRs as needing a review."""
    pull_request = event.data["pull_request"]
    await gh.post(pull_request["labels_url"], data=["needs review"])


async def handle_request(request):
    try:
        body = await request.read()
        secret = os.environ.get("GH_SECRET")
        event = sansio.Event.from_http(request.headers, body, secret=secret)
        print('GH delivery ID', event.delivery_id, file=sys.stderr)
        if event.event == "ping":
            return web.Response(status=200)
        oauth_token = os.environ.get("GH_AUTH")
        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, "rchain/rchain", oauth_token=oauth_token, cache=cache)
            # Give GitHub some time to reach internal consistency.
            await asyncio.sleep(1)
            await router.dispatch(event, gh)
        try:
            print('GH requests remaining:', gh.rate_limit.remaining)
        except AttributeError:
            pass
        return web.Response(status=200)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        return web.Response(status=500)


if __name__ == "__main__":
    app = web.Application()
    app.router.add_post("/", handle_request)
    web.run_app(app, port=9090)

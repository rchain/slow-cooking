#!/usr/bin/env python
import os
import sys
import asyncio
import importlib
import traceback
import subprocess

from loguru import logger
import aiohttp
from aiohttp import web
import cachetools
from gidgethub import aiohttp as gh_aiohttp
from gidgethub import routing
from gidgethub import sansio


def get_last_build_number():
    drone_cmd = os.environ['DRONE_CMD']
    command = [drone_cmd, 'build', 'ls', '--format={{.Number}}', '--limit=1', 'rchain/slow-cooking']
    output = subprocess.check_output(command)
    return int(output.decode().strip())


def start_drone_build(logger_context, proto_build_number):
    drone_cmd = os.environ['DRONE_CMD']
    command = [drone_cmd, 'build', 'restart', 'rchain/slow-cooking', str(proto_build_number)]
    output = subprocess.check_output(command)
    logger_context.info(output.decode().strip())


async def pushed_to_dev(logger_context, event):
    last_build_number = get_last_build_number()
    start_drone_build(logger_context, last_build_number)


async def handle_request(request, secret, oauth_token):
    body = await request.read()

    event = sansio.Event.from_http(request.headers, body, secret=secret)

    logger_context = logger.bind(delivery_id=event.delivery_id, event=event.event, ref=event.data['ref'])
    logger_context.info('Got event')
    if event.event == 'ping':
        return web.Response(status=200)

    async with aiohttp.ClientSession() as session:
        if event.event == 'push' and event.data['ref'] == 'refs/heads/dev':
            await pushed_to_dev(logger_context, event)

    return web.Response(status=200)


async def try_handle_request(request):
    github_webhook_secret = os.environ['GITHUB_WEBHOOK_SECRET']
    github_personal_token = os.environ['GITHUB_PERSONAL_TOKEN']

    try:
        await handle_request(request, github_webhook_secret, github_personal_token)
    except Exception as exc:
        logger.exception('Exception while handling request')
        return web.Response(status=500)

    return web.Response(status=200)


async def handle_health(request):
    return web.Response(status=200)


if __name__ == "__main__":
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_post("/", try_handle_request)
    web.run_app(app, port=9090)

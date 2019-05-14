#!/usr/bin/env python
import re
import os
import sys
import asyncio
import importlib
import traceback
import subprocess

from typing import (
    Any,
    List,
)

import loguru
from loguru import logger
import aiohttp
from aiohttp import web
import cachetools
import gidgethub
from gidgethub import aiohttp as gh_aiohttp
from gidgethub import routing
from gidgethub import sansio


def drone_command(drone_server: str, drone_token: str, args: List[str]) -> str:
    drone_cmd = os.environ['DRONE_CMD']
    env = {
        'DRONE_SERVER': drone_server,
        'DRONE_TOKEN':  drone_token,
    }
    command = [drone_cmd] + args
    output = subprocess.check_output(command, env=env)
    return output.decode()


def get_last_drone_build_number(drone_server: str, drone_token: str, repo: str) -> int:
    output = drone_command(
        drone_server,
        drone_token,
        ['build', 'ls', '--format={{.Number}}', '--limit=1', repo],
    )
    return int(output.strip())


def restart_drone_build(drone_server: str, drone_token: str, repo: str, build_number: int) -> str:
    output = drone_command(
        drone_server,
        drone_token,
        ['build', 'restart', repo, str(build_number)],
    )
    return output.strip()


def restart_last_drone_build(drone_server: str, drone_token: str, repo: str) -> str:
    last_build_number = get_last_drone_build_number(drone_server, drone_token, repo)
    return restart_drone_build(drone_server, drone_token, repo, last_build_number)


async def pushed_to_dev(logger_context: loguru.Logger, event: sansio.Event) -> None:
    slow_cooker_output = restart_last_drone_build(
        os.environ['SLOW_COOKING_DRONE_SERVER'],
        os.environ['SLOW_COOKING_DRONE_TOKEN'],
        'rchain/slow-cooking',
    )
    logger_context.info(slow_cooker_output)

    perf_harness_output = restart_last_drone_build(
        os.environ['PERF_HARNESS_DRONE_SERVER'],
        os.environ['PERF_HARNESS_DRONE_TOKEN'],
        'rchain/perf-harness',
    )
    logger_context.info(perf_harness_output)


def start_drone_build(contract_file_basename: str, commit_sha: str, repo_url: str) -> str:
    drone_server = os.environ['PERF_HARNESS_DRONE_SERVER']
    drone_token = os.environ['PERF_HARNESS_DRONE_TOKEN']

    last_build_number = get_last_drone_build_number(drone_server, drone_token, 'rchain/perf-harness')

    output = drone_command(
        drone_server,
        drone_token,
        [
            'build',
            'promote',
            '--format={{.Number}}',
            '--param=CONTRACT=/workdir/rchain-perf-harness/{}'.format(contract_file_basename),
            '--param=RCHAIN_COMMIT_HASH={}'.format(commit_sha),
            '--param=RCHAIN_REPO={}'.format(repo_url),
            'rchain/perf-harness',
            str(last_build_number),
            'custom_commit',
        ],
    )
    return output.strip()


async def is_collaborator(github: gh_aiohttp.GitHubAPI, owner: str, repo: str, user: str) -> bool:
    # This is a bit of an obscure way that implements checking whether user is
    # a collaborator of a given repository:
    # https://developer.github.com/v3/repos/collaborators/#check-if-a-user-is-a-collaborator

    try:
        await github.getitem('/repos/{owner}/{repo}/collaborators/{user}'.format(
            owner=owner,
            repo=repo,
            user=user,
        ))
        return True
    except gidgethub.BadRequest:
        return False


async def rhobot_try(logger_context: loguru.Logger, event: sansio.Event, github: gh_aiohttp.GitHubAPI, contract_file_basename: str) -> None:
    pull_request_url = event.data['pull_request']['url']
    pull_request = github.getitem(pull_request_url)
    commit_sha = pull_request['head']['sha']
    repo_url = pull_request['head']['repo']['clone_url']
    user = event.data['issue']['user']['login']

    # Only allow collaborators to start Drone jobs
    if not await is_collaborator(github, 'rchain', 'rchain', user):
        logger_context.info('Ignoring a non-collaborator user: {}', user)
        return

    output = start_drone_build(contract_file_basename, commit_sha, repo_url)
    logger_context.info(output)


async def comment_appeared(logger_context: loguru.Logger, event: sansio.Event, github: gh_aiohttp.GitHubAPI, comment: str) -> None:
    if len(comment.splitlines()) > 1:
        return
    stripped = comment.strip()
    fields = re.split('\s+', stripped, 2)
    if len(fields) < 3:
        return
    if fields[0].lower() != 'rhobot':
        return
    if fields[1].lower() != 'try':
        return
    contract_file_basename = fields[3]
    logger_context.info('Got command: {}', fields)
    rhobot_try(logger_context, event, github, contract_file_basename)


async def issue_comment(logger_context: loguru.Logger, event: sansio.Event, github: gh_aiohttp.GitHubAPI) -> None:
    if event.data['action'] == 'created':
        body = event.data['comment']['body']
        await comment_appeared(logger_context, event, github, body)
    elif event.data['action'] == 'edited':
        body = event.data['comment']['body']
        await comment_appeared(logger_context, event, github, body)


async def handle_webhook(request: Any, secret: str, oauth_token: str) -> Any:
    body = await request.read()

    event = sansio.Event.from_http(request.headers, body, secret=secret)

    if event.event == 'ping':
        logger_context = logger.bind(delivery_id=event.delivery_id, event=event.event)
        logger_context.info('Got event')
        if event.event == 'ping':
            return web.Response(status=200)

    if event.event == 'push':
        logger_context = logger.bind(delivery_id=event.delivery_id, event=event.event, ref=event.data['ref'])
        logger_context.info('Got event')
        if event.data['ref'] == 'refs/heads/dev':
            await pushed_to_dev(logger_context, event)

    if event.event == 'issue_comment':
        logger_context = logger.bind(delivery_id=event.delivery_id, event=event.event)
        logger_context.info('Got event')
        async with aiohttp.ClientSession() as session:
            github = gh_aiohttp.GitHubAPI(session, 'rchain/rchain', oauth_token=oauth_token)
            await issue_comment(logger_context, event, github)

    return web.Response(status=200)


async def try_handle_webhook(request: Any) -> Any:
    github_webhook_secret = os.environ['GITHUB_WEBHOOK_SECRET']
    github_personal_token = os.environ['GITHUB_PERSONAL_TOKEN']

    try:
        await handle_webhook(request, github_webhook_secret, github_personal_token)
    except Exception as exc:
        logger.exception('Exception while handling request')
        return web.Response(status=500)

    return web.Response(status=200)


async def handle_health(request: Any) -> Any:
    return web.Response(status=200, text='Bleep Bloop')


if __name__ == "__main__":
    app = web.Application()
    app.router.add_get("/health/", handle_health)
    app.router.add_post("/", try_handle_webhook)
    web.run_app(app, port=9090)

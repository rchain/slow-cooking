#!/usr/bin/env python
import re
import os
import subprocess

from typing import (
    List,
)

from loguru import logger
from loguru._logger import Logger
import aiohttp
from aiohttp import web
import gidgethub
from gidgethub import aiohttp as gh_aiohttp
from gidgethub import sansio


class NoPreviousBuild(ValueError):
    pass


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
        ['build', 'ls', '--limit=1', '--format={{.Number}}', repo],
    )
    stripped = output.strip()
    if stripped == '':
        raise NoPreviousBuild()
    return int(stripped)


def restart_drone_build(drone_server: str, drone_token: str, repo: str, build_number: int) -> str:
    output = drone_command(
        drone_server,
        drone_token,
        ['build', 'start', repo, str(build_number)],
    )
    return output.strip()


async def pushed_to_dev(logger_context: Logger) -> None:
    last_slow_cooking_build_number = get_last_drone_build_number(
        os.environ['SLOW_COOKING_DRONE_SERVER'],
        os.environ['SLOW_COOKING_DRONE_TOKEN'],
        'rchain/slow-cooking',
    )
    slow_cooking_output = restart_drone_build(
        os.environ['SLOW_COOKING_DRONE_SERVER'],
        os.environ['SLOW_COOKING_DRONE_TOKEN'],
        'rchain/slow-cooking',
        last_slow_cooking_build_number,
    )
    logger_context.info(slow_cooking_output)

    last_perf_harness_build_number = get_last_drone_build_number(
        os.environ['PERF_HARNESS_DRONE_SERVER'],
        os.environ['PERF_HARNESS_DRONE_TOKEN'],
        'rchain/perf-harness',
    )
    perf_harness_output = restart_drone_build(
        os.environ['PERF_HARNESS_DRONE_SERVER'],
        os.environ['PERF_HARNESS_DRONE_TOKEN'],
        'rchain/perf-harness',
        last_perf_harness_build_number,
    )
    logger_context.info(perf_harness_output)


def start_drone_build(contract_file_basename: str, commit_sha: str, repo_url: str) -> int:
    drone_server = os.environ['PERF_HARNESS_DRONE_SERVER']
    drone_token = os.environ['PERF_HARNESS_DRONE_TOKEN']

    last_build_number = get_last_drone_build_number(drone_server, drone_token, 'rchain/perf-harness')

    output = drone_command(
        drone_server,
        drone_token,
        [
            'deploy',
            '--param=CONTRACT=/workdir/rchain-perf-harness/{}'.format(contract_file_basename),
            '--param=RCHAIN_COMMIT_HASH={}'.format(commit_sha),
            '--param=RCHAIN_REPO={}'.format(repo_url),
            '--format={{ .Number }}',
            'rchain/perf-harness',
            str(last_build_number),
            'custom_commit',
        ],
    )
    return int(output.strip())


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


def make_build_url(repo: str, build_number: int) -> str:
    result = 'https://drone.perf.rchain-dev.tk/{repo}/{build_number}'.format(
        repo=repo,
        build_number=build_number,
    )
    return result


async def rhobot_try(logger_context: Logger, event: sansio.Event, github: gh_aiohttp.GitHubAPI, contract_file_basename: str) -> None:
    pull_request_url = event.data['issue']['pull_request']['url']
    pull_request = await github.getitem(pull_request_url)
    commit_sha = pull_request['head']['sha']
    repo_url = pull_request['head']['repo']['clone_url']
    user = event.data['issue']['user']['login']

    # Only allow collaborators to start Drone jobs
    if not await is_collaborator(github, 'rchain', 'rchain', user):
        logger_context.info('Ignoring a non-collaborator user: {}', user)
        return

    build_number = start_drone_build(contract_file_basename, commit_sha, repo_url)
    logger_context.info(build_number)

    build_url = make_build_url('rchain/perf-harness', build_number)
    comments_url = event.data['issue']['comments_url']
    await github.post(comments_url, data={'body': build_url})



async def comment_appeared(logger_context: Logger, event: sansio.Event, github: gh_aiohttp.GitHubAPI, comment: str) -> None:
    if len(comment.splitlines()) > 1:
        return
    stripped = comment.strip()
    fields = re.split(r'\s+', stripped, 2)
    if len(fields) < 3:
        return
    if fields[0].lower() != 'rhobot':
        return
    if fields[1].lower() != 'try':
        return
    contract_file_basename = fields[2]
    logger_context.info('Got command: {}', fields)
    await rhobot_try(logger_context, event, github, contract_file_basename)


async def issue_comment(logger_context: Logger, event: sansio.Event, github: gh_aiohttp.GitHubAPI) -> None:
    if event.data['action'] == 'created':
        body = event.data['comment']['body']
        await comment_appeared(logger_context, event, github, body)
    elif event.data['action'] == 'edited':
        body = event.data['comment']['body']
        await comment_appeared(logger_context, event, github, body)


async def handle_webhook(request: web.Request, secret: str, oauth_token: str) -> web.Response:
    body = await request.read()

    event = sansio.Event.from_http(request.headers, body, secret=secret)

    if event.event == 'ping':
        logger.info('Got event: {}', event.delivery_id)
        if event.event == 'ping':
            return web.Response(status=200)

    if event.event == 'push':
        logger.info('Got event: {}', event.delivery_id)
        if event.data['ref'] == 'refs/heads/dev':
            await pushed_to_dev(logger)

    if event.event == 'issue_comment':
        logger.info('Got event: {}', event.delivery_id)
        async with aiohttp.ClientSession() as session:
            github = gh_aiohttp.GitHubAPI(session, 'rchain/rchain', oauth_token=oauth_token)
            await issue_comment(logger, event, github)

    return web.Response(status=200)


async def try_handle_webhook(request: web.Request) -> web.Response:
    # pylint: disable=broad-except

    github_webhook_secret = os.environ['GITHUB_WEBHOOK_SECRET']
    github_personal_token = os.environ['GITHUB_PERSONAL_TOKEN']

    try:
        return await handle_webhook(request, github_webhook_secret, github_personal_token)
    except Exception:
        logger.exception('Exception while handling webhook')
        return web.Response(status=500)


async def handle_health(_: web.Request) -> web.Response:
    return web.Response(status=200, text='Bleep Bloop')


if __name__ == "__main__":
    # pylint: disable=invalid-name
    app = web.Application()
    app.router.add_get("/health/", handle_health)
    app.router.add_post("/", try_handle_webhook)
    web.run_app(app, port=9090)

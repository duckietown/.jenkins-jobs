#!/usr/bin/env python3

import os
import sys
import json
import argparse
import logging
import requests
from collections import defaultdict

logging.basicConfig()
logger = logging.getLogger('jobs-generator')
logger.setLevel(logging.INFO)

TEMPLATE_JOB = '__template__'
DTS_ARGS_INDENT = ' \\\n' + ' ' * 8
DEFAULT_TIMEOUT_MINUTES = 120
BLACKLIST_COMBINATIONS = [
    ("ente", "arm32v7")
]


def main():
    # configure arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobsdir', required=True,
                        help="Directory containing the final jobs")
    parser.add_argument('--repos', required=True,
                        help="File containing the list of repositories to build")
    parser.add_argument('-a', '--arch', required=True,
                        help="Comma-separated list of target architectures for the job to build")
    parser.add_argument('-M', '--distro', required=True,
                        help="Comma-separated list of target distros for the job to build")
    parsed, _ = parser.parse_known_args()
    # ---
    parsed.jobsdir = os.path.abspath(parsed.jobsdir)
    # check if the destination directory exists
    if not os.path.exists(parsed.jobsdir):
        logger.error('The path "{:s}" does not exist.'.format(parsed.jobsdir))
        exit(1)
    # get arguments
    arch_list = parsed.arch.split(',')
    distro_list = parsed.distro.split(',')
    # read list of repos
    with open(parsed.repos, 'r') as fin:
        repos = json.load(fin)
    # load eTags
    cache = defaultdict(lambda: None)
    cache_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'cache.json')
    try:
        with open(cache_file, 'r') as fin:
            cache.update(json.load(fin))
    except:
        pass
    # load template job
    template_config_file = os.path.join(parsed.jobsdir, TEMPLATE_JOB, 'config.xml.template')
    with open(template_config_file, 'rt') as fin:
        template_config = fin.read()
    # check which configurations are valid
    stats = {
        'cache': {
            'hits': 0,
            'misses': 0
        },
        'num_jobs': 0
    }
    logger.info('Found {:d} repositories.'.format(len(repos)))
    for repo in repos:
        logger.info('Analyzing [{:s}]'.format(repo['name']))
        repo_url = repo['origin']
        cached_repo = cache[repo_url]
        repo_build_timeout = repo.get('timeout_min', DEFAULT_TIMEOUT_MINUTES)
        branches_url = 'https://api.github.com/repos/{origin}/branches'.format(**repo)
        # call API
        logger.info('> Fetching list of branches')
        response = requests.get(
            branches_url,
            headers={'If-None-Match': cached_repo['ETag']} if cached_repo else {},
            timeout=10
        )
        # check quota
        if response.status_code == 401 and response.headers['X-RateLimit-Remaining'] == 0:
            logger.error('GitHub API quota exhausted! Exiting.')
            sys.exit(1)
        # check output
        if response.status_code == 404:
            logger.error('< Repository "{origin}" not found'.format(**repo))
            sys.exit(2)
        # update cache
        if response.status_code == 200:
            logger.info('< Fetched from GitHub.')
            stats['cache']['misses'] += 1
            # noinspection PyTypeChecker
            cache[repo_url] = {
                'ETag': response.headers['ETag'],
                'Content': response.json()
            }
            with open(cache_file, 'w') as fout:
                json.dump(cache, fout, indent=4, sort_keys=True)
        if response.status_code == 304:
            stats['cache']['hits'] += 1
            logger.info('< Using cached data.')
        # get json response
        repo_branches = [b['name'] for b in cache[repo_url]['Content']]
        # filter distros
        repo_distros = [b for b in repo_branches if b in distro_list]
        logger.info('> Found distros: {:s}'.format(str(repo_distros)))

        # create one job per distro
        for repo_distro in repo_distros:
            # removed blacklisted configurations
            repo_arch_list = [
                arch for arch in arch_list
                if (repo_distro, arch) not in BLACKLIST_COMBINATIONS
            ]
            # create job by updating the template fields
            job_config_path = os.path.join(
                parsed.jobsdir, job_name(repo_distro, repo['name']), 'config.xml'
            )
            os.makedirs(os.path.dirname(job_config_path))
            with open(job_config_path, 'wt') as fout:
                fout.write(template_config.format(**{
                    'REPO_NAME': repo['name'],
                    'REPO_URL': 'https://github.com/{:s}'.format(repo['origin']),
                    'REPO_ARCH': ''.join(map(
                        lambda a: '<string>{:s}</string>'.format(a), repo_arch_list
                    )),
                    'REPO_DISTRO': repo_distro,
                    'GIT_URL': '{GIT_URL}',
                    'DUCKIETOWN_CI_DT_SHELL_VERSION': '{DUCKIETOWN_CI_DT_SHELL_VERSION}',
                    'BASE_JOB': ', '.join([
                        job_name(repo_distro, b.strip()) for b in repo['base'].split(',')
                    ]) if 'base' in repo else '',
                    'DTS_ARGS': DTS_ARGS_INDENT + DTS_ARGS_INDENT.join([
                        '{:s}={:s}'.format(k, v)
                        for k, v in repo['dts_args'].items()
                    ]) if 'dts_args' in repo else '',
                    'TIMEOUT_MINUTES': repo_build_timeout
                }))
            stats['num_jobs'] += 1
    # print out stats
    logger.info('Statistics: Total jobs: {:d}; Cache[Hits]: {:d}; Cache[Misses]: {:d}'.format(
        stats['num_jobs'], stats['cache']['hits'], stats['cache']['misses']
    ))
    logger.info('Done!')


def job_name(distro, repo_name):
    return 'Docker Autobuild - {:s} - {:s}'.format(distro, repo_name)


if __name__ == '__main__':
    main()

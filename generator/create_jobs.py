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

def main():
    # configure arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobsdir', required=True,
                        help="Directory containing the final jobs")
    parser.add_argument('--repos', required=True,
                        help="File containing the list of repositories to build")
    parser.add_argument('-a', '--arch', required=True,
                        help="Comma-separated list of target architectures for the job to build")
    parser.add_argument('-M', '--major', required=True,
                        help="Comma-separated list of target majors for the job to build")
    parsed, _ = parser.parse_known_args()
    # ---
    parsed.jobsdir = os.path.abspath(parsed.jobsdir)
    # check if the destination directory exists
    if not os.path.exists(parsed.jobsdir):
        logger.error('The path "{:s}" does not exist.'.format(parsed.jobsdir))
        exit(1)
    # get arguments
    arch_list = parsed.arch.split(',')
    major_list = parsed.major.split(',')
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
        # filter majors
        repo_majors = [b for b in repo_branches if b in major_list]
        logger.info('> Found majors: {:s}'.format(str(repo_majors)))
        # create job by updating the template fields
        job_config_path = os.path.join(parsed.jobsdir, job_name(repo['name']), 'config.xml')
        os.makedirs(os.path.dirname(job_config_path))
        with open(job_config_path, 'wt') as fout:
            fout.write(template_config.format(**{
                'REPO_NAME': repo['name'],
                'REPO_URL': 'https://github.com/{:s}'.format(repo['origin']),
                'REPO_ARCH': ''.join(map(
                    lambda a: '<string>{:s}</string>'.format(a), arch_list
                )),
                'REPO_MAJOR': ''.join(map(
                    lambda m: '<string>{:s}</string>'.format(m), repo_majors
                )),
                'DUCKIETOWN_CI_MAJOR': '{DUCKIETOWN_CI_MAJOR}',
                'GIT_URL': '{GIT_URL}',
                'DUCKIETOWN_CI_DT_SHELL_VERSION': '{DUCKIETOWN_CI_DT_SHELL_VERSION}',
                'BASE_JOB': ', '.join([job_name(b.strip()) for b in repo['base'].split(',')])
                            if 'base' in repo else ''
            }))
        stats['num_jobs'] += 1
    # print out stats
    logger.info('Statistics: Total jobs: {:d}; Cache[Hits]: {:d}; Cache[Misses]: {:d}'.format(
        stats['num_jobs'], stats['cache']['hits'], stats['cache']['misses']
    ))
    logger.info('Done!')


def job_name(repo_name):
    return 'Docker Autobuild - {:s}'.format(repo_name)


if __name__ == '__main__':
    main()

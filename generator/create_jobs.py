#!/usr/bin/env python3
import argparse
import copy
import json
import logging
import os
import sys
from collections import defaultdict

import requests

logging.basicConfig()
logger = logging.getLogger("jobs-generator")
logger.setLevel(logging.INFO)

TEMPLATE_JOB = "__template__"
DTS_ARGS_INDENT = " \\\n" + " " * 8
DEFAULT_TIMEOUT_MINUTES = 120
BLACKLIST_COMBINATIONS = [
    ("ente", "arm32v7"),
    ("ente-staging", "arm32v7"),
]
BUILD_FROM_SCRIPT_TOKEN = "d249580a-b182-41fb-8f3d-ec5d24530e71"


def main():
    # configure arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobsdir", required=True, help="Directory containing the final jobs")
    parser.add_argument("--repos", required=True, help="File containing the list of repositories to build")
    parser.add_argument(
        "-a",
        "--arch",
        required=True,
        help="Comma-separated list of target architectures for the job to build",
    )
    parser.add_argument(
        "-M", "--distro", required=True, help="Comma-separated list of target distros for the job to build"
    )
    parsed, _ = parser.parse_known_args()
    # ---
    parsed.jobsdir = os.path.abspath(parsed.jobsdir)
    # check if the destination directory exists
    if not os.path.exists(parsed.jobsdir):
        logger.error('The path "{:s}" does not exist.'.format(parsed.jobsdir))
        exit(1)
    # get arguments
    arch_list = parsed.arch.split(",")
    distro_list = parsed.distro.split(",")
    # read list of repos
    with open(parsed.repos, "r") as fin:
        repos = json.load(fin)
    # load eTags
    cache = defaultdict(lambda: None)
    cache_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "cache.json")
    try:
        with open(cache_file, "r") as fin:
            cache.update(json.load(fin))
    except:
        pass
    # load template job
    template_config_file = os.path.join(parsed.jobsdir, TEMPLATE_JOB, "config.xml.template")
    with open(template_config_file, "rt") as fin:
        template_config = fin.read()
    # check which configurations are valid
    stats = {"cache": {"hits": 0, "misses": 0}, "num_jobs": 0}
    logger.info("Found {:d} repositories.".format(len(repos)))
    for repo in repos:
        logger.info("Analyzing [{:s}]".format(repo["name"]))
        repo_url = repo["origin"]
        cached_repo = cache[repo_url]
        repo_build_timeout = repo.get("timeout_min", DEFAULT_TIMEOUT_MINUTES)
        branches_url = "https://api.github.com/repos/{origin}/branches".format(**repo)
        # call API
        logger.info("> Fetching list of branches")
        response = requests.get(
            branches_url, headers={"If-None-Match": cached_repo["ETag"]} if cached_repo else {}, timeout=10
        )
        # check quota
        if response.status_code == 401 and response.headers["X-RateLimit-Remaining"] == 0:
            logger.error("GitHub API quota exhausted! Exiting.")
            sys.exit(1)
        # check output
        if response.status_code == 404:
            logger.error('< Repository "{origin}" not found'.format(**repo))
            sys.exit(2)
        # update cache
        if response.status_code == 200:
            logger.info("< Fetched from GitHub.")
            stats["cache"]["misses"] += 1
            # noinspection PyTypeChecker
            cache[repo_url] = {"ETag": response.headers["ETag"], "Content": response.json()}
            with open(cache_file, "w") as fout:
                json.dump(cache, fout, indent=4, sort_keys=True)
        if response.status_code == 304:
            stats["cache"]["hits"] += 1
            logger.info("< Using cached data.")
        # get json response
        repo_branches = [b["name"] for b in cache[repo_url]["Content"]]
        # filter distros
        repo_distros = [b for b in repo_branches if b in distro_list]
        logger.info("> Found distros: {:s}".format(str(repo_distros)))

        # create one job per distro
        for repo_distro in repo_distros:
            # removed blacklisted configurations
            repo_arch_list = [arch for arch in arch_list
                              if (repo_distro, arch) not in BLACKLIST_COMBINATIONS]
            # dts arguments
            dts_args = copy.deepcopy(repo["dts_args"]) if "dts_args" in repo else {}
            # staging?
            is_staging = "-staging" in repo_distro

            DOCKER_USERNAME = "duckietowndaemon"
            TAG = repo_distro.split("-")[0]
            if is_staging:
                PIP_INDEX_URL = "https://staging.duckietown.org/root/devel/"
                DTSERVER = "https://challenges-stage.duckietown.org"
                DOCKER_REGISTRY = "registry-stage2.duckietown.org"
                DOCKER_PASSWORD_KEY = "STAGING_DOCKER_PASSWORD"
            else:
                PIP_INDEX_URL = "https://pypi.org/simple"
                DTSERVER = "https://challenges.duckietown.org/v4"
                DOCKER_REGISTRY = "docker.io"
                DOCKER_PASSWORD_KEY = "PRODUCTION_DOCKER_PASSWORD"

            # ---
            if dts_args:
                DTS_ARGS = (DTS_ARGS_INDENT
                            + DTS_ARGS_INDENT.join(
                        [
                            ("{:s}={:s}".format(k, v)) if v is not True else k
                            for k, v in dts_args.items()
                        ]
                    ))
            else:
                DTS_ARGS = ""

            for arch in repo_arch_list:
                if "base" in repo:
                    BASE_JOB = ", ".join(
                        [job_name(repo_distro, b.strip(), arch) for b in repo["base"].split(",")]
                    )
                else:
                    BASE_JOB = ""

                jname = job_name(repo_distro, repo["name"], arch)
                # create job by updating the template fields
                job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
                params = {
                    "REPO_NAME": repo["name"],
                    "REPO_URL": "https://github.com/{:s}".format(repo["origin"]),
                    "REPO_ARCH": arch,
                    "TAG": TAG,
                    "REPO_DISTRO": repo_distro,
                    "PIP_INDEX_URL": PIP_INDEX_URL,
                    "DTSERVER": DTSERVER,
                    "DOCKER_REGISTRY": DOCKER_REGISTRY,
                    "DOCKER_USERNAME": DOCKER_USERNAME,
                    "DOCKER_PASSWORD_KEY": DOCKER_PASSWORD_KEY,
                    "GIT_URL": "{GIT_URL}",
                    "DUCKIETOWN_CI_DT_SHELL_VERSION": repo_distro,
                    "BASE_JOB": BASE_JOB,
                    "DTS_ARGS": DTS_ARGS,
                    "TIMEOUT_MINUTES": repo_build_timeout,
                    "BUILD_FROM_SCRIPT_TOKEN": BUILD_FROM_SCRIPT_TOKEN
                }
                config = template_config.format(**params)
                os.makedirs(os.path.dirname(job_config_path))
                with open(job_config_path, "wt") as fout:
                    fout.write(config)
                stats["num_jobs"] += 1

    # print out stats
    logger.info(
        "Statistics: Total jobs: {:d}; Cache[Hits]: {:d}; Cache[Misses]: {:d}".format(
            stats["num_jobs"], stats["cache"]["hits"], stats["cache"]["misses"]
        )
    )
    logger.info("Done!")


def job_name(distro, repo_name, arch):
    return "Docker Autobuild - {:s} - {:s} - {:s}".format(distro, repo_name, arch)


if __name__ == "__main__":
    main()

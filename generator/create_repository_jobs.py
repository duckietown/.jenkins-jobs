#!/usr/bin/env python3
import argparse
import copy
import json
import logging
import os
import sys
from collections import defaultdict
from typing import Optional, List, Dict

import requests

logging.basicConfig()
logger = logging.getLogger("jobs-generator")
logger.setLevel(logging.INFO)

AUTOBUILD_TEMPLATE_JOB = "__autobuild_template__"
AUTOMERGE_TEMPLATE_JOB = "__automerge_template__"
STAGESYNC_TEMPLATE_JOB = "__stagesync_template__"
DISTROSYNC_TEMPLATE_JOB = "__distrosync_template__"
DTS_ARGS_INDENT = " \\\n" + " " * 8
DEFAULT_TIMEOUT_MINUTES = 120
DISTRO_ARCH_BLACKLIST = [
    ("ente", "arm32v7"),
    ("ente-staging", "arm32v7"),
]
BLACKLIST = []
DOCKER_USERNAMES = {
    "docker.io": "afdaniele",
    "registry-stage2.duckietown.org": "duckietowndaemon"
}
BUILD_FROM_SCRIPT_TOKEN = "d249580a-b182-41fb-8f3d-ec5d24530e71"
DTS_DEVEL_BUILD_BACKEND = {
    "daffy": "buildx",
    "daffy-staging": "buildx",
}


def main():
    # configure arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--jobsdir",
        required=True,
        help="Directory containing the final jobs"
    )
    parser.add_argument(
        "--repos",
        required=True,
        help="File containing the list of repositories to build",
    )
    parser.add_argument(
        "-a",
        "--arch",
        required=True,
        help="Comma-separated list of target architectures for the job to build",
    )
    parser.add_argument(
        "-M",
        "--distro",
        required=True,
        help="Comma-separated list of target distros for the job to build",
    )
    parser.add_argument(
        "--debug",
        default=False,
        action="store_true",
        help="Run in debug mode",
    )
    parsed, _ = parser.parse_known_args()
    # ---
    # logging setup
    if parsed.debug:
        logger.setLevel(logging.DEBUG)
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
    # load template jobs
    # - Docker Autobuild job template
    autobuild_template_config_file = os.path.join(
        parsed.jobsdir, AUTOBUILD_TEMPLATE_JOB, "config.xml.template"
    )
    with open(autobuild_template_config_file, "rt") as fin:
        autobuild_template_config = fin.read()
    # - Git Autmerge job template
    automerge_template_config_file = os.path.join(
        parsed.jobsdir, AUTOMERGE_TEMPLATE_JOB, "config.xml.template"
    )
    with open(automerge_template_config_file, "rt") as fin:
        automerge_template_config = fin.read()
    # - Stage Sync job template
    stagesync_template_config_file = os.path.join(
        parsed.jobsdir, STAGESYNC_TEMPLATE_JOB, "config.xml.template"
    )
    with open(stagesync_template_config_file, "rt") as fin:
        stagesync_template_config = fin.read()
    # - Distro Sync job template
    distrosync_template_config_file = os.path.join(
        parsed.jobsdir, DISTROSYNC_TEMPLATE_JOB, "config.xml.template"
    )
    with open(distrosync_template_config_file, "rt") as fin:
        distrosync_template_config = fin.read()
    # check which configurations are valid
    stats = {"cache": {"hits": 0, "misses": 0}, "num_jobs": 0, "num_repos": len(repos)}
    logger.info("Found {:d} repositories.".format(len(repos)))
    # generate headers for github
    headers = {}
    # github token
    github_token = os.environ.get("GITHUB_TOKEN", None)
    if github_token is None:
        msg = "Please set environment variable GITHUB_TOKEN "
        logger.error(msg)
        sys.exit(6)
    headers["Authorization"] = f"token {github_token}"
    # make parent -> children map
    children: Dict[str, List[str]] = defaultdict(list)
    for repo in repos:
        if "base" not in repo:
            continue
        repo_bases = repo["base"] if isinstance(repo["base"], list) else [repo["base"]]
        for repo_base in repo_bases:
            this_job = repo["name"]
            base_job = repo_base.strip()
            children[base_job].append(this_job)

    # store things to write
    jobs_to_write = {}
    repo_branches = {}
    repo_by_name = {}
    # ---
    for repo in repos:
        logger.info("Analyzing [{:s}]".format(repo["name"]))
        # repo info
        repo_name = repo["name"]
        repo_origin = repo["origin"]
        repo_by_name[repo_name] = repo
        REPO_URL = "https://github.com/{:s}".format(repo_origin)
        GIT_URL = "git@github.com:{:s}".format(repo_origin)
        cached_repo: Optional[dict] = cache[repo_origin]
        repo_build_timeout = repo.get("timeout_min", DEFAULT_TIMEOUT_MINUTES)
        branches_url = "https://api.github.com/repos/{origin}/branches?per_page=100".format(**repo)
        # call API
        logger.info("> Fetching list of branches")
        if cached_repo:
            headers["If-None-Match"] = cached_repo["ETag"]
        response = requests.get(branches_url, headers=headers, timeout=10)
        # check quota
        if (
            response.status_code == 401
            and response.headers["X-RateLimit-Remaining"] == 0
        ):
            logger.error("GitHub API quota exhausted! Exiting.")
            sys.exit(1)
        # check output
        elif response.status_code == 404:
            logger.error('< Repository "{origin}" not found'.format(**repo))
            sys.exit(2)
        # update cache
        elif response.status_code == 200:
            logger.info("< Fetched from GitHub.")
            stats["cache"]["misses"] += 1
            # update cache
            # noinspection PyTypeChecker
            cache[repo_origin] = {
                "ETag": response.headers["ETag"],
                "Content": response.json(),
            }
            with open(cache_file, "w") as fout:
                json.dump(cache, fout, indent=4, sort_keys=True)
        elif response.status_code == 304:
            stats["cache"]["hits"] += 1
            logger.info("< Using cached data.")
        elif response.status_code == 403:
            logger.error(
                f"< Not authorized to read. Using \nurl = {branches_url}\nheaders = {headers}"
            )
            sys.exit(4)
        else:
            logger.error(f"< Unexpected response {response.status_code}")
            sys.exit(4)
        # get json response
        # noinspection PyUnresolvedReferences
        repo_branches[repo_name] = [b["name"] for b in cache[repo_origin]["Content"]]
        logger.debug(f"Branches found: {repo_branches[repo_name]}")
        # filter distros
        repo_distros = [b for b in repo_branches[repo_name] if b in distro_list]
        logger.info("> Found distros: {:s}".format(str(repo_distros)))

        # create one job per distro
        for repo_distro in repo_distros:
            # removed blacklisted configurations
            repo_arch_list = [
                arch
                for arch in arch_list
                if (repo_distro, arch) not in DISTRO_ARCH_BLACKLIST
            ]
            repo_arch_list = list(filter(
                lambda arch: arch not in repo.get("blacklist", []),
                repo_arch_list
            ))
            for a in repo.get("blacklist", []):
                BLACKLIST.append((repo_name, a))
            # dts arguments
            dts_args = copy.deepcopy(repo["dts_args"]) if "dts_args" in repo else {}
            # staging?
            is_staging = "-staging" in repo_distro

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

            DOCKER_USERNAME = DOCKER_USERNAMES[DOCKER_REGISTRY]

            # ---
            if dts_args:
                DTS_ARGS = DTS_ARGS_INDENT + DTS_ARGS_INDENT.join(
                    [
                        ("{:s}={:s}".format(k, v)) if v is not True else k
                        for k, v in dts_args.items()
                    ]
                )
            else:
                DTS_ARGS = ""

            for repo_arch in repo_arch_list:
                if "base" in repo:
                    repo_base = repo["base"] if isinstance(repo["base"], list) else [repo["base"]]
                    BASE_JOB = ", ".join([
                        autobuild_job_name(repo_distro, b.strip(), repo_arch) for b in repo_base
                    ])
                else:
                    BASE_JOB = ""

                # get children jobs
                CHILDREN_JOBS = ", ".join([
                    autobuild_job_name(repo_distro, c, repo_arch) for c in children[repo_name]
                ])

                jname = autobuild_job_name(repo_distro, repo_name, repo_arch)
                # create job by updating the template fields
                job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
                params = {
                    "REPO_NAME": repo_name,
                    "REPO_URL": REPO_URL,
                    "REPO_ARCH": repo_arch,
                    "TAG": TAG,
                    "BASE_TAG": TAG,
                    "REPO_DISTRO": repo_distro,
                    "PIP_INDEX_URL": PIP_INDEX_URL,
                    "DTSERVER": DTSERVER,
                    "DOCKER_REGISTRY": DOCKER_REGISTRY,
                    "DOCKER_USERNAME": DOCKER_USERNAME,
                    "DOCKER_PASSWORD_KEY": DOCKER_PASSWORD_KEY,
                    "GIT_URL": GIT_URL,
                    "DUCKIETOWN_CI_DT_SHELL_VERSION": repo_distro,
                    "BASE_JOB": BASE_JOB,
                    "CHILDREN_JOBS": CHILDREN_JOBS,
                    "LOCATION": repo.get("location", ""),
                    "DTS_ARGS": DTS_ARGS,
                    "TIMEOUT_MINUTES": repo_build_timeout,
                    "BUILD_FROM_SCRIPT_TOKEN": BUILD_FROM_SCRIPT_TOKEN,
                    "DTS_DEVEL_BUILD_BACKEND": DTS_DEVEL_BUILD_BACKEND.get(repo_distro, "build"),
                    "DUCKIETOWN_CI_IS_STAGING": str(int(is_staging)),
                    "DUCKIETOWN_CI_IS_PRODUCTION": str(int(not is_staging)),
                }
                config = autobuild_template_config.format(**params)

                jobs_to_write[(repo_distro, repo_name, repo_arch)] = {
                    "config_path": job_config_path,
                    "config": config,
                    "labels": repo["labels"]
                }

    # populate blacklists
    found = 1
    while found > 0:
        found = 0
        for (_, repo_name, repo_arch), job in jobs_to_write.items():
            repo = repo_by_name[repo_name]
            repo_bases = repo.get("base", [])
            repo_bases = repo_bases if isinstance(repo_bases, list) else [repo_bases]
            for repo_base in repo_bases:
                # don't write if the base is blacklisted
                if (repo_base, repo_arch) in BLACKLIST and (repo_name, repo_arch) not in BLACKLIST:
                    BLACKLIST.append((repo_name, repo_arch))
                    logger.info(f"Blacklisting {(repo_name, repo_arch)} because base job "
                                f"{(repo_base, repo_arch)} is blacklisted.")
                    found += 1

    # create autobuild jobs
    for (_, repo_name, repo_arch), job in jobs_to_write.items():
        # don't write if blacklisted
        if (repo_name, repo_arch) in BLACKLIST:
            continue
        # must not exclude 'autobuild'
        if "-autobuild" in job["labels"]:
            continue
        job_config_path = job["config_path"]
        config = job["config"]
        # write
        os.makedirs(os.path.dirname(job_config_path))
        with open(job_config_path, "wt") as fout:
            fout.write(config)
        stats["num_jobs"] += 1

    # ---
    # create auto-merging jobs
    for repo in repos:
        # must not exclude 'automerge'
        if "-automerge" in repo["labels"]:
            continue
        # repo info
        repo_name = repo["name"]
        repo_origin = repo["origin"]
        REPO_URL = "https://github.com/{:s}".format(repo_origin)
        GIT_URL = "git@github.com:{:s}".format(repo_origin)
        # one job per pair (distro, distro-staging)
        for repo_branch in repo_branches[repo_name]:
            # auto-merge can only happen on X-staging branches
            if not repo_branch.endswith("-staging"):
                continue
            # we only add this job if this branch is one of those we care about
            if repo_branch not in distro_list:
                continue
            repo_branch_prod = repo_branch[:-len("-staging")]
            if repo_branch_prod not in repo_branches[repo_name]:
                logger.warning(f"Found branch '{repo_branch}' but not '{repo_branch_prod}' "
                               f"in repository '{repo_name}'. This is weird. "
                               f"Available branches are: {str(repo_branches[repo_name])}")

            jname = automerge_job_name(
                from_branch=repo_branch_prod,
                into_branch=repo_branch,
                repo_name=repo_name
            )
            # create job by updating the template fields
            job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
            params = {
                "REPO_NAME": repo_name,
                "REPO_URL": REPO_URL,
                "FROM_BRANCH": repo_branch_prod,
                "INTO_BRANCH": repo_branch,
                "GIT_URL": GIT_URL,
                "TIMEOUT_MINUTES": 10
            }
            config = automerge_template_config.format(**params)
            # write job to disk
            os.makedirs(os.path.dirname(job_config_path))
            with open(job_config_path, "wt") as fout:
                fout.write(config)
            stats["num_jobs"] += 1

    # ---
    # create stage-sync jobs
    for repo in repos:
        # must not exclude 'stagesync'
        if "-stagesync" in repo["labels"]:
            continue
        # repo info
        repo_name = repo["name"]
        repo_origin = repo["origin"]
        REPO_URL = "https://github.com/{:s}".format(repo_origin)
        GIT_URL = "git@github.com:{:s}".format(repo_origin)
        # one job per pair (distro, distro-staging)
        for repo_branch in repo_branches[repo_name]:
            # stage-sync can only happen on X-staging branches
            if not repo_branch.endswith("-staging"):
                continue
            # we only add this job if this branch is one of those we care about
            if repo_branch not in distro_list:
                continue
            repo_branch_prod = repo_branch[:-len("-staging")]
            if repo_branch_prod not in repo_branches[repo_name]:
                logger.warning(f"Found branch '{repo_branch}' but not '{repo_branch_prod}' "
                               f"in repository '{repo_name}'. This is weird. "
                               f"Available branches are: {str(repo_branches[repo_name])}")

            jname = stagesync_job_name(
                from_branch=repo_branch_prod,
                to_branch=repo_branch,
                repo_name=repo_name
            )

            # find base jobs
            if "base" in repo:
                repo_base = repo["base"] if isinstance(repo["base"], list) else [repo["base"]]
                BASE_JOB = ", ".join([
                    stagesync_job_name(repo_branch_prod, repo_branch, b) for b in repo_base
                ])
            else:
                BASE_JOB = ""

            # create job by updating the template fields
            job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
            params = {
                "REPO_OWNER": "duckietown",
                "REPO_NAME": repo_name,
                "REPO_URL": REPO_URL,
                "GIT_URL": GIT_URL,
                "FROM_BRANCH": repo_branch_prod,
                "TO_BRANCH": repo_branch,
                "BASE_JOB": BASE_JOB,
                "TIMEOUT_MINUTES": 1
            }
            config = stagesync_template_config.format(**params)
            # write job to disk
            os.makedirs(os.path.dirname(job_config_path))
            with open(job_config_path, "wt") as fout:
                fout.write(config)
            stats["num_jobs"] += 1

    # ---
    # create distro-sync jobs
    for repo in repos:
        # must not exclude 'distrosync'
        if "-distrosync" in repo["labels"]:
            continue
        # repo info
        repo_name = repo["name"]
        repo_origin = repo["origin"]
        REPO_URL = "https://github.com/{:s}".format(repo_origin)
        GIT_URL = "git@github.com:{:s}".format(repo_origin)
        # one job per pair ( distro1[-staging] , distro2[-staging] )
        for distro1, distro2 in zip(distro_list, distro_list[1:]):
            # we only add this job if this repo has both branches
            if distro1 not in repo_branches[repo_name] or distro2 not in repo_branches[repo_name]:
                continue
            # job name
            jname = distrosync_job_name(
                from_branch=distro2,
                to_branch=distro1,
                repo_name=repo_name
            )
            # find base jobs
            if "base" in repo:
                repo_base = repo["base"] if isinstance(repo["base"], list) else [repo["base"]]
                BASE_JOB = ", ".join([
                    distrosync_job_name(distro2, distro1, b) for b in repo_base
                ])
            else:
                BASE_JOB = ""

            # create job by updating the template fields
            job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
            params = {
                "REPO_ORIGIN": repo_origin,
                "REPO_NAME": repo_name,
                "REPO_URL": REPO_URL,
                "GIT_URL": GIT_URL,
                "FROM_BRANCH": distro2,
                "TO_BRANCH": distro1,
                "BASE_JOB": BASE_JOB,
                "TIMEOUT_MINUTES": 1
            }
            config = distrosync_template_config.format(**params)
            # write job to disk
            os.makedirs(os.path.dirname(job_config_path))
            with open(job_config_path, "wt") as fout:
                fout.write(config)
            stats["num_jobs"] += 1

    # print out stats
    logger.info(
        "Statistics: Total repos: {:d}; Total jobs: {:d}; Cache[Hits]: {:d}; Cache[Misses]: {:d}".format(
            stats["num_repos"], stats["num_jobs"], stats["cache"]["hits"], stats["cache"]["misses"]
        )
    )
    logger.info("Done!")


def autobuild_job_name(distro, repo_name, arch):
    return "Docker Autobuild - {:s} - {:s} - {:s}".format(distro, repo_name, arch)


def automerge_job_name(from_branch, into_branch, repo_name):
    return "Git Automerge - {:s} -> {:s} - {:s}".format(from_branch, into_branch, repo_name)


def stagesync_job_name(from_branch, to_branch, repo_name):
    return "Stage Sync - {:s} >= {:s} - {:s}".format(from_branch, to_branch, repo_name)


def distrosync_job_name(from_branch, to_branch, repo_name):
    return "Distro Sync - {:s} >= {:s} - {:s}".format(from_branch, to_branch, repo_name)


if __name__ == "__main__":
    main()

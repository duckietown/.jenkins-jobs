#!/usr/bin/env python3
import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from typing import Optional

import requests

logging.basicConfig()
logger = logging.getLogger("jobs-generator")
logger.setLevel(logging.INFO)

BOOKBUILD_TEMPLATE_JOB = "__bookbuild_template__"
AUTOMERGE_TEMPLATE_JOB = "__automerge_template__"
STAGESYNC_TEMPLATE_JOB = "__stagesync_template__"
DISTROSYNC_TEMPLATE_JOB = "__distrosync_template__"
DEFAULT_TIMEOUT_MINUTES = 30
BUILD_FROM_SCRIPT_TOKEN = "d249580a-b182-41fb-8f3d-ec5d24530e71"


def main():
    # configure arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--jobsdir",
        required=True,
        help="Directory containing the final jobs"
    )
    parser.add_argument(
        "--books",
        required=True,
        help="File containing the list of books to build",
    )
    parser.add_argument(
        "-M",
        "--distro",
        required=True,
        help="Comma-separated list of target distros for the job to build",
    )
    parsed, _ = parser.parse_known_args()
    # ---
    parsed.jobsdir = os.path.abspath(parsed.jobsdir)
    # check if the destination directory exists
    if not os.path.exists(parsed.jobsdir):
        logger.error('The path "{:s}" does not exist.'.format(parsed.jobsdir))
        exit(1)
    # get arguments
    distro_list = parsed.distro.split(",")
    # read list of books
    with open(parsed.books, "r") as fin:
        books = json.load(fin)
    # load eTags
    cache = defaultdict(lambda: None)
    cache_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "cache.json")
    try:
        with open(cache_file, "r") as fin:
            cache.update(json.load(fin))
    except:
        pass
    # load template jobs
    # - Book Build job template
    bookbuild_template_config_file = os.path.join(
        parsed.jobsdir, BOOKBUILD_TEMPLATE_JOB, "config.xml.template"
    )
    with open(bookbuild_template_config_file, "rt") as fin:
        bookbuild_template_config = fin.read()
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
    stats = {"cache": {"hits": 0, "misses": 0}, "num_jobs": 0, "num_books": len(books)}
    logger.info("Found {:d} books.".format(len(books)))
    # generate headers for github
    headers = {}
    # github token
    github_token = os.environ.get("GITHUB_TOKEN", None)
    if github_token is None:
        msg = "Please set environment variable GITHUB_TOKEN "
        logger.error(msg)
        sys.exit(6)
    headers["Authorization"] = f"token {github_token}"

    # store things to write
    jobs_to_write = {}
    repo_branches = {}
    repo_by_name = {}
    # ---
    for book in books:
        logger.info("Analyzing [{:s}]".format(book["name"]))
        # book info
        repo_name = book["name"]
        repo_origin = book["origin"]
        repo_by_name[repo_name] = book
        REPO_URL = "https://github.com/{:s}".format(repo_origin)
        GIT_URL = "git@github.com:{:s}".format(repo_origin)
        cached_repo: Optional[dict] = cache[repo_origin]
        repo_build_timeout = book.get("timeout_min", DEFAULT_TIMEOUT_MINUTES)
        branches_url = "https://api.github.com/repos/{origin}/branches".format(**book)
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
            logger.error('< booksitory "{origin}" not found'.format(**book))
            sys.exit(2)
        # update cache
        elif response.status_code == 200:
            logger.info("< Fetched from GitHub.")
            stats["cache"]["misses"] += 1
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
        # update cache
        # get json response
        # noinspection PyUnresolvedReferences
        repo_branches[repo_name] = [b["name"] for b in cache[repo_origin]["Content"]]
        # filter distros
        repo_distros = [b for b in repo_branches[repo_name] if b in distro_list]
        logger.info("> Found distros: {:s}".format(str(repo_distros)))

        # create one job per distro
        for repo_distro in repo_distros:
            # staging?
            is_staging = "-staging" in repo_distro
            if is_staging:
                DOCKER_REGISTRY = "registry-stage2.duckietown.org"
                BOOK_LIBRARY_DNS = "staging-docs.duckietown.com"
            else:
                DOCKER_REGISTRY = "docker.io"
                BOOK_LIBRARY_DNS = "docs.duckietown.com"
            # job name
            jname = bookbuild_job_name(repo_distro, repo_name)
            # create job by updating the template fields
            job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
            params = {
                "REPO_NAME": repo_name,
                "REPO_URL": REPO_URL,
                "REPO_DISTRO": repo_distro,
                "GIT_URL": GIT_URL,
                "DOCKER_REGISTRY": DOCKER_REGISTRY,
                "BOOK_LIBRARY_DNS": BOOK_LIBRARY_DNS,
                "BASE_JOB": "",
                "DUCKIETOWN_CI_DT_SHELL_VERSION": repo_distro,
                "TIMEOUT_MINUTES": repo_build_timeout,
                "BUILD_FROM_SCRIPT_TOKEN": BUILD_FROM_SCRIPT_TOKEN,
            }
            config = bookbuild_template_config.format(**params)

            jobs_to_write[(repo_distro, repo_name)] = {
                "config_path": job_config_path,
                "config": config
            }

    # write jobs to file
    for (_, repo_name), job in jobs_to_write.items():
        job_config_path = job["config_path"]
        config = job["config"]
        # write
        os.makedirs(os.path.dirname(job_config_path))
        with open(job_config_path, "wt") as fout:
            fout.write(config)
        stats["num_jobs"] += 1

    # ---
    # create auto-merging jobs
    for book in books:
        # must not exclude 'automerge'
        if "-automerge" in book.get("labels", []):
            continue
        # book info
        book_name = book["name"]
        book_origin = book["origin"]
        REPO_URL = "https://github.com/{:s}".format(book_origin)
        GIT_URL = "git@github.com:{:s}".format(book_origin)
        # one job per pair (distro, distro-staging)
        for book_branch in repo_branches[book_name]:
            # auto-merge can only happen on X-staging branches
            if not book_branch.endswith("-staging"):
                continue
            # we only add this job if this branch is one of those we care about
            if book_branch not in distro_list:
                continue
            book_branch_prod = book_branch[:-len("-staging")]
            if book_branch_prod not in repo_branches[book_name]:
                logger.warning(f"Found branch '{book_branch}' but not '{book_branch_prod}' "
                               f"in booksitory '{book_name}'. This is weird. "
                               f"Available branches are: {str(repo_branches[book_name])}")

            jname = automerge_job_name(
                from_branch=book_branch_prod,
                into_branch=book_branch,
                repo_name=book_name
            )
            # create job by updating the template fields
            job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
            params = {
                "REPO_NAME": book_name,
                "REPO_URL": REPO_URL,
                "FROM_BRANCH": book_branch_prod,
                "INTO_BRANCH": book_branch,
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
    for book in books:
        # book info
        book_name = book["name"]
        book_origin = book["origin"]
        REPO_URL = "https://github.com/{:s}".format(book_origin)
        GIT_URL = "git@github.com:{:s}".format(book_origin)
        # one job per pair (distro, distro-staging)
        for book_branch in repo_branches[book_name]:
            # stage-sync can only happen on X-staging branches
            if not book_branch.endswith("-staging"):
                continue
            # we only add this job if this branch is one of those we care about
            if book_branch not in distro_list:
                continue
            book_branch_prod = book_branch[:-len("-staging")]
            if book_branch_prod not in repo_branches[book_name]:
                logger.warning(f"Found branch '{book_branch}' but not '{book_branch_prod}' "
                               f"in booksitory '{book_name}'. This is weird. "
                               f"Available branches are: {str(repo_branches[book_name])}")

            jname = stagesync_job_name(
                from_branch=book_branch_prod,
                to_branch=book_branch,
                repo_name=book_name
            )

            # find base jobs
            if "base" in book:
                book_base = book["base"] if isinstance(book["base"], list) else [book["base"]]
                BASE_JOB = ", ".join([
                    stagesync_job_name(book_branch_prod, book_branch, b) for b in book_base
                ])
            else:
                BASE_JOB = ""

            # create job by updating the template fields
            job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
            params = {
                "REPO_OWNER": "duckietown",
                "REPO_NAME": book_name,
                "REPO_URL": REPO_URL,
                "GIT_URL": GIT_URL,
                "FROM_BRANCH": book_branch_prod,
                "TO_BRANCH": book_branch,
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
    for book in books:
        # book info
        book_name = book["name"]
        book_origin = book["origin"]
        REPO_URL = "https://github.com/{:s}".format(book_origin)
        GIT_URL = "git@github.com:{:s}".format(book_origin)
        # one job per pair ( distro1[-staging] , distro2[-staging] )
        for distro1, distro2 in zip(distro_list, distro_list[1:]):
            # we only add this job if this book has both branches
            if distro1 not in repo_branches[book_name] or distro2 not in repo_branches[book_name]:
                continue
            # job name
            jname = distrosync_job_name(
                from_branch=distro2,
                to_branch=distro1,
                repo_name=book_name
            )
            # find base jobs
            if "base" in book:
                book_base = book["base"] if isinstance(book["base"], list) else [book["base"]]
                BASE_JOB = ", ".join([
                    distrosync_job_name(distro2, distro1, b) for b in book_base
                ])
            else:
                BASE_JOB = ""

            # create job by updating the template fields
            job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
            params = {
                "REPO_ORIGIN": book_origin,
                "REPO_NAME": book_name,
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
        "Statistics: Total books: {:d}; Total jobs: {:d}; Cache[Hits]: {:d}; Cache[Misses]: {:d}".format(
            stats["num_books"], stats["num_jobs"], stats["cache"]["hits"], stats["cache"]["misses"]
        )
    )
    logger.info("Done!")


def bookbuild_job_name(distro, repo_name):
    return "Book Build - {:s} - {:s}".format(distro, repo_name)


def automerge_job_name(from_branch, into_branch, repo_name):
    return "Git Automerge - Book - {:s} -> {:s} - {:s}".format(from_branch, into_branch, repo_name)


def stagesync_job_name(from_branch, to_branch, repo_name):
    return "Stage Sync - Book - {:s} >= {:s} - {:s}".format(from_branch, to_branch, repo_name)


def distrosync_job_name(from_branch, to_branch, repo_name):
    return "Distro Sync - Book - {:s} >= {:s} - {:s}".format(from_branch, to_branch, repo_name)


if __name__ == "__main__":
    main()

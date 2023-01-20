#!/usr/bin/env python3
import argparse
import json
import logging
import os

logging.basicConfig()
logger = logging.getLogger("jobs-generator")
logger.setLevel(logging.INFO)

WEBCHECK_TEMPLATE_JOB = "__webcheck_template__"
DEFAULT_TIMEOUT_MINUTES = 1
DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:60.0) Gecko/20100101 Firefox/81.0"


def main():
    # configure arguments
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--jobsdir",
        required=True,
        help="Directory containing the final jobs"
    )
    parser.add_argument(
        "--websites",
        required=True,
        help="File containing the list of websites to check",
    )
    parser.add_argument(
        "--labels",
        required=True,
        help="Comma-separated list of job labels to filter by",
    )
    parsed, _ = parser.parse_known_args()
    # ---
    parsed.jobsdir = os.path.abspath(parsed.jobsdir)
    # check if the destination directory exists
    if not os.path.exists(parsed.jobsdir):
        logger.error('The path "{:s}" does not exist.'.format(parsed.jobsdir))
        exit(1)
    # get arguments
    labels = set(parsed.labels.strip().strip(",").strip().split(","))
    # read list of websites
    with open(parsed.websites, "r") as fin:
        websites = json.load(fin)
    # load template jobs
    # - Webcheck job template
    webcheck_template_config_file = os.path.join(
        parsed.jobsdir, WEBCHECK_TEMPLATE_JOB, "config.xml.template"
    )
    with open(webcheck_template_config_file, "rt") as fin:
        webcheck_template_config = fin.read()
    # check which configurations are valid
    stats = {"num_jobs": 0, "num_websites": len(websites)}
    logger.info("Found {:d} websites.".format(len(websites)))

    # store things to write
    jobs_to_write = {}
    # ---
    for website in websites:
        logger.info("Analyzing [{:s}]".format(website["name"]))
        # must have a whitelisted label
        if len(labels.intersection(website["labels"])) <= 0:
            continue
        # website info
        website_name = website["name"]
        website_url = website["url"]
        website_timeout = website.get("timeout", DEFAULT_TIMEOUT_MINUTES)

        # create job name
        jname = webcheck_job_name(website_name)
        # create job by updating the template fields
        job_config_path = os.path.join(parsed.jobsdir, jname, "config.xml")
        params = {
            "NAME": website_name,
            "URL": website_url,
            "USER_AGENT": DEFAULT_USER_AGENT,
            "TIMEOUT_MINUTES": website_timeout,
        }
        config = webcheck_template_config.format(**params)

        # write job to disk
        os.makedirs(os.path.dirname(job_config_path))
        with open(job_config_path, "wt") as fout:
            fout.write(config)
        stats["num_jobs"] += 1

    # print out stats
    logger.info(
        "Statistics: Total websites: {:d}; Total jobs: {:d}".format(stats["num_websites"], stats["num_jobs"])
    )
    logger.info("Done!")


def webcheck_job_name(website_name):
    return "Webcheck - {:s}".format(website_name)


if __name__ == "__main__":
    main()

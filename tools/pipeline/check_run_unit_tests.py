#!/usr/bin/env python
# -*- coding: utf-8 -*-

import requests
import json
import argparse
import sys
from pathlib import Path
import re

import base64


def get_pull_request_information(args):
    url = rf"https://api.bitbucket.org/2.0/repositories/{args.workspace}/{args.repo_slug}/pullrequests/{args.pull_request_id}"
    bitbucket_username = "fredericodamianltrace"
    app_password = "xvaw8rDXDNpZPyV3GnEJ"
    headers = {
        "Accept": "application/json",
    }

    response = requests.request("GET", url, headers=headers, auth=(f"{bitbucket_username}", f"{app_password}"))
    response_json = json.loads(response.text)

    return filter_interest_data(response_json)


def filter_interest_data(json_data):
    # Title info
    title = json_data["title"]

    # Opened tasks info
    has_opened_tasks = int(json_data["task_count"]) > 0

    # Approval info
    has_approval = False
    participants = json_data["participants"]
    if len(participants) > 0:
        approvals = [participant["approved"] for participant in participants]
        has_approval = any(approvals)

    params = {"title": title, "has_approval": has_approval, "has_opened_tasks": has_opened_tasks}

    return params


def should_run_unit_test(args):
    pull_request_info = get_pull_request_information(args)
    should_run_test = True
    # Check for valid title
    if re.search(r"(\bWIP\b|\bwip\b|\bDRAFT\b|\bdraft\b)", pull_request_info["title"]):
        print("Tests should not be runned because title says its a WIP pull request.")
        should_run_test = False

    # Check at least one approval rule
    if not pull_request_info["has_approval"]:
        print("Tests should not be runned because the pull requests doesn't have any approval.")
        should_run_test = False

    # Check for opened tasks
    if pull_request_info["has_opened_tasks"] is True:
        print("Tests should not be runned because it has opened tasks.")
        should_run_test = False

    return should_run_test


def create_flag_file(storage_path):
    file = Path(storage_path) / ".run_test_flag"
    if file.is_file():
        file.unlink()

    with open(file, "w") as f:
        f.write("Run test")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Script to check if bitbucket pipeline should run the unit tests.")
    parser.add_argument("--pull_request_id", type=int, dest="pull_request_id", default=None)
    parser.add_argument("--repo_slug", type=str, dest="repo_slug", default=None)
    parser.add_argument("--workspace", type=str, dest="workspace", default=None)
    parser.add_argument("--storage_path", type=str, dest="storage_path", default="")

    args = parser.parse_args()
    if args.pull_request_id is None or args.repo_slug is None or args.workspace is None:
        print("Some required arguments are missing")
        sys.exit(1)

    if not should_run_unit_test(args):
        sys.exit(0)

    # Create flag if needs to run the unit test step from pipeline
    create_flag_file(args.storage_path)
    sys.exit(0)

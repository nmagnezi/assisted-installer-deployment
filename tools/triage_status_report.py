#!/usr/bin/env python3
import argparse
import dataclasses
import json
import os
import sys
from typing import List

import consts
import jira
import requests

FILTER_ID = 12380672
MISSING_VALUE = "<MISSING>"


@dataclasses.dataclass(order=True)
class IssueData:
    email_domain: str
    user: str
    key: str
    url: str
    features: List[str]

    def __post_init__(self):
        for field, value in self.__dict__.items():
            if value is None:
                if field == "features":
                    self.features = [MISSING_VALUE]
                else:
                    setattr(self, field, MISSING_VALUE)


def _parse_issue_data(issue):
    key = issue.key
    url = issue.permalink()
    user = issue.raw["fields"]["customfield_12319044"]
    email_domain = issue.raw["fields"]["customfield_12319045"]

    features = [label.replace("FEATURE-", "") for label in issue.raw["fields"]["labels"] if "FEATURE" in label]

    # filtering some non-important "features"
    features = [
        feature
        for feature in features
        if feature
        not in (
            "Requested-hostname",
            "Requsted-hostname",  # leaving the value with the typo for backwards compatibility
            "NetworkType",
        )
    ]

    return IssueData(key=key, url=url, user=user, email_domain=email_domain, features=features)


def _post_message(webhook, text):
    if webhook is None:
        # dry-run mode, just printing it raw
        print(text)
    else:
        response = requests.post(webhook, data=json.dumps({"text": text}), headers={"Content-type": "application/json"})
        response.raise_for_status()

        print("Message sent successfully!")


def triage_status_report(jira_client, filter_id, webhook):
    jira_filter = jira_client.filter(filter_id)
    jira_issues = jira_client.search_issues(jira_filter.jql)

    filter_url = jira_filter.viewUrl

    # Temporary focus
    ocp_4_12 = "https://issues.redhat.com/issues/?jql=project%20%3D%20AI-Triage%20AND%20component%20%3D%20Cloud-Triage%20AND%20created%20%3E%3D%20-7d%20AND%20affectedVersion%20%3D%20%22OpenShift%204.12%22%20ORDER%20BY%20key%20DESC"
    issues = []
    errors = []
    for issue in jira_issues:
        try:
            issues.append(_parse_issue_data(issue))
        except ValueError as e:
            errors.append((issue, e))

    if errors:
        for issue, e in errors:
            print(f"Failed parsing {issue}, error: {e}", file=sys.stderr)

        raise RuntimeError(f"Failed parsing all jira issues. Had {len(errors)} errors")

    text = f"There are <{filter_url}|{len(jira_issues)} new triage tickets> but please focus on <{ocp_4_12}|these> from the past week because we had a low success rate with 4.12 clusters recently\n"

    table = ""
    for issue in sorted(issues):
        table += f"<{issue.url}|{issue.key}>   {issue.user:<15} {issue.email_domain:<15} {issue.features}\n"

    if table:
        text += "```{}```".format(table)

    _post_message(webhook, text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--jira-access-token",
        default=os.environ.get("JIRA_ACCESS_TOKEN"),
        required=False,
        help="PAT (personal access token) for accessing Jira",
    )
    parser.add_argument(
        "--webhook",
        default=os.environ.get("WEBHOOK"),
        help="Slack channel url to post information. Not specifying implies dry-run",
    )
    parser.add_argument("--filter-id", default=FILTER_ID, help="Jira filter id")
    args = parser.parse_args()

    client = jira.JIRA(consts.JIRA_SERVER, token_auth=args.jira_access_token, validate=True)

    triage_status_report(client, args.filter_id, args.webhook)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Validate release provenance and staging evidence; no deployment capability."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import release_deployment as release

REQUIRED_TESTS = {"preflight", "stale staging cleanup", "resource preflight",
                  "Blue setup and synthetic database", "Blue schema and application",
                  "candidate schema migration and Blue compatibility",
                  "Green preparation and health", "promotion and Green route",
                  "rollback and Blue health", "scoped cleanup"}


class EvidenceError(Exception):
    pass


def require(ok, message):
    if not ok:
        raise EvidenceError(message)


def api(path):
    result = subprocess.run(("gh", "api", path), capture_output=True, text=True)
    require(result.returncode == 0, "GitHub API unavailable")
    return json.loads(result.stdout)


def release_run(repository, run_id):
    require(re.fullmatch(r"[0-9]+", run_id), "invalid release run ID")
    data = api(f"repos/{repository}/actions/runs/{run_id}")
    require(data.get("name") == "Release images" and
            data.get("path") == ".github/workflows/release.yml" and
            data.get("event") == "push" and data.get("conclusion") == "success" and
            data.get("head_repository", {}).get("full_name") == repository and
            re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", data.get("head_branch", "")),
            "release run is not a successful trusted tag build")
    return data


def validate_release_run(repository, run_id, directory):
    metadata = release_run(repository, run_id)
    paths = list(Path(directory).rglob("release-manifest.json"))
    require(len(paths) == 1, "release artifact must contain exactly one manifest")
    manifest, refs = release.manifest(paths[0])
    require(manifest["source_commit"] == metadata["head_sha"] and
            manifest["version"] == metadata["head_branch"] and
            manifest.get("workflow_run") == metadata["html_url"],
            "release manifest does not match successful workflow run")
    target = Path(directory) / "release-manifest.json"
    if paths[0] != target:
        target.write_bytes(paths[0].read_bytes())
    return manifest, refs


def validate_report(report, *, blue, green, controller_sha, max_age_hours=72):
    require(report.get("overall") == "PASS" and report.get("mode") == "release",
            "successful release-mode staging evidence required")
    require(report.get("controller_commit") == controller_sha,
            "deployment-controller commit mismatch")
    require(report.get("promotion") == "PASS" and report.get("rollback") == "PASS" and
            report.get("schema_compatibility", {}).get("result") == "PASS" and
            REQUIRED_TESTS <= report.get("tests", {}).keys() and
            all(value == "PASS" for value in report.get("tests", {}).values()),
            "staging evidence has failed or missing checks")
    require(re.fullmatch(r"[0-9]+-[0-9]+", report.get("run_id", "")),
            "invalid staging run identifier")
    completed = dt.datetime.fromisoformat(report["completed_at"])
    age = dt.datetime.now(dt.timezone.utc) - completed
    require(dt.timedelta(0) <= age <= dt.timedelta(hours=max_age_hours), "staging evidence is stale")
    for color, expected in (("blue", blue), ("green", green)):
        actual = report.get("releases", {}).get(color, {})
        require(actual.get("version") == expected["version"] and
                actual.get("source_commit") == expected["source_commit"] and
                all(actual.get("images", {}).get(s, {}).get("digest") == expected["images"][s]["digest"]
                    for s in ("backend", "frontend")),
                f"{color} release digest or identity mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    runs = sub.add_parser("validate-release-runs")
    for name in ("repository", "blue-run", "green-run", "blue-dir", "green-dir", "mode"):
        runs.add_argument("--" + name, required=True)
    args = parser.parse_args()
    try:
        require(args.repository == "Mafunamiii/Cashbook-mafunami", "wrong repository")
        require(args.mode in ("infrastructure", "release"), "invalid validation mode")
        blue, blue_refs = validate_release_run(args.repository, args.blue_run, args.blue_dir)
        green, green_refs = validate_release_run(args.repository, args.green_run, args.green_dir)
        if args.mode == "infrastructure":
            require(args.blue_run == args.green_run and blue_refs == green_refs,
                    "infrastructure mode requires the same release run")
        else:
            require(args.blue_run != args.green_run and blue_refs != green_refs,
                    "release mode requires distinct release digests")
        return 0
    except (EvidenceError, release.SafetyError, ValueError, KeyError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

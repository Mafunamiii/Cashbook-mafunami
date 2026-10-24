#!/usr/bin/env python3
"""On-demand, staging-only release rehearsal. No production command is exposed."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys

import bluegreen_deployment as bg
import release_deployment as legacy

ROOT = Path(__file__).resolve().parent.parent
CONTAINERS = {f"namicash-bg-stage-{part}-{service}": (f"namicash-bg-stage-{part}", service)
              for part, services in (("blue", ("backend", "frontend")),
                                     ("green", ("backend", "frontend")),
                                     ("db", ("db",)), ("gateway", ("caddy",)))
              for service in services}
NETWORKS = ("namicash-bg-stage-database", "namicash-bg-stage-gateway",
            "namicash-bg-stage-blue_app", "namicash-bg-stage-green_app")
VOLUME = "namicash-bg-stage-postgres-data"


def need(condition, message):
    if not condition:
        raise bg.Error(message)


def run(*args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
    except OSError:
        raise bg.Error(f"required command unavailable: {args[0]}") from None
    need(result.returncode == 0, f"{args[0]} command failed (exit {result.returncode})")
    return result.stdout.strip()


def docker_inspect(kind, name):
    result = subprocess.run(("docker", kind, "inspect", name), capture_output=True, text=True)
    if result.returncode:
        return None
    data = json.loads(result.stdout)
    need(len(data) == 1 and data[0].get("Name", name).lstrip("/") == name,
         f"unexpected {kind} identity: {name}")
    return data[0]


def check_ref(ref):
    need(ref == "refs/heads/main", "staging workflow requires trusted main ref")


def preflight(controller):
    need(platform.machine() == "x86_64", "staging host must be amd64")
    need(shutil.which("docker") is not None, "Docker CLI missing")
    need(os.environ.get("DOCKER_HOST", "") in ("", "unix:///var/run/docker.sock") and
         os.environ.get("DOCKER_CONTEXT", "") in ("", "default"),
         "remote Docker endpoint forbidden for staging")
    need(run("docker", "context", "show") == "default" and
         run("docker", "context", "inspect", "default", "--format", "{{.Endpoints.docker.Host}}") ==
         "unix:///var/run/docker.sock", "staging must use local Docker socket")
    run("docker", "compose", "version")
    run("docker", "info", "--format", "{{.ServerVersion}}")
    need(not any(docker_inspect("network", name) for name in
                 ("namicash-db-access", "namicash-gateway", "cashbook-mafunami_default")),
         "production Docker network present on staging host")
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 18091))
        except OSError:
            need(docker_inspect("container", controller.gateway_container) is not None,
                 "staging gateway port occupied by another process")
    return True


def cleanup(controller, report_dir):
    """Only remove resources with exact staging names and Compose identity labels."""
    failures = []
    for name, (project, service) in CONTAINERS.items():
        container_name = name + "-1"
        data = docker_inspect("container", container_name)
        if data is None:
            continue
        labels = data.get("Config", {}).get("Labels") or {}
        need(labels.get("com.docker.compose.project") == project and
             labels.get("com.docker.compose.service") == service,
             f"refusing to remove unexpected container: {container_name}")
        log = subprocess.run(("docker", "logs", container_name), capture_output=True, text=True)
        output = (log.stdout + log.stderr)[-200000:]
        if controller.env_file.is_file():
            for line in controller.env_file.read_text().splitlines():
                if line.startswith(("POSTGRES_PASSWORD=", "DATABASE_URL=")) and "=" in line:
                    secret = line.split("=", 1)[1]
                    if secret:
                        output = output.replace(secret, "[REDACTED]")
            password = re.search(r"^POSTGRES_PASSWORD=(.+)$", controller.env_file.read_text(), re.MULTILINE)
            if password:
                output = output.replace(password[1], "[REDACTED]")
        (report_dir / f"{container_name}.log").write_text(output)
        try:
            run("docker", "rm", "-f", container_name)
        except bg.Error as exc:
            failures.append(str(exc))
    for name in NETWORKS:
        data = docker_inspect("network", name)
        if data is None:
            continue
        labels = data.get("Labels") or {}
        if name.endswith("_app"):
            need(labels.get("com.docker.compose.project") == name[:-4],
                 f"refusing to remove unrelated network: {name}")
        else:
            need(labels.get("org.namicash.scope") == "bluegreen-staging",
                 f"refusing to remove unrelated network: {name}")
        need(not data.get("Containers"), f"staging network still has containers: {name}")
        try:
            run("docker", "network", "rm", name)
        except bg.Error as exc:
            failures.append(str(exc))
    data = docker_inspect("volume", VOLUME)
    if data is not None:
        labels = data.get("Labels") or {}
        need(labels.get("com.docker.compose.project") == "namicash-bg-stage-db" and
             labels.get("com.docker.compose.volume") == "staging-db",
             "refusing to remove volume without staging Compose identity")
        try:
            run("docker", "volume", "rm", VOLUME)
        except bg.Error as exc:
            failures.append(str(exc))
    need(not failures, "; ".join(failures))
    for path in (controller.state_path, controller.state_dir / "events.jsonl",
                 controller.state_dir / "previous-route.caddy", controller.gateway_file,
                 controller.snippet, *(controller.state_dir / "nginx" / f"{c}.conf" for c in bg.COLORS)):
        path.unlink(missing_ok=True)


def write_report(report, directory):
    directory.mkdir(parents=True, exist_ok=True)
    report["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    report["overall"] = "PASS" if all(v == "PASS" for v in report["tests"].values()) else "FAIL"
    (directory / "staging-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = ["# NamiCash staging validation", "", f"Overall: **{report['overall']}**",
             f"Mode: {report['mode']}", f"Run: {report['run_id']}",
             f"Controller commit: {report['controller_commit']}",
             f"Completed: {report['completed_at']}", "",
             "| Check | Result |", "| --- | --- |"]
    lines += [f"| {key} | {value} |" for key, value in report["tests"].items()]
    lines += ["", "## Releases", ""]
    for color, data in report["releases"].items():
        lines += [f"- {color}: {data['version']} at {data['source_commit']}",
                  f"  - backend: {data['images']['backend']['digest']}",
                  f"  - frontend: {data['images']['frontend']['digest']}"]
    if report.get("error"):
        lines += ["", f"Failure: {report['error']}"]
    (directory / "staging-report.md").write_text("\n".join(lines) + "\n")


def execute(args):
    check_ref(args.trusted_ref)
    need(re.fullmatch(r"[0-9]+-[0-9]+", args.run_id), "invalid run identifier")
    blue, blue_refs = legacy.manifest(args.blue_manifest)
    green, green_refs = legacy.manifest(args.candidate_manifest)
    if args.mode == "infrastructure":
        need(blue_refs == green_refs and blue["source_commit"] == green["source_commit"],
             "infrastructure mode requires the same release in both colors")
    else:
        need(blue_refs != green_refs,
             "release mode requires distinct actual releases")
    controller = bg.Controller(argparse.Namespace(mode="staging", state_dir=args.state_dir,
                             env_file=args.env_file, managed_dir=None, gateway_file=None,
                             schema_attestation=None))
    controller.env_guard()
    state_dir = controller.state_dir
    need(not state_dir.is_symlink() and
         not state_dir.resolve().is_relative_to(Path("/home/jahn/namicash-releases")) and
         not state_dir.resolve().is_relative_to(Path("/home/jahn/caddy-gateway")),
         "unsafe staging state directory")
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = state_dir / ".staging-validation-owner"
    if marker.exists():
        need(not marker.is_symlink() and marker.read_text() == "NamiCash off-host staging\n",
             "staging state ownership marker mismatch")
    else:
        need(not any(state_dir.iterdir()), "unmarked staging state directory is not empty")
        marker.write_text("NamiCash off-host staging\n")
    report_dir = Path(args.report_dir).resolve()
    need(not report_dir.is_relative_to(controller.state_dir.resolve()),
         "report directory must survive staging cleanup")
    report = {"schema": 1, "mode": args.mode, "run_id": args.run_id,
              "controller_commit": run("git", "rev-parse", "HEAD"),
              "releases": {"blue": blue, "green": green}, "tests": {},
              "promotion": "NOT_RUN", "rollback": "NOT_RUN", "schema_compatibility": "NOT_RUN"}
    report_dir.mkdir(parents=True, exist_ok=True)
    step = "preflight"
    try:
        preflight(controller)
        report["tests"][step] = "PASS"
        step = "stale staging cleanup"
        cleanup(controller, report_dir)
        report["tests"][step] = "PASS"
        step = "resource preflight"
        controller.resource_check(staging_additional_mib=bg.STAGING_SETUP_MIB)
        report["tests"][step] = "PASS"
        def command(name, manifest=None):
            arguments = argparse.Namespace(command=name, manifest=manifest, execute=True,
                                           inject_failure=None)
            return controller.execute(arguments)
        step = "Blue setup and synthetic database"
        command("staging-setup", args.blue_manifest)
        command("bootstrap", args.blue_manifest)
        report["tests"][step] = "PASS"
        step = "Blue schema and application"
        need(controller.schema_revision() == controller.image_schema_head(blue_refs["backend"]),
             "Blue schema mismatch")
        controller.slot_check("blue", controller.load()["slots"]["blue"])
        controller.route_probe("blue")
        report["tests"][step] = "PASS"
        step = "candidate schema migration and Blue compatibility"
        command("prepare", args.candidate_manifest)
        controller.slot_check("blue", controller.load()["slots"]["blue"])
        controller.route_probe("blue")
        report["schema_compatibility"] = {"result": "PASS", "revision": controller.schema_revision(),
                                          "blue_head": controller.image_schema_head(blue_refs["backend"]),
                                          "green_head": controller.image_schema_head(green_refs["backend"])}
        report["tests"][step] = "PASS"
        step = "Green preparation and health"
        command("stage", args.candidate_manifest)
        command("verify")
        report["tests"][step] = "PASS"
        step = "promotion and Green route"
        command("promote")
        controller.route_probe("green")
        report["promotion"] = "PASS"
        report["tests"][step] = "PASS"
        step = "rollback and Blue health"
        command("rollback")
        controller.route_probe("blue")
        controller.db_identity()
        need(controller.schema_revision() == report["schema_compatibility"]["revision"],
             "database schema changed during rollback")
        controller.slot_check("blue", controller.load()["slots"]["blue"])
        report["rollback"] = "PASS"
        report["tests"][step] = "PASS"
    except (bg.Error, legacy.SafetyError, OSError, ValueError) as exc:
        report["tests"][step] = "FAIL"
        report["error"] = str(exc)
    finally:
        try:
            cleanup(controller, report_dir)
            report["tests"]["scoped cleanup"] = "PASS"
        except (bg.Error, OSError, ValueError) as exc:
            report["tests"]["scoped cleanup"] = "FAIL"
            report["cleanup_error"] = str(exc)
        write_report(report, report_dir)
    return 0 if report["overall"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("infrastructure", "release"), required=True)
    parser.add_argument("--blue-manifest", required=True)
    parser.add_argument("--candidate-manifest", required=True)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--trusted-ref", required=True)
    args = parser.parse_args()
    try:
        return execute(args)
    except (bg.Error, legacy.SafetyError, OSError, ValueError) as exc:
        write_report({"schema": 1, "mode": args.mode, "run_id": args.run_id,
                      "controller_commit": "unverified", "releases": {},
                      "tests": {"input validation": "FAIL"}, "promotion": "NOT_RUN",
                      "rollback": "NOT_RUN", "schema_compatibility": "NOT_RUN",
                      "error": str(exc)}, Path(args.report_dir))
        print(f"STOP: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

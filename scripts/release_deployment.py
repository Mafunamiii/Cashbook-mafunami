#!/usr/bin/env python3
"""Digest-pinned application deployment; no database or migration operations."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
REPOS = {s: f"ghcr.io/mafunamiii/namicash-{s}" for s in ("backend", "frontend")}
PROJECT = "cashbook-mafunami"
BACKEND_COMMAND = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips"]
PORTS = {"backend": {("127.0.0.1", "8002", "8000")}, "frontend": {
    ("127.0.0.1", "3004", "8080"), ("192.168.2.2", "3004", "8080"),
    ("100.93.39.106", "3004", "8080")}}
STATE_DIR = Path(os.environ.get("NAMI_DEPLOY_STATE_DIR", "/home/jahn/namicash-releases/deployment-state"))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/home/jahn/backups/namicash/postgres"))
RCLONE_CONFIG = os.environ.get("RCLONE_CONFIG", "/home/jahn/.config/rclone/rclone.conf")
REMOTE = "gdrive-crypt:namicash/postgres"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
VERSION = re.compile(r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
ARCHIVE = re.compile(r"namicash-postgres-([0-9]{8}T[0-9]{6}Z)\.dump\.gz\Z")


class SafetyError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise SafetyError(message)


def run(args, *, env=None, input=None, binary=False):
    try:
        p = subprocess.run(args, env=env, input=input, capture_output=True, check=False,
                           text=not binary)
    except OSError as exc:
        raise SafetyError(f"{args[0]} unavailable: {exc.strerror}") from None
    # Never echo command output: Compose/Docker errors may contain environment values.
    require(p.returncode == 0, f"{args[0]} {args[1] if len(args)>1 else ''} failed (exit {p.returncode})")
    return p.stdout


def manifest(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise SafetyError("release manifest is missing or malformed") from None
    require(isinstance(data, dict) and VERSION.fullmatch(str(data.get("version", ""))), "invalid release version")
    require(re.fullmatch(r"[0-9a-f]{40}", str(data.get("source_commit", ""))) is not None,
            "invalid source commit")
    images = data.get("images")
    require(isinstance(images, dict) and set(images) == set(REPOS), "manifest must contain backend and frontend images")
    refs = {}
    for service, repo in REPOS.items():
        item = images[service]
        require(isinstance(item, dict), f"malformed {service} image")
        require(item.get("name") == repo, f"wrong {service} image repository")
        require(isinstance(item.get("digest"), str) and DIGEST.fullmatch(item["digest"]),
                f"invalid {service} SHA-256 digest")
        require(item.get("architecture") == "linux/amd64", f"unsupported {service} platform")
        refs[service] = repo + "@" + item["digest"]
    return data, refs


def validate_refs(refs, *, allow_image_id=False):
    for service, repo in REPOS.items():
        ref = refs.get(service)
        valid_ghcr = isinstance(ref, str) and ref.startswith(repo + "@") and DIGEST.fullmatch(ref[len(repo)+1:])
        valid_id = allow_image_id and isinstance(ref, str) and DIGEST.fullmatch(ref)
        require(valid_ghcr or valid_id, f"{service} must use an immutable digest or verified image ID")


def docker_json(*args):
    try:
        return json.loads(run(["docker", *args]))
    except (ValueError, TypeError):
        raise SafetyError("malformed Docker response") from None


def inspect_container(service, *, require_running=True):
    name = f"{PROJECT}-{service}-1"
    data = docker_json("inspect", "--type", "container", name)
    require(isinstance(data, list) and len(data) == 1, f"missing {service} container")
    c = data[0]
    labels = c["Config"].get("Labels") or {}
    require(c["Name"] == "/" + name and labels.get("com.docker.compose.project") == PROJECT
            and labels.get("com.docker.compose.service") == service,
            f"unexpected {service} container identity")
    if require_running:
        require(c["State"].get("Running") is True, f"{service} is not running")
    return c


def health(c, service):
    require(c["State"].get("Health", {}).get("Status") == "healthy", f"{service} is not healthy")


def port_set(c):
    result = set()
    ports = c["NetworkSettings"].get("Ports") or c.get("HostConfig", {}).get("PortBindings") or {}
    for target, entries in ports.items():
        for entry in entries or []:
            result.add((entry["HostIp"], entry["HostPort"], target.split("/")[0]))
    return result


def identity(containers, *, allow_stopped_apps=False):
    network = docker_json("network", "inspect", f"{PROJECT}_default")
    require(len(network) == 1 and network[0]["Name"] == f"{PROJECT}_default", "production network missing")
    net_id = network[0]["Id"]
    for service, c in containers.items():
        if allow_stopped_apps and service != "db" and not c["State"].get("Running"):
            continue
        nets = c["NetworkSettings"]["Networks"]
        require(f"{PROJECT}_default" in nets and nets[f"{PROJECT}_default"]["NetworkID"] == net_id,
                f"{service} network identity changed")
    volume = docker_json("volume", "inspect", "cashbook-postgres-production-data")
    require(len(volume) == 1 and volume[0]["Name"] == "cashbook-postgres-production-data",
            "PostgreSQL volume missing")
    mounts = [m for m in containers["db"]["Mounts"] if m.get("Destination") == "/var/lib/postgresql/data"]
    require(len(mounts) == 1 and mounts[0].get("Type") == "volume"
            and mounts[0].get("Name") == "cashbook-postgres-production-data",
            "unexpected PostgreSQL volume")
    for service in PORTS:
        require(port_set(containers[service]) == PORTS[service], f"{service} port bindings changed")
    return {"db_id": containers["db"]["Id"], "network_id": net_id,
            "volume": volume[0]["Name"], "ports": {s: sorted(PORTS[s]) for s in PORTS}}


def compose_env(refs):
    return {**os.environ, "BACKEND_IMAGE": refs["backend"], "FRONTEND_IMAGE": refs["frontend"]}


def compose_config(file, refs):
    return json.loads(run(["docker", "compose", "-p", PROJECT, "--env-file", str(ROOT / ".env.prod"),
                           "-f", str(ROOT / file), "config", "--format", "json"], env=compose_env(refs)))


def validate_compose(refs):
    require((ROOT / ".env.prod").is_file(), "production .env.prod is unavailable")
    base = compose_config("compose.production.yaml", refs)
    target = compose_config("compose.ghcr.yaml", refs)
    require(set(target["services"]) == {"db", "backend", "frontend"}, "unexpected GHCR services")
    require(target["services"]["db"] == base["services"]["db"], "database Compose configuration changed")
    for service in REPOS:
        a, b = base["services"][service], target["services"][service]
        require("build" not in b and b.get("image") == refs[service], f"unsafe {service} build/image configuration")
        if service == "backend":
            require(b.get("command") == BACKEND_COMMAND + [b["environment"]["FORWARDED_ALLOW_IPS"]],
                    "backend must start without running migrations")
        require({k: v for k, v in a.items() if k not in ("build", "command")} ==
                {k: v for k, v in b.items() if k not in ("image", "command")},
                f"{service} Compose behavior changed")
        require({(p.get("host_ip", ""), str(p["published"]), str(p["target"])) for p in b["ports"]}
                == PORTS[service], f"{service} configured ports changed")
    require(target.get("volumes") == base.get("volumes"), "Compose volume identity changed")
    return target


def image_id(ref, *, remote=False):
    if remote:
        info = docker_json("manifest", "inspect", ref)
        manifests = info.get("manifests")
        if manifests:
            require(any(m.get("platform", {}).get("os") == "linux" and
                        m.get("platform", {}).get("architecture") == "amd64" for m in manifests),
                    f"image lacks linux/amd64: {ref}")
        else:
            cfg = info.get("config", {})
            # Single-platform registry manifests cannot reveal architecture;
            # local image inspection after pull provides the authoritative check.
            require(bool(cfg), f"unrecognized image manifest: {ref}")
        return None
    images = docker_json("image", "inspect", ref)
    require(len(images) == 1 and images[0].get("Os") == "linux" and images[0].get("Architecture") == "amd64",
            f"image unavailable or wrong platform: {ref}")
    return images[0]["Id"]


def previous_refs(containers, supplied):
    refs = {}
    for service in REPOS:
        candidate = supplied.get(service)
        if not candidate:
            raw = containers[service]["Config"].get("Image", "")
            candidates = [raw] + (docker_json("image", "inspect", containers[service]["Image"])[0].get("RepoDigests") or [])
            candidate = next((r for r in candidates if r.startswith(REPOS[service] + "@")
                              and DIGEST.fullmatch(r[len(REPOS[service])+1:])), None)
        require(candidate, f"no immutable previous {service} reference; supply --previous-{service}")
        refs[service] = candidate
    validate_refs(refs)
    for service in REPOS:
        require(image_id(refs[service]) == containers[service]["Image"],
                f"previous {service} digest does not match running image")
    return refs


def backup_check():
    files = sorted(BACKUP_DIR.glob("namicash-postgres-*.dump.gz"), reverse=True)
    now = dt.datetime.now(dt.timezone.utc)
    for archive in files:
        match = ARCHIVE.fullmatch(archive.name)
        if not match:
            continue
        try:
            stamp = dt.datetime.strptime(match[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if not dt.timedelta(0) <= now - stamp <= dt.timedelta(hours=48):
            continue
        sidecar = archive.with_name(archive.name + ".sha256")
        if not sidecar.is_file():
            continue
        local_hash = hashlib.sha256()
        with archive.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                local_hash.update(chunk)
        expected = f"{local_hash.hexdigest()}  {archive.name}"
        if sidecar.read_text().strip() != expected:
            continue
        run(["gzip", "-t", str(archive)])
        # Current cloud contents are verified byte for byte. Uploaded markers are ignored.
        remote_hash = hashlib.sha256()
        for suffix in ("", ".sha256"):
            try:
                p = subprocess.Popen(["rclone", "--config", RCLONE_CONFIG, "cat",
                                      f"{REMOTE}/{archive.name}{suffix}"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
            except OSError:
                raise SafetyError("off-site verification tool unavailable") from None
            if suffix:
                content = p.stdout.read(256)
                require(p.stdout.read(1) == b"" and p.wait() == 0 and content.decode().strip() == expected,
                        "off-site checksum unavailable or mismatched")
            else:
                for chunk in iter(lambda: p.stdout.read(1024 * 1024), b""):
                    remote_hash.update(chunk)
                require(p.wait() == 0 and remote_hash.hexdigest() == local_hash.hexdigest(),
                        "off-site backup unavailable or mismatched")
        return archive.name
    raise SafetyError("no verified local backup from the last 48 hours")


def preflight(refs, supplied, *, backups=True):
    validate_refs(refs)
    validate_compose(refs)
    run(["docker", "info", "--format", "{{.ServerVersion}}"])
    containers = {s: inspect_container(s) for s in ("db", "backend", "frontend")}
    health(containers["db"], "database")
    health(containers["backend"], "backend")
    health(containers["frontend"], "frontend")
    baseline = identity(containers)
    previous = previous_refs(containers, supplied)
    if backups:
        baseline["backup"] = backup_check()
    for ref in refs.values():
        image_id(ref, remote=True)
    return baseline, previous


def verify(refs, baseline=None):
    validate_refs(refs, allow_image_id=True)
    containers = {s: inspect_container(s) for s in ("db", "backend", "frontend")}
    for service, c in containers.items():
        health(c, service)
    current = identity(containers)
    if baseline:
        require(current["db_id"] == baseline["db_id"], "database container was replaced")
        require(current["network_id"] == baseline["network_id"], "network was replaced")
    for service in REPOS:
        require(containers[service]["Image"] == image_id(refs[service]),
                f"{service} image ID mismatch")
        require(containers[service]["Config"]["Image"] == refs[service],
                f"{service} container is not pinned to expected digest")
    return current


def wait_healthy(refs, baseline, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for service in REPOS:
            status = inspect_container(service)["State"].get("Health", {}).get("Status")
            require(status != "unhealthy", f"{service} became unhealthy")
        try:
            return verify(refs, baseline)
        except SafetyError:
            time.sleep(5)
    raise SafetyError("application health verification timed out")


def compose_up(refs, service):
    # --no-deps prevents Compose from starting or recreating db. Backend must
    # become healthy before frontend is replaced because it depends on backend.
    run(["docker", "compose", "-p", PROJECT, "--env-file", str(ROOT / ".env.prod"),
         "-f", str(ROOT / "compose.ghcr.yaml"), "up", "-d", "--no-deps", "--no-build",
         "--pull", "never", "--force-recreate", service], env=compose_env(refs))


def archive_path(service, ref):
    return STATE_DIR / "images" / f"{service}-{ref.split(':')[-1]}.tar"


def archive_valid(service, ref, expected_id):
    path = archive_path(service, ref)
    metadata = path.with_suffix(".json")
    if not path.is_file() or not metadata.is_file():
        return False
    try:
        info = json.loads(metadata.read_text())
        if info.get("reference") != ref or info.get("image_id") != expected_id:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == info.get("archive_sha256")
    except (OSError, ValueError):
        return False


def preserve_images(refs, containers):
    directory = STATE_DIR / "images"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for service, ref in refs.items():
        expected_id = containers[service]["Image"]
        if archive_valid(service, ref, expected_id):
            continue
        size = docker_json("image", "inspect", ref)[0].get("Size", 0)
        require(shutil.disk_usage(directory).free > max(size * 2, 1024**3),
                f"insufficient disk space to preserve {service} image")
        path = archive_path(service, ref)
        temp = path.with_name(path.name + f".tmp.{os.getpid()}")
        try:
            run(["docker", "save", "--output", str(temp), ref])
            digest = hashlib.sha256()
            with temp.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            os.replace(temp, path)
            path.with_suffix(".json").write_text(json.dumps({
                "reference": ref, "image_id": expected_id, "archive_sha256": digest.hexdigest()}))
        finally:
            temp.unlink(missing_ok=True)
        require(archive_valid(service, ref, expected_id), f"{service} image archive verification failed")


def rollback_ref(service, ghcr_ref, expected_id, execute):
    try:
        require(image_id(ghcr_ref) == expected_id, f"{service} previous image ID mismatch")
        return ghcr_ref
    except SafetyError:
        require(archive_valid(service, ghcr_ref, expected_id),
                f"{service} rollback image unavailable locally and archive invalid or missing")
        if execute:
            run(["docker", "load", "--input", str(archive_path(service, ghcr_ref))])
            require(image_id(expected_id) == expected_id, f"{service} restored archive image ID mismatch")
        return expected_id


def record(event):
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE_DIR / "history.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def lock():
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = (STATE_DIR / ".deploy.lock").open("a")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fd.close()
        raise SafetyError("another deployment or rollback holds the lock") from None
    return fd


def history():
    path = STATE_DIR / "history.jsonl"
    require(path.is_file(), "no deployment history")
    try:
        return [json.loads(line) for line in path.read_text().splitlines()]
    except (OSError, ValueError):
        raise SafetyError("deployment history is unreadable or malformed") from None


def latest_success():
    successes = [e for e in history() if e.get("outcome") == "success"]
    require(successes, "no recorded known-good deployment")
    return successes[-1]


def rollback_source():
    attempts = [e for e in history() if e.get("operation") == "deploy" and
                e.get("outcome") in ("success", "failed")]
    require(attempts, "no deployment with recorded previous images")
    return attempts[-1]


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    d = subs.add_parser("deploy")
    d.add_argument("--manifest", required=True)
    d.add_argument("--execute", action="store_true")
    d.add_argument("--previous-backend")
    d.add_argument("--previous-frontend")
    d.add_argument("--timeout", type=int, default=180)
    r = subs.add_parser("rollback")
    r.add_argument("--execute", action="store_true")
    r.add_argument("--timeout", type=int, default=180)
    v = subs.add_parser("verify")
    v.add_argument("--manifest")
    m = subs.add_parser("validate-manifest")
    m.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.command == "validate-manifest":
        data, refs = manifest(args.manifest)
        print(f"Valid release {data['version']}: linux/amd64 digest references")
        return
    if args.command == "verify":
        last = latest_success()
        refs = manifest(args.manifest)[1] if args.manifest else last["target"]
        require(refs == last["target"], "requested images differ from latest verified deployment")
        require(isinstance(last.get("baseline"), dict), "deployment baseline is missing")
        verify(refs, last["baseline"])
        print("Deployment verified: images, health, ports, database and network identity")
        return
    with lock():
        if args.command == "deploy":
            data, refs = manifest(args.manifest)
            supplied = {s: getattr(args, "previous_" + s) for s in REPOS}
            baseline, previous = preflight(refs, supplied)
            print(f"Preflight passed for {data['version']}; backup {baseline['backup']}")
            print("Plan: preserve previous image digests; replace backend, wait healthy; replace frontend, verify all identities")
            print("Database, migrations, network, ports and production environment are outside the deployment operation")
            if not args.execute:
                print("Dry run complete; no containers or images changed")
                return
            current = {s: inspect_container(s) for s in REPOS}
            preserve_images(previous, current)
            event = {"operation": "deploy", "version": data["version"], "target": refs,
                     "previous": previous, "previous_ids": {s: current[s]["Image"] for s in REPOS},
                     "baseline": baseline, "source_commit": data["source_commit"],
                     "started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "outcome": "started"}
        else:
            last = rollback_source()
            target = last["previous"]
            validate_refs(target)
            validate_compose(target)
            require(isinstance(last.get("previous_ids"), dict), "previous image IDs are missing from history")
            current = {s: inspect_container(s, require_running=(s == "db"))
                       for s in ("db", "backend", "frontend")}
            require(all(current[s]["Image"] == last["previous_ids"][s] or
                        current[s]["Config"]["Image"] == last["target"][s] for s in REPOS),
                    "running application does not match latest deployment attempt")
            require(any(current[s]["Image"] != last["previous_ids"][s] for s in REPOS),
                    "application already uses recorded previous images")
            baseline = last.get("baseline")
            require(isinstance(baseline, dict), "deployment baseline missing")
            now = identity(current, allow_stopped_apps=True)
            require(now["db_id"] == baseline["db_id"] and now["network_id"] == baseline["network_id"],
                    "database or network identity changed since deployment attempt")
            health(current["db"], "database")
            target = {s: rollback_ref(s, target[s],
                                      last["previous_ids"][s], args.execute) for s in REPOS}
            print("Plan: application-only rollback to recorded previous digests; database is not recovered or migrated")
            if not args.execute:
                print("Dry run complete; no containers or images changed")
                return
            refs = target
            previous = last["target"]
            event = {"operation": "rollback", "target": refs, "previous": previous,
                     "baseline": baseline, "started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "outcome": "started"}
        record(event)
        try:
            if args.command == "deploy":
                for ref in refs.values():
                    run(["docker", "pull", "--platform", "linux/amd64", ref])
                    image_id(ref)
                # Recheck database and network after potentially long pulls.
                after_pull = identity({s: inspect_container(s) for s in ("db", "backend", "frontend")})
                require(after_pull["db_id"] == baseline["db_id"] and
                        after_pull["network_id"] == baseline["network_id"],
                        "database or network identity changed during image pull")
            compose_up(refs, "backend")
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                c = inspect_container("backend")
                status = c["State"].get("Health", {}).get("Status")
                if status == "healthy" and c["Image"] == image_id(refs["backend"]):
                    break
                require(status != "unhealthy", "backend became unhealthy")
                time.sleep(5)
            else:
                raise SafetyError("backend health timed out")
            compose_up(refs, "frontend")
            wait_healthy(refs, baseline, args.timeout)
        except SafetyError as exc:
            event.update(outcome="failed", finished_at=dt.datetime.now(dt.timezone.utc).isoformat(), reason=str(exc))
            record(event)
            raise
        event.update(outcome="success", finished_at=dt.datetime.now(dt.timezone.utc).isoformat())
        record(event)
        print("Application deployment verified and recorded")


if __name__ == "__main__":
    try:
        main()
    except SafetyError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(1)

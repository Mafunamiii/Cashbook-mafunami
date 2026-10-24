#!/usr/bin/env python3
"""Opt-in blue/green controller. Existing single-environment deployment remains available."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.request
from urllib.parse import urlsplit

import release_deployment as legacy

ROOT = Path(__file__).resolve().parent.parent
COLORS = ("blue", "green")
IMPORT = "import /etc/caddy/managed/namicash.caddy"
ADMIN = "admin unix//run/caddy-admin.sock"
NGINX_UPSTREAM = "proxy_pass http://backend:8000;"
BACKEND_COMMAND = legacy.BACKEND_COMMAND
REQUIRED_MEMORY_MIB = 1536
REQUIRED_DISK_MIB = 2048
MAX_RUNNING_CONTAINERS = 24
# Staging setup adds DB (512), gateway (128), backend (512), frontend (256).
# Allow 256 MiB for Docker/process overhead and retain 768 MiB for the host.
STAGING_SETUP_MIB = 1408
STAGING_CANDIDATE_MIB = 768
STAGING_OVERHEAD_MIB = 256
STAGING_HOST_RESERVE_MIB = 768


class Error(legacy.SafetyError):
    pass


def need(ok, message):
    if not ok:
        raise Error(message)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        with tmp.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        tmp.unlink(missing_ok=True)


def safe_run(args, *, env=None):
    try:
        return legacy.run(args, env=env)
    except legacy.SafetyError as exc:
        # Docker may echo environment values. Only add labels derived from known
        # subcommands; never include arguments or captured output.
        if args[:2] == ["docker", "run"]:
            operation = "staging migration" if "upgrade" in args and "head" in args else "image schema inspection"
        elif args[:2] == ["docker", "compose"]:
            action = next((word for word in ("up", "stop", "config") if word in args), "operation")
            service = next((word for word in ("backend", "frontend", "db") if word in args), "stack")
            operation = f"container {action} {service}"
        elif args[:2] == ["docker", "exec"] and "caddy" in args:
            operation = "Caddy reload" if "reload" in args else "Caddy validation"
        elif args[:2] == ["docker", "pull"]:
            operation = "image pull"
        else:
            operation = "Docker operation"
        raise Error(f"{operation}: {exc}") from None


class Controller:
    def __init__(self, args):
        self.mode = args.mode
        self.staging = self.mode == "staging"
        default_state = ((ROOT / ".staging/bluegreen") if self.staging else
                         Path("/home/jahn/namicash-releases/deployment-state/bluegreen-production"))
        self.state_dir = Path(args.state_dir or os.environ.get("NAMI_BG_STATE_DIR") or default_state)
        self.env_file = Path(args.env_file or (ROOT / (".env.bluegreen.staging" if self.staging else ".env.prod")))
        self.managed_dir = Path(args.managed_dir or (self.state_dir / "managed" if self.staging else
                                                   "/home/jahn/caddy-gateway/managed"))
        self.gateway_file = Path(args.gateway_file or (self.state_dir / "Caddyfile" if self.staging else
                                                     "/home/jahn/caddy-gateway/Caddyfile"))
        self.gateway_container = "namicash-bg-stage-gateway-caddy-1" if self.staging else "caddy-gateway"
        self.gateway_url = "http://127.0.0.1:18091" if self.staging else "http://127.0.0.1:8091"
        self.gateway_network = "namicash-bg-stage-gateway" if self.staging else "namicash-gateway"
        self.db_network = "namicash-bg-stage-database" if self.staging else "namicash-db-access"
        self.db_container = "namicash-bg-stage-db-db-1" if self.staging else "cashbook-mafunami-db-1"
        self.host = "stage.namicash.invalid" if self.staging else "namicash.mafunami.me"
        self.attestation = Path(args.schema_attestation) if args.schema_attestation else None
        if self.staging:
            need(self.managed_dir.resolve() == (self.state_dir / "managed").resolve() and
                 self.gateway_file.resolve() == (self.state_dir / "Caddyfile").resolve(),
                 "staging gateway paths must remain inside staging state")
        else:
            need(self.managed_dir.resolve() == Path("/home/jahn/caddy-gateway/managed").resolve() and
                 self.gateway_file.resolve() == Path("/home/jahn/caddy-gateway/Caddyfile").resolve(),
                 "production gateway paths are fixed")

    def project(self, color):
        return f"namicash-bg-stage-{color}" if self.staging else f"namicash-{color}"

    def container_name(self, color, service, *, legacy_blue=False):
        if legacy_blue:
            return f"cashbook-mafunami-{service}-1"
        return f"{self.project(color)}-{service}-1"

    @property
    def state_path(self):
        return self.state_dir / "state.json"

    @property
    def snippet(self):
        return self.managed_dir / "namicash.caddy"

    def lock(self):
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = (self.state_dir / ".lock").open("a")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fd.close()
            raise Error("another blue/green operation holds the lock") from None
        return fd

    def load(self):
        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            raise Error("blue/green state missing or malformed; run bootstrap or restore state") from None
        need(state.get("schema") == 1 and state.get("mode") == self.mode and
             state.get("active") in COLORS and isinstance(state.get("slots"), dict),
             "invalid blue/green state")
        return state

    def save(self, state, action):
        state["updated_at"] = now()
        atomic(self.state_path, (json.dumps(state, sort_keys=True) + "\n").encode())
        with (self.state_dir / "events.jsonl").open("a") as stream:
            stream.write(json.dumps({"at": now(), "action": action, "active": state["active"],
                                     "phase": state.get("phase"), "slots": {
                                         c: {"version": v.get("version"), "status": v.get("status")}
                                         for c, v in state["slots"].items()},
                                     "refs": {c: v.get("refs") for c, v in state["slots"].items()}},
                                    sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def manifest(self, path):
        need(bool(path), "explicit release manifest required")
        return legacy.manifest(path)

    def inspect(self, name, *, running=True):
        data = legacy.docker_json("inspect", "--type", "container", name)
        need(isinstance(data, list) and len(data) == 1 and data[0].get("Name") == "/" + name,
             f"container identity missing: {name}")
        c = data[0]
        if running:
            need(c["State"].get("Running") is True, f"container not running: {name}")
        return c

    def network(self, name):
        result = legacy.docker_json("network", "inspect", name)
        need(len(result) == 1 and result[0].get("Name") == name, f"network missing: {name}")
        return result[0]

    def member(self, c, network, alias=None):
        entry = c["NetworkSettings"].get("Networks", {}).get(network)
        need(entry and entry.get("NetworkID") == self.network(network)["Id"],
             f"{c['Name']} is not on {network}")
        if alias:
            need(alias in (entry.get("Aliases") or []), f"{c['Name']} lacks {alias} alias")

    def baseline_check(self, state):
        need(self.db_identity() == state["baseline"]["db_id"], "database container changed since bootstrap")
        blue = state["slots"].get("blue")
        if blue and blue.get("kind") == "legacy" and blue.get("status") != "retired":
            need(self.slot_check("blue", blue) == state["baseline"]["blue_ids"],
                 "initial Blue production containers changed")

    def db_identity(self):
        db_net = self.network(self.db_network)
        need(db_net.get("Internal") is True, "database network must be internal")
        allowed = ({self.db_container} |
                   {self.container_name(color, "backend") for color in COLORS})
        members = db_net.get("Containers") or {}
        need(all((entry.get("Name") or "") in allowed for entry in members.values()),
             "database network contains an unexpected container")
        c = self.inspect(self.db_container)
        need(c["State"].get("Health", {}).get("Status") == "healthy", "database is not healthy")
        self.member(c, self.db_network, "db")
        if self.staging:
            mounts = [m for m in c["Mounts"] if m.get("Destination") == "/var/lib/postgresql/data"]
            need(len(mounts) == 1 and mounts[0].get("Name") == "namicash-bg-stage-postgres-data",
                 "staging database volume mismatch")
            volume = legacy.docker_json("volume", "inspect", "namicash-bg-stage-postgres-data")
            need(len(volume) == 1 and
                 (volume[0].get("Labels") or {}).get("com.docker.compose.project") == "namicash-bg-stage-db" and
                 (volume[0].get("Labels") or {}).get("com.docker.compose.volume") == "staging-db",
                 "staging database volume ownership mismatch")
            need(set(c["NetworkSettings"]["Networks"]) == {self.db_network},
                 "staging database has unexpected network access")
            fixture = safe_run(["docker", "exec", self.db_container, "sh", "-c",
                                'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT label FROM staging_fixture"'])
            need(fixture.strip() == "synthetic-only", "staging synthetic fixture missing")
            members = self.network(self.db_network).get("Containers") or {}
            need(all((entry.get("Name") or "").startswith("namicash-bg-stage-")
                     for entry in members.values()),
                 "staging database network contains a non-staging container")
        else:
            need(c["Id"] == legacy.inspect_container("db")["Id"], "production database identity changed")
            mounts = [m for m in c["Mounts"] if m.get("Destination") == "/var/lib/postgresql/data"]
            need(len(mounts) == 1 and mounts[0].get("Name") == "cashbook-postgres-production-data",
                 "production database volume mismatch")
        return c["Id"]

    def env_guard(self):
        need(self.env_file.is_file(), "environment file missing")
        if self.staging:
            prod_env = ROOT / ".env.prod"
            need(not prod_env.exists() or not self.env_file.samefile(prod_env),
                 "staging cannot use production environment")
            raw = self.env_file.read_bytes()
            need(not re.search(rb"^(?:PROD(?:UCTION)?_|CLOUDFLARE_|AWS_|GH_|GITHUB_TOKEN|SENTRY_BACKEND_DSN=\S)",
                               raw, re.MULTILINE), "production or external credentials in staging environment")
            passwords = re.findall(rb"^POSTGRES_PASSWORD=(.*)$", raw, re.MULTILINE)
            need(len(passwords) == 1 and re.fullmatch(rb"stage_[A-Za-z0-9_]+", passwords[0]) and
                 b"replace_with" not in passwords[0],
                 "staging requires a distinct stage_ PostgreSQL credential")
            need(re.findall(rb"^STAGING_ISOLATED=(.*)$", raw, re.MULTILINE) == [b"1"] and
                 re.findall(rb"^POSTGRES_DB=(.*)$", raw, re.MULTILINE) == [b"namicash_stage"] and
                 re.findall(rb"^POSTGRES_USER=(.*)$", raw, re.MULTILINE) == [b"stage"],
                 "staging environment marker or database name missing")
            need(b"namicash_stage" in raw and b"@db:" in raw,
                 "staging database URL must target the isolated db alias")
            url_values = re.findall(rb"^DATABASE_URL=(.*)$", raw, re.MULTILINE)
            need(len(url_values) == 1, "staging requires one database URL")
            expected_url = (b"postgresql+psycopg://stage:" + passwords[0] +
                            b"@db:5432/namicash_stage")
            need(url_values[0] == expected_url,
                 "staging database URL requires psycopg v3 and isolated credentials")
            need(re.search(rb"^REGISTRATION_MODE=open$", raw, re.MULTILINE),
                 "staging must use synthetic open-registration mode")
        else:
            need(self.env_file.samefile(ROOT / ".env.prod"), "production must use existing .env.prod")

    def compose_env(self, color, refs, nginx_path):
        env = dict(os.environ)
        if self.staging:
            for line in self.env_file.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    if key in ("STAGING_ISOLATED", "POSTGRES_DB", "POSTGRES_USER",
                               "POSTGRES_PASSWORD", "DATABASE_URL", "FRONTEND_ORIGIN",
                               "TRUSTED_HOSTS", "FORWARDED_ALLOW_IPS", "REGISTRATION_MODE"):
                        env[key] = value
            env["SENTRY_BACKEND_DSN"] = ""
            env["SENTRY_FRONTEND_DSN"] = ""
        return {**env, "BACKEND_IMAGE": refs["backend"], "FRONTEND_IMAGE": refs["frontend"],
                "BG_COLOR": color, "BG_DB_NETWORK": self.db_network,
                "BG_GATEWAY_NETWORK": self.gateway_network, "FRONTEND_NGINX_CONF": str(nginx_path),
                "BG_PROBE_HOST": self.host}

    def compose(self, color, refs, nginx_path, *command):
        need(color in COLORS, "invalid color")
        return safe_run(["docker", "compose", "-p", self.project(color), "--env-file",
                         str(self.env_file), "-f", str(ROOT / "compose.bluegreen.yaml"), *command],
                        env=self.compose_env(color, refs, nginx_path))

    def config_check(self, color, refs, nginx_path):
        self.env_guard()
        legacy.validate_refs(refs)
        try:
            cfg = json.loads(self.compose(color, refs, nginx_path, "config", "--format", "json"))
        except (ValueError, TypeError):
            raise Error("Compose configuration malformed") from None
        services = cfg.get("services", {})
        need(set(services) == {"backend", "frontend"}, "candidate Compose may contain only application services")
        b, f = services["backend"], services["frontend"]
        for service, item in (("backend", b), ("frontend", f)):
            need("build" not in item and item.get("image") == refs[service] and not item.get("ports"),
                 f"unsafe {service} image, build, or port configuration")
        need(b.get("command") == BACKEND_COMMAND + [b["environment"]["FORWARDED_ALLOW_IPS"]],
             "backend must start without running migrations")
        expected_backend_health = ["CMD", "python", "-c",
                                   "import urllib.request; urllib.request.urlopen(urllib.request.Request("
                                   "'http://127.0.0.1:8000/ready', headers={'Host': '" + self.host +
                                   "'}), timeout=2)"]
        need(b.get("healthcheck", {}).get("test") == expected_backend_health and
             f.get("healthcheck", {}).get("test") ==
             ["CMD", "wget", "-q", "-O", "/dev/null", "--header", f"Host: {self.host}",
              "http://127.0.0.1:8080/api/v1/auth/recovery-info"],
             "candidate health checks changed")
        db_url = urlsplit(b["environment"].get("DATABASE_URL", ""))
        need(db_url.hostname == "db", "backend database endpoint must be the isolated db alias")
        nets = cfg.get("networks", {})
        need(nets.get("database", {}).get("name") == self.db_network and
             nets.get("gateway", {}).get("name") == self.gateway_network and
             nets.get("app", {}).get("internal") is True, "candidate network isolation changed")
        need(set(b.get("networks", {})) == {"app", "database"} and
             set(f.get("networks", {})) == {"app", "gateway"}, "candidate network membership changed")
        need(b["networks"]["app"].get("aliases") == [f"{color}-api"] and
             f["networks"]["gateway"].get("aliases") == [f"{color}-frontend"],
             "candidate service discovery aliases changed")
        need(str(b.get("mem_limit")) == str(512 * 1024**2) and
             str(f.get("mem_limit")) == str(256 * 1024**2) and
             b.get("pids_limit") == 256 and f.get("pids_limit") == 128,
             "candidate resource limits changed")
        need(not b.get("volumes") and len(f.get("volumes", [])) == 1, "unexpected candidate mounts")
        need(str(f["volumes"][0]["source"]) == str(nginx_path), "frontend proxy mount changed")
        return cfg

    def nginx(self, color, version):
        source = (ROOT / "frontend/nginx.conf").read_text()
        need(source.count(NGINX_UPSTREAM) == 1, "frontend proxy template changed")
        need(color in COLORS and legacy.VERSION.fullmatch(version), "invalid frontend identity")
        return (source.replace(NGINX_UPSTREAM, f"proxy_pass http://{color}-api:8000;")
                .replace("    index index.html;", "    index index.html;\n"
                         f'    add_header X-Nami-Environment "{color}" always;\n'
                         f'    add_header X-Nami-Release "{version}" always;')).encode()

    def resource_check(self, *, staging_additional_mib=None):
        mem = Path("/proc/meminfo").read_text()
        match = re.search(r"^MemAvailable:\s+(\d+) kB$", mem, re.MULTILINE)
        need(match is not None, "available memory cannot be measured")
        available_mib = int(match[1]) // 1024
        disk_path = self.state_dir
        while not disk_path.exists():
            disk_path = disk_path.parent
        disk_mib = shutil.disk_usage(disk_path).free // (1024 * 1024)
        running = int(safe_run(["docker", "info", "--format", "{{.ContainersRunning}}"]).strip())
        if self.staging:
            additional_mib = (STAGING_CANDIDATE_MIB if staging_additional_mib is None
                              else staging_additional_mib)
            required_mib = additional_mib + STAGING_OVERHEAD_MIB + STAGING_HOST_RESERVE_MIB
        else:
            additional_mib = 768
            required_mib = REQUIRED_MEMORY_MIB
        need(available_mib >= required_mib,
             f"insufficient memory: {available_mib} MiB available; {required_mib} MiB required")
        need(disk_mib >= REQUIRED_DISK_MIB, f"insufficient disk: {disk_mib} MiB free")
        if not self.staging:
            need(running <= MAX_RUNNING_CONTAINERS,
                 f"existing Docker load too high: {running} running containers")
        return {"memory_available_mib": available_mib, "disk_free_mib": disk_mib,
                "running_containers": running, "candidate_limit_mib": additional_mib,
                "estimated_additional_mib": additional_mib + 256}

    def schema_revision(self):
        # Read-only query inside the existing DB container. Shell expands its
        # own environment; credentials never cross the controller output.
        result = safe_run(["docker", "exec", self.db_container, "sh", "-c",
                           'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT version_num FROM alembic_version"'])
        revision = result.strip()
        need(re.fullmatch(r"[A-Za-z0-9_]+", revision) is not None, "database schema revision unknown")
        return revision

    def compatibility(self, state, refs):
        if self.staging:
            revision = self.schema_revision()
            need(revision == self.image_schema_head(refs["backend"]),
                 "staging database schema does not match candidate backend")
            return revision
        need(self.attestation and self.attestation.is_file(), "schema compatibility attestation required")
        try:
            data = json.loads(self.attestation.read_text())
        except (OSError, ValueError):
            raise Error("schema compatibility attestation malformed") from None
        old = state["slots"][state["active"]]["refs"]
        revision = self.schema_revision()
        need(data.get("compatible") is True and data.get("revision") == revision and
             data.get("active_backend") == old["backend"] and
             data.get("candidate_backend") == refs["backend"] and
             isinstance(data.get("approved_by"), str) and bool(data["approved_by"].strip()),
             "database schema compatibility is unknown or mismatched")
        return sha(self.attestation.read_bytes())

    def image_schema_head(self, ref):
        need(self.staging, "image schema inspection is staging-only")
        need(isinstance(ref, str) and ref.startswith(legacy.REPOS["backend"] + "@") and
             legacy.DIGEST.fullmatch(ref.split("@", 1)[1]), "backend image must use an immutable digest")
        heads = safe_run(["docker", "run", "--rm", "--pull=never", "--network", "none",
                          "--memory", "512m", "--pids-limit", "256", "--platform", "linux/amd64",
                          "--entrypoint", "alembic", ref, "heads"]).strip().splitlines()
        need(len(heads) == 1, "backend image must contain exactly one Alembic head")
        revision = heads[0].split()[0]
        need(re.fullmatch(r"[A-Za-z0-9_]+", revision), "backend image Alembic head invalid")
        return revision

    def staging_migrate(self, ref):
        need(self.staging, "database migration helper is staging-only")
        self.env_guard()
        self.db_identity()
        self.image_schema_head(ref)
        self.resource_check(staging_additional_mib=512)
        safe_run(["docker", "run", "--rm", "--pull=never", "--network", self.db_network,
                  "--memory", "512m", "--pids-limit", "256",
                  "--platform", "linux/amd64", "--env-file", str(self.env_file),
                  "--entrypoint", "alembic", ref, "upgrade", "head"])
        need(self.schema_revision() == self.image_schema_head(ref),
             "staging migration did not reach backend image head")

    def gateway_guard(self, state=None):
        need(self.gateway_file.is_file() and self.snippet.is_file(), "managed Caddy configuration missing")
        main = self.gateway_file.read_bytes()
        need(main == (ROOT / "gateway/Caddyfile.bluegreen.example").read_bytes(),
             "gateway configuration differs from dedicated NamiCash template")
        need(main.count(IMPORT.encode()) == 1 and main.count(ADMIN.encode()) == 1,
             "Caddy gateway lacks managed import or protected Unix admin socket")
        c = self.inspect(self.gateway_container)
        self.member(c, self.gateway_network)
        need(set(c["NetworkSettings"]["Networks"]) == {self.gateway_network},
             "gateway has unexpected network access")
        if self.staging:
            need(c["NetworkSettings"].get("Ports", {}).get("8091/tcp") ==
                 [{"HostIp": "127.0.0.1", "HostPort": "18091"}],
                 "staging gateway must bind only loopback port 18091")
            need(all((entry.get("Name") or "").startswith("namicash-bg-stage-")
                     for entry in (self.network(self.gateway_network).get("Containers") or {}).values()),
                 "staging gateway network contains a non-staging container")
        mounts = c.get("Mounts", [])
        need(any(m.get("Destination") == "/etc/caddy/managed" and
                 Path(m.get("Source", "")).resolve() == self.managed_dir.resolve() for m in mounts),
             "Caddy managed directory is not mounted")
        if state:
            need(sha(main) == state["gateway_hash"], "unauthorized Caddyfile modification")
            need(sha(self.snippet.read_bytes()) == state["route_hash"], "unauthorized Caddy route modification")
        return sha(main)

    def slot_check(self, color, slot):
        refs = slot["refs"]
        legacy.validate_refs(refs)
        legacy_blue = slot.get("kind") == "legacy"
        names = {s: self.container_name(color, s, legacy_blue=legacy_blue) for s in legacy.REPOS}
        containers = {s: self.inspect(name) for s, name in names.items()}
        for service, c in containers.items():
            labels = c["Config"].get("Labels") or {}
            expected_project = legacy.PROJECT if legacy_blue else self.project(color)
            need(labels.get("com.docker.compose.project") == expected_project and
                 labels.get("com.docker.compose.service") == service,
                 f"{color} {service} Compose identity mismatch")
            need(c["State"].get("Health", {}).get("Status") == "healthy", f"{color} {service} unhealthy")
            need(c["Image"] == legacy.image_id(refs[service]), f"{color} {service} image mismatch")
            if not legacy_blue:
                need(c["Config"].get("Image") == refs[service],
                     f"{color} {service} is not pinned to expected digest")
                need(not legacy.port_set(c), f"{color} {service} unexpectedly publishes ports")
        self.member(containers["frontend"], self.gateway_network, f"{color}-frontend")
        if not legacy_blue:
            app_net = f"{self.project(color)}_app"
            self.member(containers["frontend"], app_net)
            self.member(containers["backend"], app_net, f"{color}-api")
            self.member(containers["backend"], self.db_network)
            need(self.db_network not in containers["frontend"]["NetworkSettings"]["Networks"] and
                 self.gateway_network not in containers["backend"]["NetworkSettings"]["Networks"],
                 "application network isolation broken")
            need(set(containers["backend"]["NetworkSettings"]["Networks"]) == {app_net, self.db_network} and
                 set(containers["frontend"]["NetworkSettings"]["Networks"]) == {app_net, self.gateway_network},
                 "application has unexpected network access")
            proxy = self.state_dir / "nginx" / f"{color}.conf"
            need(proxy.is_file() and proxy.read_bytes() == self.nginx(color, slot["version"]),
                 "frontend-to-backend routing configuration changed")
            need(any(m.get("Destination") == "/etc/nginx/conf.d/default.conf" and
                     Path(m.get("Source", "")).resolve() == proxy.resolve()
                     for m in containers["frontend"].get("Mounts", [])),
                 "frontend proxy mount changed")
            response = safe_run(["docker", "exec", names["frontend"], "wget", "-q", "-O", "-",
                                 "--header", f"Host: {self.host}",
                                 "http://127.0.0.1:8080/api/v1/auth/recovery-info"])
            try:
                need("message" in json.loads(response), "frontend API route failed")
            except ValueError:
                raise Error("frontend API response malformed") from None
        return {s: c["Id"] for s, c in containers.items()}

    def route_text(self, color):
        need(color in COLORS, "invalid route color")
        return (f"header X-Nami-Route {color}\n"
                f"reverse_proxy {color}-frontend:8080 {{\n"
                "    stream_close_delay 5m\n}\n").encode()

    def route_probe(self, color, *, managed=True):
        for path in ("/", "/api/v1/auth/recovery-info"):
            req = urllib.request.Request(self.gateway_url + path, headers={"Host": self.host})
            try:
                with urllib.request.urlopen(req, timeout=4) as response:
                    body = response.read(256 * 1024)
                    need(response.status == 200, "Caddy route response not healthy")
                    if managed:
                        need(response.headers.get("X-Nami-Route") == color, "Caddy routed to wrong color")
                    if path.startswith("/api/"):
                        need("message" in json.loads(body), "Caddy API route failed")
                    elif color == "green" or self.staging:
                        need(response.headers.get("X-Nami-Environment") == color,
                             "Caddy upstream environment mismatch")
            except (OSError, ValueError) as exc:
                raise Error(f"Caddy route verification failed: {type(exc).__name__}") from None

    def caddy_validate(self, candidate):
        main = self.gateway_file.read_text()
        need(main.count(IMPORT) == 1, "Caddy import changed")
        candidate_path = self.managed_dir / f"candidate-{os.getpid()}.caddy"
        full_path = self.managed_dir / f"candidate-{os.getpid()}.Caddyfile"
        try:
            atomic(candidate_path, candidate)
            full = main.replace(IMPORT, f"import /etc/caddy/managed/{candidate_path.name}")
            atomic(full_path, full.encode())
            safe_run(["docker", "exec", self.gateway_container, "caddy", "validate", "--config",
                      f"/etc/caddy/managed/{full_path.name}", "--adapter", "caddyfile"])
        finally:
            candidate_path.unlink(missing_ok=True)
            full_path.unlink(missing_ok=True)

    def caddy_reload(self):
        safe_run(["docker", "exec", self.gateway_container, "caddy", "reload", "--config",
                  "/etc/caddy/Caddyfile", "--address", "unix//run/caddy-admin.sock"])

    def switch(self, state, target, inject_failure=None):
        previous = state["active"]
        old = self.snippet.read_bytes()
        candidate = self.route_text(target)
        self.caddy_validate(candidate)
        revision = self.schema_revision()
        state["phase"] = "promoting"
        state["pending"] = {"from": previous, "to": target, "old_route_sha": sha(old),
                            "revision": revision}
        atomic(self.state_dir / "previous-route.caddy", old)
        self.save(state, "promotion-start")
        try:
            atomic(self.snippet, candidate)
            if inject_failure == "crash-after-route-write":
                raise SystemExit("simulated controller interruption after route write")
            if inject_failure == "reload":
                raise Error("simulated Caddy reload failure")
            self.caddy_reload()
            if inject_failure == "crash-after-reload":
                raise SystemExit("simulated controller interruption after Caddy reload")
            self.route_probe(target)
        except (Error, legacy.SafetyError):
            atomic(self.snippet, old)
            try:
                self.caddy_reload()
                self.route_probe(previous)
                state["phase"] = "idle"
                state.pop("pending", None)
                state["route_hash"] = sha(old)
                self.save(state, "promotion-reverted")
            except (Error, legacy.SafetyError):
                state["phase"] = "recovery-required"
                self.save(state, "promotion-recovery-required")
            raise Error("Caddy promotion failed; previous route restored or recovery required") from None
        state["active"] = target
        state["rollback_to"] = previous
        state["rollback_schema"] = revision
        state["slots"][target]["status"] = "active"
        state["slots"][previous]["status"] = "staged"
        state["phase"] = "idle"
        state.pop("pending", None)
        state["route_hash"] = sha(candidate)
        self.save(state, "promotion-success")

    def rollback(self, state):
        pending = state.get("pending")
        if pending:
            target = pending["from"]
            if not self.staging:
                need(self.schema_revision() == pending.get("revision"),
                     "database schema changed during interrupted promotion")
        else:
            target = state.get("rollback_to")
            need(target in COLORS and target != state["active"],
                 "no previous promoted environment to roll back to")
            if not self.staging:
                need(self.schema_revision() == state.get("rollback_schema"),
                     "database schema changed since promotion; rollback compatibility unknown")
        slot = state["slots"].get(target)
        need(slot and slot.get("status") in ("active", "staged", "prepared"), "previous environment unavailable")
        self.db_identity()
        self.slot_check(target, slot)
        if pending:
            previous = self.state_dir / "previous-route.caddy"
            need(previous.is_file() and sha(previous.read_bytes()) == pending["old_route_sha"],
                 "known-good route snapshot missing")
            self.caddy_validate(previous.read_bytes())
            atomic(self.snippet, previous.read_bytes())
            self.caddy_reload()
            self.route_probe(target)
            previous_active = state["active"]
            state["active"] = target
            state["slots"][target]["status"] = "active"
            if previous_active != target:
                state["slots"][previous_active]["status"] = "staged"
            state["phase"] = "idle"
            state.pop("pending", None)
            state["route_hash"] = sha(self.snippet.read_bytes())
            self.save(state, "interrupted-promotion-recovered")
        else:
            self.switch(state, target)
        return target

    def staging_setup(self, manifest_path, execute):
        need(self.staging, "staging setup cannot operate in production mode")
        need(self.managed_dir == self.state_dir / "managed" and
             self.gateway_file == self.state_dir / "Caddyfile",
             "staging gateway paths must remain inside staging state")
        need(not self.state_path.exists(), "staging state already initialized")
        self.env_guard()
        data, refs = self.manifest(manifest_path)
        resources = self.resource_check(staging_additional_mib=STAGING_SETUP_MIB)
        nginx_path = self.state_dir / "nginx" / "blue.conf"
        self.config_check("blue", refs, nginx_path)
        if not execute:
            return (f"Dry run: isolated staging networks, database, Caddy and Blue app; "
                    f"estimated +{resources['estimated_additional_mib']} MiB; no containers changed")
        try:
            volume = legacy.docker_json("volume", "inspect", "namicash-bg-stage-postgres-data")
        except legacy.SafetyError:
            volume = None
        if volume:
            need(len(volume) == 1 and
                 (volume[0].get("Labels") or {}).get("com.docker.compose.project") == "namicash-bg-stage-db" and
                 (volume[0].get("Labels") or {}).get("com.docker.compose.volume") == "staging-db",
                 "existing staging database volume lacks staging ownership")
        for network, internal in ((self.gateway_network, False), (self.db_network, True)):
            try:
                existing = self.network(network)
            except (Error, legacy.SafetyError):
                cmd = ["docker", "network", "create"]
                if internal:
                    cmd.append("--internal")
                cmd.extend(("--label", "org.namicash.scope=bluegreen-staging"))
                safe_run([*cmd, network])
            else:
                need(existing.get("Internal") is internal, f"{network} isolation setting changed")
                need((existing.get("Labels") or {}).get("org.namicash.scope") == "bluegreen-staging",
                     f"{network} staging ownership label missing")
                members = existing.get("Containers") or {}
                need(all((entry.get("Name") or "").startswith("namicash-bg-stage-")
                         for entry in members.values()),
                     "staging network contains a non-staging container")
        gateway_source = (ROOT / "gateway/Caddyfile.bluegreen.example").read_bytes()
        if self.gateway_file.exists():
            need(self.gateway_file.read_bytes() == gateway_source,
                 "existing staging Caddyfile differs from fixture")
        else:
            atomic(self.gateway_file, gateway_source)
        if self.snippet.exists():
            need(self.snippet.read_bytes() == self.route_text("blue"),
                 "existing staging route is not Blue")
        else:
            atomic(self.snippet, self.route_text("blue"))
        expected_nginx = self.nginx("blue", data["version"])
        if nginx_path.exists():
            need(nginx_path.read_bytes() == expected_nginx, "existing staging Blue proxy differs")
        else:
            atomic(nginx_path, expected_nginx)
        for ref in refs.values():
            legacy.image_id(ref, remote=True)
            safe_run(["docker", "pull", "--platform", "linux/amd64", ref])
            legacy.image_id(ref)
        safe_run(["docker", "compose", "-p", "namicash-bg-stage-db", "--env-file",
                  str(self.env_file), "-f", str(ROOT / "compose.bluegreen.staging-db.yaml"),
                  "up", "-d", "--no-build", "db"],
                 env=self.compose_env("blue", refs, nginx_path))
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            try:
                self.db_identity()
                break
            except (Error, legacy.SafetyError):
                time.sleep(5)
        else:
            raise Error("staging database health timed out")
        self.staging_migrate(refs["backend"])
        self.resource_check(staging_additional_mib=896)
        safe_run(["docker", "compose", "-p", "namicash-bg-stage-gateway", "-f",
                  str(ROOT / "compose.bluegreen.staging-gateway.yaml"), "up", "-d", "--no-build"],
                 env={**self.compose_env("blue", refs, nginx_path), "BG_CADDYFILE": str(self.gateway_file),
                      "BG_MANAGED_DIR": str(self.managed_dir)})
        self.gateway_guard()
        self.resource_check(staging_additional_mib=768)
        self.compose("blue", refs, nginx_path, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "backend")
        slot = {"kind": "managed", "refs": refs, "version": data["version"], "source_commit": data["source_commit"], "status": "active"}
        self.wait_slot("blue", slot, backend_only=True)
        self.resource_check(staging_additional_mib=256)
        self.compose("blue", refs, nginx_path, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "frontend")
        self.wait_slot("blue", slot)
        self.route_probe("blue")
        return "Isolated staging Blue is healthy; run bootstrap --execute to record baseline"

    def bootstrap(self, manifest_path, execute):
        data, refs = self.manifest(manifest_path)
        self.env_guard()
        self.db_identity()
        self.gateway_guard()
        if self.staging:
            slot = {"kind": "managed", "refs": refs, "version": data["version"], "source_commit": data["source_commit"], "status": "active"}
        else:
            slot = {"kind": "legacy", "refs": refs, "version": data["version"], "source_commit": data["source_commit"], "status": "active"}
            # The existing production app is Blue; never recreate it here.
            legacy.identity({s: legacy.inspect_container(s) for s in ("db", "backend", "frontend")})
        ids = self.slot_check("blue", slot)
        need(self.snippet.read_bytes() == self.route_text("blue"), "initial Caddy route is not Blue")
        self.route_probe("blue")
        need(not self.state_path.exists(), "blue/green state already initialized")
        baseline = {"db_id": self.db_identity(), "blue_ids": ids}
        state = {"schema": 1, "mode": self.mode, "active": "blue", "phase": "idle",
                 "slots": {"blue": slot}, "baseline": baseline,
                 "rollback_to": None, "rollback_schema": None,
                 "gateway_hash": sha(self.gateway_file.read_bytes()),
                 "route_hash": sha(self.snippet.read_bytes())}
        if execute:
            self.save(state, "bootstrap-blue")
        return f"Blue bootstrap {'recorded' if execute else 'validated; no state written'}"

    def stage(self, state, data, refs, execute):
        color = "green" if state["active"] == "blue" else "blue"
        existing = state["slots"].get(color)
        need(not existing or existing.get("status") in ("prepared", "retired", "staging"),
             "inactive environment already staged; finalize it first")
        if existing and existing.get("kind") == "legacy" and existing.get("status") != "retired":
            raise Error("legacy Blue must be explicitly finalized before reusing the Blue slot")
        nginx_path = self.state_dir / "nginx" / f"{color}.conf"
        self.config_check(color, refs, nginx_path)
        self.gateway_guard(state)
        self.network(self.gateway_network)
        self.network(self.db_network)
        self.baseline_check(state)
        resources = self.resource_check()
        attestation_hash = self.compatibility(state, refs)
        need(existing and existing.get("refs") == refs and existing.get("status") in ("prepared", "staging"),
             "candidate must be prepared with the same manifest")
        need(legacy.image_id(refs["backend"]) and legacy.image_id(refs["frontend"]),
             "prepared images unavailable")
        if not execute:
            return color, resources
        expected_nginx = self.nginx(color, data["version"])
        if nginx_path.exists():
            need(nginx_path.read_bytes() == expected_nginx,
                 "existing candidate proxy differs from manifest")
        else:
            atomic(nginx_path, expected_nginx)
        state["slots"][color] = {"kind": "managed", "refs": refs, "version": data["version"],
                                 "status": "staging", "source_commit": data["source_commit"],
                                 "schema_attestation_sha": attestation_hash}
        state["phase"] = "staging"
        self.save(state, "stage-start")
        try:
            self.compose(color, refs, nginx_path, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "backend")
            self.wait_slot(color, state["slots"][color], backend_only=True)
            if self.staging:
                self.resource_check(staging_additional_mib=256)
            self.compose(color, refs, nginx_path, "up", "-d", "--no-deps", "--no-build", "--pull", "never", "frontend")
            self.wait_slot(color, state["slots"][color])
        except (Error, legacy.SafetyError):
            state["phase"] = "stage-failed"
            self.save(state, "stage-failed")
            raise
        state["slots"][color]["status"] = "staged"
        state["phase"] = "idle"
        self.save(state, "stage-success")
        return color, resources

    def wait_slot(self, color, slot, *, backend_only=False):
        deadline = time.monotonic() + 180
        services = ("backend",) if backend_only else ("backend", "frontend")
        while time.monotonic() < deadline:
            containers = [self.inspect(self.container_name(color, s), running=False) for s in services]
            need(all(c["State"].get("Health", {}).get("Status") != "unhealthy" for c in containers),
                 f"{color} service became unhealthy")
            if all(c["State"].get("Health", {}).get("Status") == "healthy" for c in containers):
                if not backend_only:
                    self.slot_check(color, slot)
                return
            time.sleep(5)
        raise Error(f"{color} health timeout")

    def prepare(self, state, data, refs, execute):
        color = "green" if state["active"] == "blue" else "blue"
        slot = state["slots"].get(color)
        need(not slot or slot.get("status") in ("retired", "prepared", "stage-failed"),
             "inactive slot is occupied")
        self.env_guard()
        self.baseline_check(state)
        self.gateway_guard(state)
        self.resource_check()
        if not self.staging:
            self.compatibility(state, refs)
        for ref in refs.values():
            legacy.image_id(ref, remote=True)
        if execute:
            for ref in refs.values():
                safe_run(["docker", "pull", "--platform", "linux/amd64", ref])
                legacy.image_id(ref)
            if self.staging:
                self.staging_migrate(refs["backend"])
                self.compatibility(state, refs)
                self.slot_check(state["active"], state["slots"][state["active"]])
                self.route_probe(state["active"])
            state["slots"][color] = {"kind": "managed", "refs": refs,
                                     "version": data["version"], "source_commit": data["source_commit"],
                                     "status": "prepared"}
            self.save(state, "prepare-success")
        return color

    def verify_candidate(self, state):
        color = "green" if state["active"] == "blue" else "blue"
        slot = state["slots"].get(color)
        need(slot and slot.get("status") == "staged", "candidate not staged")
        self.baseline_check(state)
        self.slot_check(color, slot)
        if not self.staging:
            need(self.attestation and self.attestation.is_file() and
                 self.compatibility(state, slot["refs"]) == slot["schema_attestation_sha"],
                 "schema compatibility evidence changed")
        return color

    def check_phase(self, state, allowed=("idle",)):
        need(state.get("phase") in allowed, f"interrupted operation ({state.get('phase')}); run rollback or resume stage")

    def execute(self, args):
        command = args.command
        if command == "staging-setup":
            return self.staging_setup(args.manifest, args.execute)
        if command == "bootstrap":
            return self.bootstrap(args.manifest, args.execute)
        state = self.load()
        if command == "status":
            health = {}
            for color, slot in state["slots"].items():
                if slot.get("status") in ("active", "staged"):
                    try:
                        self.slot_check(color, slot)
                        health[color] = "healthy"
                    except (Error, legacy.SafetyError):
                        health[color] = "unhealthy-or-unavailable"
            try:
                self.db_identity()
                self.route_probe(state["active"])
                health["database"] = "healthy"
                health["route"] = "healthy"
            except (Error, legacy.SafetyError):
                health["route"] = "unhealthy-or-unavailable"
            return json.dumps({"active": state["active"], "phase": state.get("phase"),
                               "rollback_to": state.get("rollback_to"),
                               "health": health, "slots": {c: {"version": s.get("version"),
                               "status": s.get("status"), "refs": s.get("refs"),
                               "source_commit": s.get("source_commit")}
                               for c, s in state["slots"].items()}}, sort_keys=True)
        if command == "rollback":
            need(state.get("phase") in ("idle", "promoting", "recovery-required"),
                 "rollback unavailable during staging")
            target = state.get("pending", {}).get("from") or state.get("rollback_to")
            need(target in COLORS and target != state["active"] or
                 bool(state.get("pending") and target == state["active"]),
                 "no prior promotion to roll back")
            if not args.execute:
                return f"Dry run: restore previous {target} route"
            self.gateway_guard(state if state["phase"] == "idle" else None)
            return f"Rollback routed to {self.rollback(state)}"
        self.check_phase(state, ("idle", "stage-failed", "staging")
                         if command in ("stage", "finalize") else ("idle",))
        if command in ("plan", "prepare", "stage"):
            data, refs = self.manifest(args.manifest)
            color = "green" if state["active"] == "blue" else "blue"
            if command == "plan":
                self.env_guard()
                self.gateway_guard(state)
                self.config_check(color, refs, self.state_dir / "nginx" / f"{color}.conf")
                resources = self.resource_check()
                self.db_identity()
                return f"Plan: {state['active']} remains active; {color} candidate {data['version']}; estimated +{resources['estimated_additional_mib']} MiB; no changes"
            if command == "prepare":
                return f"{color} images {'prepared' if args.execute else 'validated; no pull'}" if self.prepare(state, data, refs, args.execute) else ""
            staged, resources = self.stage(state, data, refs, args.execute)
            return f"{staged} {'staged and verified' if args.execute else 'stage validated; no changes'}; estimated +{resources['estimated_additional_mib']} MiB"
        if command == "verify":
            self.gateway_guard(state)
            color = self.verify_candidate(state)
            self.route_probe(state["active"])
            return f"{color} candidate healthy; {state['active']} remains routed"
        if command == "promote":
            need(not args.inject_failure or self.staging, "failure injection is staging-only")
            self.gateway_guard(state)
            color = self.verify_candidate(state)
            self.slot_check(state["active"], state["slots"][state["active"]])
            self.route_probe(state["active"])
            if not args.execute:
                need(self.route_text(color), "invalid candidate route")
                return f"Dry run: {color} healthy; Caddy validation and route change reserved for --execute"
            self.switch(state, color, args.inject_failure)
            old = "green" if color == "blue" else "blue"
            return f"Traffic routed to {color}; previous {old} retained"
        if command == "finalize":
            color = args.color
            need(color in COLORS and color != state["active"], "only inactive color may be retired")
            slot = state["slots"].get(color)
            need(slot and slot.get("kind") in ("managed", "legacy"), "inactive environment unavailable")
            need(slot.get("status") in ("staged", "staging"), "inactive environment cannot be retired")
            if slot["kind"] == "legacy":
                need(not self.staging and color == "blue" and args.allow_legacy_blue,
                     "legacy Blue retirement needs --allow-legacy-blue")
            self.gateway_guard(state)
            self.route_probe(state["active"])
            if not args.execute:
                return f"Dry run: stop inactive {color} application containers; no database operation"
            if slot["kind"] == "legacy":
                safe_run(["docker", "compose", "-p", legacy.PROJECT, "--env-file",
                          str(ROOT / ".env.prod"), "-f", str(ROOT / "compose.production.yaml"),
                          "stop", "frontend", "backend"])
            else:
                path = self.state_dir / "nginx" / f"{color}.conf"
                self.compose(color, slot["refs"], path, "stop", "frontend", "backend")
            slot["status"] = "retired"
            if state.get("rollback_to") == color:
                state["rollback_to"] = None
                state["rollback_schema"] = None
            state["phase"] = "idle"
            self.save(state, "finalize-inactive")
            return f"Inactive {color} containers stopped; images and history retained"
        raise Error("unsupported command")


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("staging", "production"), default="staging")
    parser.add_argument("--state-dir")
    parser.add_argument("--env-file")
    parser.add_argument("--managed-dir")
    parser.add_argument("--gateway-file")
    parser.add_argument("--schema-attestation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("staging-setup", "bootstrap", "plan", "prepare", "stage", "verify", "promote", "rollback", "status", "finalize"):
        cmd = sub.add_parser(name)
        if name in ("bootstrap", "plan", "prepare", "stage", "staging-setup"):
            cmd.add_argument("--manifest", required=True)
        if name == "finalize":
            cmd.add_argument("--color", choices=COLORS, required=True)
            cmd.add_argument("--allow-legacy-blue", action="store_true")
        if name in ("staging-setup", "bootstrap", "prepare", "stage", "promote", "rollback", "finalize"):
            cmd.add_argument("--execute", action="store_true")
        if name == "promote":
            cmd.add_argument("--inject-failure", choices=("reload", "crash-after-route-write", "crash-after-reload"))
    args = parser.parse_args(argv)
    controller = Controller(args)
    with controller.lock():
        result = controller.execute(args)
    print(result)


if __name__ == "__main__":
    try:
        main()
    except (Error, legacy.SafetyError) as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        sys.exit(1)

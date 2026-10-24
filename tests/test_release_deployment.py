import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import release_deployment as d


class DeploymentSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "manifest.json"
        self.payload = {
            "version": "v1.0.2", "source_commit": "a" * 40,
            "images": {s: {"name": repo, "digest": "sha256:" + "b" * 64,
                           "architecture": "linux/amd64"} for s, repo in d.REPOS.items()}}

    def check(self):
        self.path.write_text(json.dumps(self.payload))
        return d.manifest(self.path)

    def test_invalid_manifests(self):
        for value in ("v1.0", "v01.0.0", "v1.0.0:latest"):
            self.payload["version"] = value
            with self.assertRaises(d.SafetyError): self.check()
        self.payload["version"] = "v1.0.2"
        self.payload["images"]["backend"]["digest"] = "sha256:short"
        with self.assertRaises(d.SafetyError): self.check()
        self.payload["images"]["backend"]["digest"] = "sha256:" + "b" * 64
        self.payload["images"]["backend"]["architecture"] = "linux/arm64"
        with self.assertRaises(d.SafetyError): self.check()
        self.path.write_text("{bad json")
        with self.assertRaises(d.SafetyError): d.manifest(self.path)

    def test_wrong_repository_and_mutable_tag(self):
        self.payload["images"]["frontend"]["name"] = "ghcr.io/other/frontend"
        with self.assertRaises(d.SafetyError): self.check()
        with self.assertRaises(d.SafetyError):
            d.validate_refs({"backend": d.REPOS["backend"] + ":v1.0.2",
                             "frontend": d.REPOS["frontend"] + "@sha256:" + "a" * 64})

    def test_missing_backup_and_remote_failure(self):
        with patch.object(d, "BACKUP_DIR", Path(self.tmp.name)):
            with self.assertRaisesRegex(d.SafetyError, "no verified local backup"):
                d.backup_check()
            name = "namicash-postgres-" + d.dt.datetime.now(d.dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".dump.gz"
            archive = Path(self.tmp.name) / name
            archive.write_bytes(b"backup")
            (Path(self.tmp.name) / (name + ".sha256")).write_text(d.hashlib.sha256(b"backup").hexdigest() + "  " + name + "\n")
            with patch.object(d, "run"), patch.object(d.subprocess, "Popen", side_effect=OSError()):
                with self.assertRaisesRegex(d.SafetyError, "off-site"):
                    d.backup_check()

    def test_unhealthy_database_and_wrong_volume(self):
        with patch.object(d, "validate_compose"), patch.object(d, "run"), \
             patch.object(d, "inspect_container") as inspect:
            inspect.side_effect = lambda s: {"State": {"Health": {"Status": "unhealthy"}}} if s == "db" else {}
            with self.assertRaisesRegex(d.SafetyError, "database is not healthy"):
                d.preflight({s: repo + "@sha256:" + "b" * 64 for s, repo in d.REPOS.items()}, {}, backups=False)
        db = {"Mounts": [{"Destination": "/var/lib/postgresql/data", "Type": "volume", "Name": "wrong"}],
              "NetworkSettings": {"Networks": {"cashbook-mafunami_default": {"NetworkID": "net"}}}}
        apps = {s: {"NetworkSettings": {"Networks": {"cashbook-mafunami_default": {"NetworkID": "net"}},
                                          "Ports": {}}, "Mounts": []} for s in d.REPOS}
        with patch.object(d, "docker_json", side_effect=[[{"Name": "cashbook-mafunami_default", "Id": "net"}],
                                                      [{"Name": "cashbook-postgres-production-data"}]]):
            with self.assertRaisesRegex(d.SafetyError, "unexpected PostgreSQL volume"):
                d.identity({"db": db, **apps})

    def test_missing_previous_image(self):
        containers = {s: {"Config": {"Image": "local:latest"}, "Image": "sha256:" + "a" * 64} for s in d.REPOS}
        with patch.object(d, "docker_json", return_value=[{"RepoDigests": []}]):
            with self.assertRaisesRegex(d.SafetyError, "no immutable previous"):
                d.previous_refs(containers, {})

    def test_rollback_archive_fallback_and_missing_archive(self):
        ref = d.REPOS["backend"] + "@sha256:" + "b" * 64
        image_id = "sha256:" + "a" * 64
        with patch.object(d, "STATE_DIR", Path(self.tmp.name)), \
             patch.object(d, "image_id", side_effect=d.SafetyError("missing")):
            with self.assertRaisesRegex(d.SafetyError, "rollback image unavailable"):
                d.rollback_ref("backend", ref, image_id, False)
        with patch.object(d, "STATE_DIR", Path(self.tmp.name)):
            path = d.archive_path("backend", ref)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"archive")
            path.with_suffix(".json").write_text(json.dumps({
                "reference": ref, "image_id": image_id,
                "archive_sha256": d.hashlib.sha256(b"archive").hexdigest()}))
            with patch.object(d, "image_id", side_effect=d.SafetyError("missing")):
                self.assertEqual(d.rollback_ref("backend", ref, image_id, False), image_id)
            path.write_bytes(b"corrupt")
            with patch.object(d, "image_id", side_effect=d.SafetyError("missing")):
                with self.assertRaisesRegex(d.SafetyError, "archive invalid"):
                    d.rollback_ref("backend", ref, image_id, False)

    def test_failed_health_and_timeout(self):
        with patch.object(d, "inspect_container", return_value={"State": {"Health": {"Status": "unhealthy"}}}):
            with self.assertRaisesRegex(d.SafetyError, "became unhealthy"):
                d.wait_healthy({}, {}, 1)
        with patch.object(d, "inspect_container", return_value={"State": {"Health": {"Status": "starting"}}}), \
             patch.object(d, "verify", side_effect=d.SafetyError("starting")), \
             patch.object(d.time, "sleep"), patch.object(d.time, "monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(d.SafetyError, "timed out"):
                d.wait_healthy({}, {}, 1)

    def test_locking(self):
        with patch.object(d, "STATE_DIR", Path(self.tmp.name)):
            fd = d.lock()
            self.addCleanup(fd.close)
            with self.assertRaisesRegex(d.SafetyError, "holds the lock"):
                d.lock()

    def test_compose_never_targets_database_or_migration(self):
        refs = {s: repo + "@sha256:" + "b" * 64 for s, repo in d.REPOS.items()}
        with patch.object(d, "run") as run:
            d.compose_up(refs, "backend")
            args = run.call_args.args[0]
            self.assertIn("--no-deps", args)
            self.assertIn("--no-build", args)
            self.assertEqual(args[-1], "backend")
            self.assertNotIn("db", args)
            self.assertNotIn("migrate", args)
            self.assertNotIn("down", args)
            self.assertNotIn("alembic", " ".join(args))
        compose = (d.ROOT / "compose.ghcr.yaml").read_text()
        self.assertNotIn("  migrate:", compose)
        self.assertNotIn("    build:", compose)
        self.assertNotIn("alembic", compose)
        self.assertIn('command: ["uvicorn", "app.main:app"', compose)
        staging = (d.ROOT / "compose.staging.yaml").read_text()
        self.assertIn("namicash-staging-postgres-data", staging)
        self.assertNotIn("    ports:", staging)
        self.assertNotIn("alembic", staging)
        self.assertIn('127.0.0.1:${BACKEND_PORT:-8000}:8000', compose)
        self.assertIn('${LAN_BIND_IP:?Set LAN_BIND_IP in .env}', compose)
        self.assertIn('${TAILSCALE_BIND_IP:?Set TAILSCALE_BIND_IP in .env}', compose)

    def test_backend_image_startup_does_not_migrate(self):
        dockerfile = (d.ROOT / "backend/Dockerfile").read_text()
        command = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))
        self.assertIn("exec uvicorn app.main:app", command)
        self.assertNotIn("alembic", command)


if __name__ == "__main__":
    unittest.main()

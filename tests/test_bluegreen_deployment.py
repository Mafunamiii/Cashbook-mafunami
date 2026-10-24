import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bluegreen_deployment as bg
import release_deployment as legacy


class BlueGreenSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / ".env.bluegreen.staging"
        self.env.write_text("STAGING_ISOLATED=1\nPOSTGRES_DB=namicash_stage\n"
                            "POSTGRES_USER=stage\nPOSTGRES_PASSWORD=stage_synthetic\n"
                            "DATABASE_URL=postgresql://stage:stage_synthetic@db:5432/namicash_stage\n"
                            "FRONTEND_ORIGIN=https://stage.namicash.invalid\n"
                            "TRUSTED_HOSTS=stage.namicash.invalid\nFORWARDED_ALLOW_IPS=127.0.0.1\n"
                            "REGISTRATION_MODE=open\n")
        args = SimpleNamespace(mode="staging", state_dir=str(self.root / "state"), env_file=str(self.env),
                               managed_dir=None, gateway_file=None, schema_attestation=None)
        self.c = bg.Controller(args)
        self.refs = {s: repo + "@sha256:" + "a" * 64 for s, repo in legacy.REPOS.items()}
        self.state = {"schema": 1, "mode": "staging", "active": "blue", "phase": "idle",
                      "slots": {"blue": {"kind": "managed", "refs": self.refs,
                                         "version": "v1.0.2", "status": "active"},
                                "green": {"kind": "managed", "refs": self.refs,
                                          "version": "v1.0.2", "status": "staged"}},
                      "baseline": {"db_id": "db-id"}, "rollback_to": None,
                      "gateway_hash": "hash",
                      "route_hash": bg.sha(self.c.route_text("blue"))}

    def test_invalid_manifest_and_mutable_image(self):
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"version": "v1.0.2", "source_commit": "a" * 40,
                                    "images": {s: {"name": repo, "digest": "latest",
                                                   "architecture": "linux/amd64"}
                                               for s, repo in legacy.REPOS.items()}}))
        with self.assertRaises(legacy.SafetyError):
            self.c.manifest(path)
        with self.assertRaises(legacy.SafetyError):
            legacy.validate_refs({"backend": "ghcr.io/mafunamiii/namicash-backend:latest",
                                  "frontend": self.refs["frontend"]})

    def test_nginx_routes_only_to_own_backend(self):
        green = self.c.nginx("green", "v1.0.2").decode()
        self.assertIn("proxy_pass http://green-api:8000;", green)
        self.assertNotIn("proxy_pass http://backend:8000;", green)
        self.assertNotIn("blue-api", green)
        self.assertIn('X-Nami-Environment "green"', green)
        compose = (bg.ROOT / "compose.bluegreen.yaml").read_text()
        self.assertNotIn("  db:", compose)
        self.assertNotIn("    build:", compose)
        self.assertNotIn("    ports:", compose)
        self.assertNotIn("alembic", compose)
        self.assertIn('command: ["uvicorn",', compose)
        self.assertIn("internal: true", compose)

    def test_staging_database_isolation(self):
        self.c.env_guard()
        # Compose-level hostname validation is performed on the resolved config.
        with patch.object(self.c, "compose", return_value=json.dumps({
            "services": {"backend": {"image": self.refs["backend"], "command": bg.BACKEND_COMMAND + ["127.0.0.1"],
                                     "environment": {"FORWARDED_ALLOW_IPS": "127.0.0.1",
                                                     "DATABASE_URL": "postgresql://x@production-db:5432/x"},
                                     "healthcheck": {"test": ["CMD", "python", "-c",
                                                              "import urllib.request; urllib.request.urlopen(urllib.request.Request("
                                                              "'http://127.0.0.1:8000/ready', headers={'Host': 'stage.namicash.invalid'"
                                                              "}), timeout=2)"]},
                                     "networks": {"app": {}, "database": {}}},
                         "frontend": {"image": self.refs["frontend"], "networks": {"app": {}, "gateway": {}},
                                      "volumes": [{"source": str(self.root / "proxy.conf")}],
                                      "healthcheck": {"test": ["CMD", "wget", "-q", "-O", "/dev/null",
                                                               "--header", "Host: stage.namicash.invalid",
                                                               "http://127.0.0.1:8080/api/v1/auth/recovery-info"]}}},
            "networks": {"app": {"internal": True}, "database": {"name": self.c.db_network},
                         "gateway": {"name": self.c.gateway_network}}})):
            with self.assertRaisesRegex(bg.Error, "database endpoint"):
                self.c.config_check("green", self.refs, self.root / "proxy.conf")
        self.env.write_text(self.env.read_text().replace("STAGING_ISOLATED=1", "STAGING_ISOLATED=0"))
        with self.assertRaisesRegex(bg.Error, "marker"):
            self.c.env_guard()

    def test_unhealthy_or_missing_upstream_blocks_promotion(self):
        with patch.object(self.c, "db_identity", return_value="db-id"), \
             patch.object(self.c, "slot_check", side_effect=bg.Error("green backend unhealthy")):
            with self.assertRaisesRegex(bg.Error, "unhealthy"):
                self.c.verify_candidate(self.state)
        self.state["slots"]["green"]["status"] = "prepared"
        with self.assertRaisesRegex(bg.Error, "not staged"):
            self.c.verify_candidate(self.state)

    def test_wrong_caddy_route_is_rejected(self):
        class Response:
            status = 200
            headers = {"X-Nami-Route": "blue", "X-Nami-Environment": "blue"}
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, *_): return b"<html></html>"
        with patch.object(bg.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(bg.Error, "wrong color"):
                self.c.route_probe("green")

    def test_failed_reload_restores_blue_and_history(self):
        self.c.snippet.parent.mkdir(parents=True)
        self.c.snippet.write_bytes(self.c.route_text("blue"))
        with patch.object(self.c, "schema_revision", return_value="test_revision"), \
             patch.object(self.c, "caddy_validate"), patch.object(self.c, "caddy_reload"), \
             patch.object(self.c, "route_probe"):
            with self.assertRaisesRegex(bg.Error, "promotion failed"):
                self.c.switch(self.state, "green", inject_failure="reload")
        self.assertEqual(self.c.snippet.read_bytes(), self.c.route_text("blue"))
        recovered = self.c.load()
        self.assertEqual(recovered["active"], "blue")
        self.assertEqual(recovered["phase"], "idle")
        self.assertIn("promotion-reverted", (self.c.state_dir / "events.jsonl").read_text())

    def test_interrupted_promotion_recovers_after_restart(self):
        self.c.snippet.parent.mkdir(parents=True)
        self.c.snippet.write_bytes(self.c.route_text("blue"))
        with patch.object(self.c, "schema_revision", return_value="test_revision"), \
             patch.object(self.c, "caddy_validate"), patch.object(self.c, "caddy_reload"), \
             patch.object(self.c, "route_probe"):
            with self.assertRaises(SystemExit):
                self.c.switch(self.state, "green", inject_failure="crash-after-reload")
        restarted = bg.Controller(SimpleNamespace(mode="staging", state_dir=str(self.c.state_dir),
                                                  env_file=str(self.env), managed_dir=None,
                                                  gateway_file=None, schema_attestation=None))
        saved = restarted.load()
        self.assertEqual(saved["phase"], "promoting")
        with patch.object(restarted, "db_identity"), patch.object(restarted, "slot_check"), \
             patch.object(restarted, "caddy_validate"), patch.object(restarted, "caddy_reload"), \
             patch.object(restarted, "route_probe"):
            self.assertEqual(restarted.rollback(saved), "blue")
        self.assertEqual(restarted.load()["active"], "blue")
        self.assertEqual(restarted.snippet.read_bytes(), restarted.route_text("blue"))

    def test_locking_and_unauthorized_config(self):
        first = self.c.lock()
        self.addCleanup(first.close)
        with self.assertRaisesRegex(bg.Error, "holds the lock"):
            self.c.lock()
        self.c.gateway_file.write_text("{ admin unix//run/caddy-admin.sock }\n" + bg.IMPORT + "\n")
        self.c.snippet.parent.mkdir(parents=True)
        self.c.snippet.write_bytes(self.c.route_text("blue"))
        fake = {"NetworkSettings": {"Networks": {self.c.gateway_network: {}}},
                "Mounts": [{"Destination": "/etc/caddy/managed", "Source": str(self.c.managed_dir)}]}
        with patch.object(self.c, "inspect", return_value=fake), patch.object(self.c, "member"):
            with self.assertRaisesRegex(bg.Error, "dedicated NamiCash template"):
                self.c.gateway_guard(self.state)

    def test_rollback_cannot_promote_unapproved_candidate(self):
        with self.assertRaisesRegex(bg.Error, "no previous promoted environment"):
            self.c.rollback(self.state)

    def test_candidate_caddy_validation_precedes_route_change(self):
        self.c.snippet.parent.mkdir(parents=True)
        self.c.snippet.write_bytes(self.c.route_text("blue"))
        with patch.object(self.c, "caddy_validate", side_effect=bg.Error("invalid candidate")):
            with self.assertRaisesRegex(bg.Error, "invalid candidate"):
                self.c.switch(self.state, "green")
        self.assertEqual(self.c.snippet.read_bytes(), self.c.route_text("blue"))
        self.assertFalse(self.c.state_path.exists())

    def test_staging_database_network_rejects_foreign_container(self):
        foreign = {"Internal": True, "Containers": {"x": {"Name": "cashbook-mafunami-db-1"}}}
        with patch.object(self.c, "network", return_value=foreign):
            with self.assertRaisesRegex(bg.Error, "unexpected container"):
                self.c.db_identity()

    def test_initial_blue_id_change_blocks_promotion(self):
        self.state["slots"]["blue"]["kind"] = "legacy"
        self.state["baseline"]["blue_ids"] = {"backend": "original", "frontend": "original"}
        with patch.object(self.c, "db_identity", return_value="db-id"), \
             patch.object(self.c, "slot_check", return_value={"backend": "new", "frontend": "original"}):
            with self.assertRaisesRegex(bg.Error, "initial Blue"):
                self.c.baseline_check(self.state)

    def test_schema_compatibility_fail_closed(self):
        prod = bg.Controller(SimpleNamespace(mode="production", state_dir=str(self.root / "prod-state"),
                                             env_file=None, managed_dir=None, gateway_file=None,
                                             schema_attestation=None))
        with self.assertRaisesRegex(bg.Error, "attestation required"):
            prod.compatibility(self.state, self.refs)
        path = self.root / "attestation.json"
        path.write_text(json.dumps({"compatible": False, "revision": "rev1",
                                    "active_backend": self.refs["backend"],
                                    "candidate_backend": self.refs["backend"], "approved_by": "operator"}))
        prod.attestation = path
        with patch.object(prod, "schema_revision", return_value="rev1"):
            with self.assertRaisesRegex(bg.Error, "unknown"):
                prod.compatibility(self.state, self.refs)

    def test_resource_preflight_fails_closed(self):
        with patch.object(bg.Path, "read_text", return_value="MemAvailable: 100000 kB\n"), \
             patch.object(bg, "safe_run", return_value="2"), \
             patch.object(bg.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * 1024**3)):
            with self.assertRaisesRegex(bg.Error, "insufficient memory"):
                self.c.resource_check()
        with patch.object(bg.Path, "read_text", return_value="MemAvailable: 2000000 kB\n"), \
             patch.object(bg, "safe_run", return_value="30"), \
             patch.object(bg.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * 1024**3)):
            self.assertEqual(self.c.resource_check()["estimated_additional_mib"], 1024)
            with self.assertRaisesRegex(bg.Error, "2432 MiB required"):
                self.c.resource_check(staging_additional_mib=bg.STAGING_SETUP_MIB)
        with patch.object(bg.Path, "read_text", return_value="MemAvailable: 1800000 kB\n"), \
             patch.object(bg, "safe_run", return_value="30"), \
             patch.object(bg.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * 1024**3)):
            with self.assertRaisesRegex(bg.Error, "1792 MiB required"):
                self.c.resource_check()

    def test_production_resource_limits_unchanged(self):
        prod = bg.Controller(SimpleNamespace(mode="production", state_dir=str(self.root / "prod-state"),
                                             env_file=None, managed_dir=None, gateway_file=None,
                                             schema_attestation=None))
        with patch.object(bg.Path, "read_text", return_value="MemAvailable: 3000000 kB\n"), \
             patch.object(bg, "safe_run", return_value="30"), \
             patch.object(bg.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * 1024**3)):
            with self.assertRaisesRegex(bg.Error, "Docker load"):
                prod.resource_check()

    def test_finalize_never_targets_database(self):
        self.c.snippet.parent.mkdir(parents=True)
        self.c.snippet.write_bytes(self.c.route_text("blue"))
        args = SimpleNamespace(command="finalize", color="green", execute=True)
        with patch.object(self.c, "load", return_value=self.state), \
             patch.object(self.c, "gateway_guard"), patch.object(self.c, "route_probe"), \
             patch.object(self.c, "compose") as compose:
            self.c.execute(args)
        self.assertEqual(compose.call_args.args[-3:], ("stop", "frontend", "backend"))
        self.assertNotIn("db", compose.call_args.args)
        self.assertEqual(self.state["active"], "blue")


if __name__ == "__main__":
    unittest.main()

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bluegreen_deployment as bg
import release_deployment as release
import staging_evidence as evidence
import staging_validation as staging


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.refs = {s: repo + "@sha256:" + "a" * 64 for s, repo in release.REPOS.items()}
        self.manifest = {"version": "v1.2.3", "source_commit": "b" * 40,
                         "images": {s: {"name": repo, "digest": "sha256:" + "a" * 64,
                                        "architecture": "linux/amd64"}
                                    for s, repo in release.REPOS.items()}}
        self.env = self.root / "stage.env"
        self.env.write_text("STAGING_ISOLATED=1\nPOSTGRES_DB=namicash_stage\nPOSTGRES_USER=stage\n"
                            "POSTGRES_PASSWORD=stage_test\nDATABASE_URL=postgresql+psycopg://stage:stage_test@db:5432/namicash_stage\n"
                            "REGISTRATION_MODE=open\n")
        self.controller = bg.Controller(SimpleNamespace(mode="staging", state_dir=str(self.root / "state"),
                            env_file=str(self.env), managed_dir=None, gateway_file=None,
                            schema_attestation=None))

    def test_runner_guard_rejects_other_workflows(self):
        guard = Path(__file__).resolve().parents[1] / "scripts/staging_runner_guard.sh"
        env = {**os.environ, "GITHUB_REPOSITORY": "Mafunamiii/Cashbook-mafunami",
               "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
               "GITHUB_WORKFLOW_REF": "Mafunamiii/Cashbook-mafunami/.github/workflows/staging-validation.yml@refs/heads/main",
               "GITHUB_JOB": "rehearse"}
        self.assertEqual(subprocess.run(("bash", str(guard)), env=env).returncode, 0)
        env["GITHUB_WORKFLOW_REF"] = "Mafunamiii/Cashbook-mafunami/.github/workflows/ci.yml@refs/heads/main"
        self.assertNotEqual(subprocess.run(("bash", str(guard)), env=env).returncode, 0)

    def test_workflow_runs_only_on_manual_trusted_staging_runner(self):
        workflow = (Path(__file__).resolve().parents[1] /
                    ".github/workflows/staging-validation.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("  push:", workflow)
        self.assertIn("runs-on: [self-hosted, Linux, X64, namicash, legion-staging]", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertNotIn("--mode production", workflow)

    def test_wrong_ref_and_invalid_manifest_fail_before_docker(self):
        with self.assertRaisesRegex(bg.Error, "trusted main"):
            staging.check_ref("refs/heads/feature")
        path = self.root / "manifest.json"
        path.write_text(json.dumps(self.manifest).replace("sha256:", "latest:"))
        with self.assertRaises(release.SafetyError):
            release.manifest(path)

    def test_missing_docker_and_memory_fail_closed(self):
        with patch.object(staging.platform, "machine", return_value="x86_64"), \
             patch.object(staging.shutil, "which", return_value=None):
            with self.assertRaisesRegex(bg.Error, "Docker CLI missing"):
                staging.preflight(self.controller)
        with patch.object(bg.Path, "read_text", return_value="MemAvailable: 100000 kB\n"), \
             patch.object(bg, "safe_run", return_value="0"), \
             patch.object(bg.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * 1024**3)):
            with self.assertRaisesRegex(bg.Error, "insufficient memory"):
                self.controller.resource_check(staging_additional_mib=bg.STAGING_SETUP_MIB)

    def test_remote_docker_and_production_network_rejected(self):
        with patch.object(staging.platform, "machine", return_value="x86_64"), \
             patch.object(staging.shutil, "which", return_value="/usr/bin/docker"), \
             patch.dict(staging.os.environ, {"DOCKER_HOST": "tcp://production:2375"}):
            with self.assertRaisesRegex(bg.Error, "remote Docker"):
                staging.preflight(self.controller)
        with patch.object(staging.platform, "machine", return_value="x86_64"), \
             patch.object(staging.shutil, "which", return_value="/usr/bin/docker"), \
             patch.object(staging, "run", side_effect=("default", "unix:///var/run/docker.sock", "v2", "27")), \
             patch.object(staging, "docker_inspect", return_value={"Name": "namicash-db-access"}), \
             patch.dict(staging.os.environ, {"DOCKER_HOST": "", "DOCKER_CONTEXT": ""}):
            with self.assertRaisesRegex(bg.Error, "production Docker network"):
                staging.preflight(self.controller)

    def test_production_credentials_rejected(self):
        self.env.write_text(self.env.read_text() + "CLOUDFLARE_TOKEN=secret\n")
        with self.assertRaisesRegex(bg.Error, "credentials"):
            self.controller.env_guard()

    def test_database_driver_and_credentials_checked_before_docker(self):
        valid = self.env.read_text()
        for url in (
            "postgresql://stage:stage_test@db:5432/namicash_stage",
            "postgresql+psycopg2://stage:stage_test@db:5432/namicash_stage",
            "postgresql+psycopg://stage:wrong_secret@db:5432/namicash_stage",
            "postgresql+psycopg://stage:stage_test@other:5432/namicash_stage",
        ):
            with self.subTest(url=url), patch.object(bg, "safe_run") as docker:
                self.env.write_text(valid.replace(
                    "postgresql+psycopg://stage:stage_test@db:5432/namicash_stage", url))
                with self.assertRaisesRegex(bg.Error, "staging database URL") as caught:
                    self.controller.staging_migrate(self.refs["backend"])
                self.assertNotIn("wrong_secret", str(caught.exception))
                docker.assert_not_called()
        for extra in ("POSTGRES_PASSWORD=stage_other\n", "POSTGRES_DB=other\n",
                      "POSTGRES_USER=other\n", "DATABASE_URL=postgresql://stage:stage_test@db:5432/namicash_stage\n"):
            with self.subTest(extra=extra), patch.object(bg, "safe_run") as docker:
                self.env.write_text(valid + extra)
                with self.assertRaises(bg.Error):
                    self.controller.staging_migrate(self.refs["backend"])
                docker.assert_not_called()

    def test_staging_diagnostics_identify_operation_without_docker_output(self):
        secret = "stage_sensitive_token"
        for args, label in (
            (["docker", "run", "--entrypoint", "alembic", "image", "upgrade", "head"], "staging migration"),
            (["docker", "exec", "gateway", "caddy", "reload"], "Caddy reload"),
            (["docker", "compose", "up", "backend"], "container up backend"),
        ):
            with self.subTest(label=label), patch.object(bg.legacy.subprocess, "run", return_value=SimpleNamespace(
                    returncode=1, stdout=secret, stderr=f"DATABASE_URL={secret}")):
                with self.assertRaisesRegex(bg.Error, label) as caught:
                    bg.safe_run(args)
                self.assertNotIn(secret, str(caught.exception))

    def test_staging_compose_ignores_inherited_production_values(self):
        with patch.dict(os.environ, {"POSTGRES_DB": "production", "POSTGRES_PASSWORD": "production-secret",
                                    "DATABASE_URL": "postgresql://prod@production/db",
                                    "SENTRY_BACKEND_DSN": "https://production.invalid/1"}):
            env = self.controller.compose_env("blue", self.refs, self.root / "blue.conf")
        self.assertEqual(env["POSTGRES_DB"], "namicash_stage")
        self.assertEqual(env["POSTGRES_PASSWORD"], "stage_test")
        self.assertEqual(env["DATABASE_URL"],
                         "postgresql+psycopg://stage:stage_test@db:5432/namicash_stage")
        self.assertEqual(env["SENTRY_BACKEND_DSN"], "")

    def test_staging_migration_never_runs_in_production(self):
        prod = bg.Controller(SimpleNamespace(mode="production", state_dir=str(self.root / "prod"),
                  env_file=None, managed_dir=None, gateway_file=None, schema_attestation=None))
        with self.assertRaisesRegex(bg.Error, "staging-only"):
            prod.staging_migrate(self.refs["backend"])

    def test_cleanup_refuses_unrelated_identity_and_surfaces_failure(self):
        report = self.root / "reports"
        report.mkdir()
        foreign = {"Name": "/namicash-bg-stage-blue-backend-1",
                   "Config": {"Labels": {"com.docker.compose.project": "production"}}}
        with patch.object(staging, "docker_inspect", side_effect=lambda kind, name: foreign if name.endswith("blue-backend-1") else None):
            with self.assertRaisesRegex(bg.Error, "unexpected container"):
                staging.cleanup(self.controller, report)
        owned = {"Name": "/namicash-bg-stage-blue-backend-1",
                 "Config": {"Labels": {"com.docker.compose.project": "namicash-bg-stage-blue",
                                       "com.docker.compose.service": "backend"}}}
        with patch.object(staging, "docker_inspect", side_effect=lambda kind, name: owned if name.endswith("blue-backend-1") else None), \
             patch.object(staging, "run", side_effect=bg.Error("remove failed")), \
             patch.object(staging.subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
            with self.assertRaisesRegex(bg.Error, "remove failed"):
                staging.cleanup(self.controller, report)

    def test_evidence_digest_and_staleness(self):
        report = {"overall": "PASS", "mode": "release", "controller_commit": "c" * 40,
                  "promotion": "PASS", "rollback": "PASS", "schema_compatibility": {"result": "PASS"},
                  "tests": {step: "PASS" for step in evidence.REQUIRED_TESTS}, "run_id": "123-1",
                  "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "releases": {"blue": self.manifest, "green": self.manifest}}
        evidence.validate_report(report, blue=self.manifest, green=self.manifest, controller_sha="c" * 40)
        report["releases"]["green"] = json.loads(json.dumps(self.manifest))
        report["releases"]["green"]["images"]["backend"]["digest"] = "sha256:" + "d" * 64
        with self.assertRaisesRegex(evidence.EvidenceError, "digest"):
            evidence.validate_report(report, blue=self.manifest, green=self.manifest, controller_sha="c" * 40)
        report["releases"]["green"] = self.manifest
        report["completed_at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=4)).isoformat()
        with self.assertRaisesRegex(evidence.EvidenceError, "stale"):
            evidence.validate_report(report, blue=self.manifest, green=self.manifest, controller_sha="c" * 40)

    def test_report_preserves_release_and_failure_evidence(self):
        report = {"mode": "infrastructure", "run_id": "123-2",
                  "workflow_run": "https://github.com/Mafunamiii/Cashbook-mafunami/actions/runs/123/attempts/2",
                  "release_runs": {"blue": "45", "green": "45"},
                  "controller_commit": "c" * 40,
                  "releases": {"blue": self.manifest, "green": self.manifest},
                  "tests": {"promotion and Green route": "FAIL", "scoped cleanup": "PASS"},
                  "promotion": "NOT_RUN", "rollback": "NOT_RUN",
                  "schema_compatibility": {"result": "PASS", "cross_version_tested": False},
                  "error": "Caddy reload: docker exec failed (exit 1)"}
        staging.write_report(report, self.root / "report")
        saved = json.loads((self.root / "report/staging-report.json").read_text())
        summary = (self.root / "report/staging-report.md").read_text()
        self.assertEqual(saved["overall"], "FAIL")
        self.assertFalse(saved["schema_compatibility"]["cross_version_tested"])
        self.assertIn("selected run: 45", summary)
        self.assertIn("Caddy reload", summary)
        self.assertIn("Cleanup: PASS", summary)

    def test_schema_compatibility_requires_candidate_head(self):
        with patch.object(self.controller, "schema_revision", return_value="old"), \
             patch.object(self.controller, "image_schema_head", return_value="new"):
            with self.assertRaisesRegex(bg.Error, "schema"):
                self.controller.compatibility({}, self.refs)


if __name__ == "__main__":
    unittest.main()

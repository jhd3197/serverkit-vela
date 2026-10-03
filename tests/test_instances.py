"""Instance lifecycle: validation, the deploy flow with the panel's deploy
seam stubbed, and delete/action behavior.

The panel's own services are stubbed exactly at the seams the plugin calls —
``ManifestApplyService.apply`` (the serverkit.yaml import path),
``DeploymentJobService.enqueue_app_deploy`` (the async build), the
suspend/purge pair (delete) and the application lifecycle service
(start/stop/restart) — so these tests exercise the plugin's logic against
the real panel app without docker, git clones or builds.

Skips cleanly when the ServerKit checkout is absent (see test_blueprint_auth).
Run with: python -m unittest discover -s tests
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_blueprint_auth import (  # noqa: E402  (shared harness)
    BACKEND, PLUGIN_PKG, ROOT, create_access_token, db, generate_password_hash,
    load_plugin, create_app, InstalledPlugin, User,
)

if not (BACKEND / "app" / "__init__.py").is_file():
    raise unittest.SkipTest(
        f"ServerKit backend not found at {BACKEND} (set SERVERKIT_BACKEND)")

from app.models.application import Application  # noqa: E402
from app.models.application_manifest import ApplicationManifest  # noqa: E402
from app.models.project import Project  # noqa: E402
from app.models.server import Server  # noqa: E402


def _fake_apply_success(project, normalized, user_id=None, environment=None,
                        manifest_row=None):
    """Stand-in for ManifestApplyService.apply: records the app row the real
    create_app step would, and reports success."""
    service = normalized["services"][0]
    app = Application(
        name=service["name"], app_type="docker", status="stopped",
        port=service.get("port"), user_id=user_id, project_id=project.id)
    db.session.add(app)
    db.session.commit()
    return {"success": True, "job_id": "apply-job-1", "applied": 4,
            "issues": [], "results": []}


class InstanceLifecycleTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app("testing")
        with cls.app.app_context():
            db.create_all()
        load_plugin(cls.app)
        cls.client = cls.app.test_client()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        db.session.add(InstalledPlugin(
            name="serverkit-vela", display_name="Vela", slug="serverkit-vela",
            version="0.1.0", status=InstalledPlugin.STATUS_ACTIVE,
            has_backend=True, url_prefix="/api/v1/vela", manifest={}))
        self.user = User(email="dev@t.local", username="dev",
                         password_hash=generate_password_hash("x"),
                         role="developer", is_active=True)
        db.session.add(self.user)
        db.session.commit()
        self.headers = {
            "Authorization": f"Bearer {create_access_token(identity=self.user.id)}"}
        self.vela_service = sys.modules[f"{PLUGIN_PKG}.vela_service"]

        apply_patch = mock.patch(
            "app.services.manifest_apply_service.ManifestApplyService.apply",
            side_effect=_fake_apply_success)
        deploy_patch = mock.patch(
            "app.services.deployment_job_service.DeploymentJobService"
            ".enqueue_app_deploy",
            return_value={"success": True, "job_id": "deploy-job-1"})
        self.mock_apply = apply_patch.start()
        self.mock_deploy = deploy_patch.start()
        self.addCleanup(apply_patch.stop)
        self.addCleanup(deploy_patch.stop)
        self.addCleanup(self.ctx.pop)

    def _create(self, body=None):
        return self.client.post("/api/v1/vela/instances",
                                json=body if body is not None else {"name": "Home"},
                                headers=self.headers)

    # -- the happy path ------------------------------------------------------

    def test_create_deploys_through_the_manifest_seam(self):
        resp = self._create({"name": "Home", "domain": "vela.example.com"})
        self.assertEqual(resp.status_code, 201, resp.get_json())
        payload = resp.get_json()
        instance = payload["instance"]
        self.assertEqual(instance["slug"], "vela-home")
        self.assertEqual(instance["domain"], "vela.example.com")
        self.assertEqual(payload["deploy_job_id"], "deploy-job-1")

        # The generated password is referenced, never returned.
        self.assertEqual(instance["initial_password"], {
            "vault": "manifest",
            "secret": "vela_home_vela_initial_password"})
        self.assertNotIn("value", instance["initial_password"])

        # The apply seam received the rendered recipe with repo provenance
        # stored on the manifest row (that's what lets the Dockerfile build
        # clone the Vela repo).
        self.assertEqual(self.mock_apply.call_count, 1)
        project, normalized = self.mock_apply.call_args.args[:2]
        self.assertEqual(project.slug, "vela-home")
        service = normalized["services"][0]
        self.assertEqual(service["name"], "vela-home")
        self.assertEqual(service["port"], 7700)
        self.assertEqual(service["healthcheck_path"], "/api/health")
        self.assertEqual(service["dockerfile_path"], "Dockerfile")
        env = {var["key"]: var for var in service["env_vars"]}
        self.assertEqual(env["VELA_DATA_DIR"]["value"], "/data")
        self.assertEqual(env["VELA_PUBLIC_ORIGIN"]["value"],
                         "https://vela.example.com")
        self.assertEqual(env["VELA_INITIAL_PASSWORD"]["source"], "generate")
        disk = service["disks"][0]
        self.assertEqual(disk["mount_path"], "/data")
        self.assertEqual(disk["size"], "4GB")
        self.assertEqual(disk["backup"], {"schedule": "daily", "retain": 7})
        self.assertEqual(normalized["domains"], [{
            "host": "vela.example.com", "service": "vela-home", "ssl": "auto"}])

        row = ApplicationManifest.query.filter_by(project_id=project.id).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.source_repo, self.vela_service.VELA_REPO_URL)

        # The build was enqueued for the app the apply created.
        self.assertEqual(self.mock_deploy.call_count, 1)

    def test_create_without_domain_has_no_origin_or_domain_block(self):
        resp = self._create({"name": "Work"})
        self.assertEqual(resp.status_code, 201, resp.get_json())
        instance = resp.get_json()["instance"]
        self.assertIsNone(instance["domain"])
        self.assertTrue(any("VELA_PUBLIC_ORIGIN" in w
                            for w in instance.get("warnings", [])))
        _project, normalized = self.mock_apply.call_args.args[:2]
        service = normalized["services"][0]
        env = {var["key"]: var for var in service["env_vars"]}
        self.assertEqual(env["VELA_PUBLIC_ORIGIN"]["source"], "placeholder")
        self.assertEqual(normalized["domains"], [])

    # -- validation ----------------------------------------------------------

    def test_bad_name_gets_400(self):
        resp = self._create({"name": "!!!"})
        self.assertEqual(resp.status_code, 400)
        resp = self._create({})
        self.assertEqual(resp.status_code, 400)

    def test_duplicate_name_gets_409(self):
        self.assertEqual(self._create().status_code, 201)
        resp = self._create({"name": "home"})  # case-insensitive slug
        self.assertEqual(resp.status_code, 409)

    def test_unknown_server_gets_400(self):
        resp = self._create({"name": "Fleet", "server_id": "no-such-server"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Unknown server", resp.get_json()["error"])

    def test_remote_server_is_refused_for_now(self):
        db.session.add(Server(name="fleet-1", hostname="10.0.0.2",
                              status="online", management_mode="managed"))
        db.session.commit()
        resp = self._create({"name": "Fleet", "server_id": "fleet-1"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("remote", resp.get_json()["error"])

    def test_observed_server_is_refused(self):
        db.session.add(Server(name="ro-1", hostname="10.0.0.3",
                              status="online", management_mode="observed"))
        db.session.commit()
        resp = self._create({"name": "Obs", "server_id": "ro-1"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("read-only", resp.get_json()["error"])

    def test_invalid_domain_gets_400(self):
        resp = self._create({"name": "Bad", "domain": "not a domain"})
        self.assertEqual(resp.status_code, 400)

    def test_apply_refusal_cleans_up_the_project(self):
        self.mock_apply.side_effect = lambda *a, **k: {
            "success": False, "refused": True,
            "blockers": [{"message": "panel host already has it bound"}],
            "issues": [], "results": []}
        resp = self._create({"name": "Blocked"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("bound", resp.get_json()["error"])
        self.assertIsNone(Project.query.filter_by(slug="vela-blocked").first())
        self.assertEqual(self.client.get("/api/v1/vela/instances",
                                         headers=self.headers).get_json(),
                         {"instances": []})

    # -- list / detail ---------------------------------------------------------

    def test_list_and_detail(self):
        self.assertEqual(self._create().status_code, 201)
        resp = self.client.get("/api/v1/vela/instances", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        (view,) = resp.get_json()["instances"]
        self.assertEqual(view["slug"], "vela-home")
        self.assertIn("status", view)
        self.assertIn("url", view)
        self.assertEqual(view["deploy"], {"job_id": "deploy-job-1", "status": None})

        resp = self.client.get("/api/v1/vela/instances/vela-home",
                               headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        detail = resp.get_json()["instance"]
        self.assertEqual(detail["initial_password"]["secret"],
                         "vela_home_vela_initial_password")

    # -- actions ---------------------------------------------------------------

    def test_start_stop_restart_use_the_panel_lifecycle(self):
        self.assertEqual(self._create().status_code, 201)
        for action in ("start", "stop", "restart"):
            with mock.patch(f"app.services.application_lifecycle_service"
                            f".{action}_application") as handler:
                resp = self.client.post(
                    f"/api/v1/vela/instances/vela-home/{action}",
                    headers=self.headers)
                self.assertEqual(resp.status_code, 200, resp.get_json())
                self.assertEqual(handler.call_count, 1)

    def test_action_on_unknown_instance_gets_404(self):
        resp = self.client.post("/api/v1/vela/instances/vela-ghost/start",
                                headers=self.headers)
        self.assertEqual(resp.status_code, 404)

    # -- delete ------------------------------------------------------------------

    def test_delete_requires_confirmation(self):
        self.assertEqual(self._create().status_code, 201)
        resp = self.client.delete("/api/v1/vela/instances/vela-home",
                                  headers=self.headers)
        self.assertEqual(resp.status_code, 400)

    def test_delete_suspends_and_purges_through_the_panel(self):
        self.assertEqual(self._create().status_code, 201)
        with mock.patch("app.services.application_restore.suspend_application",
                        return_value={}) as suspend, \
             mock.patch("app.services.recycle_bin_service.purge",
                        return_value=(True, None)) as purge:
            resp = self.client.delete(
                "/api/v1/vela/instances/vela-home?confirm=vela-home",
                headers=self.headers)
            self.assertEqual(resp.status_code, 200, resp.get_json())
            self.assertEqual(suspend.call_count, 1)
            purge.assert_called_once()
            self.assertEqual(purge.call_args.args[0], "application")
        self.assertIsNone(Project.query.filter_by(slug="vela-home").first())
        resp = self.client.get("/api/v1/vela/instances", headers=self.headers)
        self.assertEqual(resp.get_json(), {"instances": []})


if __name__ == "__main__":
    unittest.main()

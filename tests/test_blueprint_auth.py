"""Blueprint auth: the read routes accept a JWT *or* a scoped API key.

Reads use ``auth_required()`` + ``require_scope("servers:read")`` so a Vela
host can poll them with one scoped ServerKit key (``X-API-Key``); writes are
``@developer_required`` like the panel's own container routes. JWT callers
are unaffected, a key without the scope gets 403, no credentials get 401,
and a viewer gets 403 on writes.

These tests run against the real ServerKit app from the sibling checkout
(``SERVERKIT_BACKEND`` env overrides the default ``../ServerKit/backend``)
and skip cleanly when it isn't available — the same pattern serverkit-gui
and the panel's own extracted-plugin suites use.

Run with: python -m unittest discover -s tests
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ.get("SERVERKIT_BACKEND")
               or (ROOT.parent / "ServerKit" / "backend"))

if not (BACKEND / "app" / "__init__.py").is_file():
    raise unittest.SkipTest(
        f"ServerKit backend not found at {BACKEND} (set SERVERKIT_BACKEND)")

# Test-environment knobs must be set before the ServerKit app package imports.
os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("SERVERKIT_REGISTRY_URL", "")
_DB_FILE = os.path.join(
    tempfile.gettempdir(), f"serverkit_vela_test_{os.getpid()}.db").replace("\\", "/")
os.environ["TEST_DATABASE_URL"] = "sqlite:///" + _DB_FILE

sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)  # instance/config paths resolve relative to the backend

from app import create_app, db  # noqa: E402
from app.models import User  # noqa: E402
from app.models.plugin import InstalledPlugin  # noqa: E402
from app.services.api_key_service import ApiKeyService  # noqa: E402
from flask_jwt_extended import create_access_token  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

PLUGIN_PKG = "app.plugins.serverkit-vela"


def load_plugin(app):
    """Load this repo's backend as the installed plugin package and mount its
    blueprint at the manifest's prefix, mirroring a real install."""
    if PLUGIN_PKG not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PLUGIN_PKG, ROOT / "backend" / "__init__.py",
            submodule_search_locations=[str(ROOT / "backend")])
        module = importlib.util.module_from_spec(spec)
        sys.modules[PLUGIN_PKG] = module
        spec.loader.exec_module(module)
    vela_bp = sys.modules[PLUGIN_PKG].vela_bp
    if vela_bp.name not in app.blueprints:
        app.register_blueprint(vela_bp, url_prefix="/api/v1/vela")


class BlueprintAuthTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app("testing")
        with cls.app.app_context():
            db.create_all()
        load_plugin(cls.app)
        cls.client = cls.app.test_client()
        cls.manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        plugin = InstalledPlugin(
            name="serverkit-vela",
            display_name=self.manifest.get("display_name", "Vela"),
            slug="serverkit-vela", version=self.manifest.get("version", "0.0.0"),
            status=InstalledPlugin.STATUS_ACTIVE, has_backend=True,
            url_prefix="/api/v1/vela", manifest=self.manifest)
        db.session.add(plugin)
        self.developer = User(email="dev@t.local", username="dev",
                              password_hash=generate_password_hash("x"),
                              role="developer", is_active=True)
        self.viewer = User(email="view@t.local", username="view",
                           password_hash=generate_password_hash("x"),
                           role="viewer", is_active=True)
        db.session.add_all([self.developer, self.viewer])
        db.session.commit()
        self.addCleanup(self.ctx.pop)

    def _api_key_headers(self, scopes, user=None):
        _, raw_key = ApiKeyService.create_key(
            (user or self.developer).id, name="poll", scopes=scopes)
        return {"X-API-Key": raw_key}

    def _jwt_headers(self, user=None):
        return {"Authorization": f"Bearer {create_access_token(identity=(user or self.developer).id)}"}

    # (a) a key with servers:read reaches both read routes
    def test_scoped_api_key_gets_200_on_read_routes(self):
        headers = self._api_key_headers(["servers:read"])
        resp = self.client.get("/api/v1/vela/instances", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json(), {"instances": []})

        resp = self.client.get("/api/v1/vela/instances/vela-nope", headers=headers)
        self.assertEqual(resp.status_code, 404)  # past auth, unknown instance

    # (b) a key without the scope is refused before the handler runs
    def test_api_key_without_the_scope_gets_403(self):
        headers = self._api_key_headers(["databases:read"])
        resp = self.client.get("/api/v1/vela/instances", headers=headers)
        self.assertEqual(resp.status_code, 403)

    # (c) JWT callers are unaffected
    def test_jwt_caller_gets_200(self):
        resp = self.client.get("/api/v1/vela/instances", headers=self._jwt_headers())
        self.assertEqual(resp.status_code, 200, resp.get_json())

    # (d) no credentials at all
    def test_unauthenticated_gets_401(self):
        self.assertEqual(self.client.get("/api/v1/vela/instances").status_code, 401)
        self.assertEqual(self.client.post("/api/v1/vela/instances", json={}).status_code, 401)
        self.assertEqual(self.client.delete("/api/v1/vela/instances/vela-x").status_code, 401)

    # (e) writes need the developer role: a viewer JWT is a 403, not a 2xx
    def test_viewer_is_refused_on_writes(self):
        headers = self._jwt_headers(user=self.viewer)
        resp = self.client.post("/api/v1/vela/instances",
                                json={"name": "Home"}, headers=headers)
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post("/api/v1/vela/instances/vela-x/start",
                                headers=headers)
        self.assertEqual(resp.status_code, 403)
        resp = self.client.delete("/api/v1/vela/instances/vela-x",
                                  headers=headers)
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()

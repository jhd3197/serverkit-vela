"""Vela instance registry.

An instance is one ServerKit managed app deployed from the Vela repo's
``serverkit.yaml`` recipe, plus the metadata that ties it back to a name, a
server and a domain. The metadata lives in the plugin's own key/value store
(``plugins_sdk.store``); everything heavier — the app row, env vars, the
generated password, the disk, the backup policy, the vhost — is owned by the
panel's manifest/deploy machinery, never by raw docker calls here.
"""
import re
from datetime import datetime

from app import db
from app.plugins_sdk import logger, store

PLUGIN_SLUG = 'serverkit-vela'

#: Where instances are cloned and built from. The recipe (``serverkit.yaml``)
#: below mirrors this repo's own file verbatim; the manifest row's provenance
#: (source_repo/source_ref) is what lets the panel's apply clone it.
VELA_REPO_URL = 'https://github.com/jhd3197/vela'
VELA_REPO_BRANCH = 'main'

#: VELA_TRUSTED_PROXIES default: the docker bridge gateway, which is where a
#: host nginx proxy appears from inside the container (see vela docs/SERVER.md).
DEFAULT_TRUSTED_PROXIES = '172.17.0.1'

_STORE_KEY = 'instances'
_SLUG_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,61}$')
_HOST_RE = re.compile(r'^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?'
                      r'(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$')

log = logger(__name__)


def _store():
    return store.for_plugin(PLUGIN_SLUG)


def _registry():
    value = _store().get(_STORE_KEY)
    return dict(value) if isinstance(value, dict) else {}


def _save_registry(registry):
    _store().set(_STORE_KEY, registry)


def get_instance(slug):
    return _registry().get(slug)


def put_instance(instance):
    registry = _registry()
    registry[instance['slug']] = instance
    _save_registry(registry)
    return instance


def remove_instance(slug):
    registry = _registry()
    existed = registry.pop(slug, None) is not None
    if existed:
        _save_registry(registry)
    return existed


def slugify(name):
    """'Home' -> 'vela-home'. DNS-safe; also the app, project and disk name."""
    base = re.sub(r'[^a-z0-9]+', '-', (name or '').strip().lower()).strip('-')
    base = re.sub(r'-{2,}', '-', base)[:50].strip('-')
    if not base:
        return None
    return f'vela-{base}'


def normalize_domain(raw):
    """Bare lowercase hostname from a host or URL, or None when absent."""
    host = (raw or '').strip().lower()
    if '://' in host:
        host = host.split('://', 1)[1]
    host = host.split('/', 1)[0].split(':', 1)[0].strip().strip('.')
    return host or None


def valid_domain(host):
    return bool(host) and bool(_HOST_RE.match(host))


def generated_secret_name(slug):
    """The vault secret the recipe's ``generate: true`` produces for an instance.

    Mirrors ``ManifestApplyService._generated_secret_name``: the service name
    and env key, lowercased, non-alphanumerics folded to underscores.
    """
    return re.sub(r'[^a-z0-9]+', '_', f'{slug}_VELA_INITIAL_PASSWORD'.lower()).strip('_')


def _load_app(instance):
    from app.models.application import Application
    app_id = instance.get('app_id')
    if not app_id:
        return None
    return Application.query_active().filter_by(id=app_id).first()


def _live_status(instance, app):
    """Best-effort live status: deploy job first, then containers, then the row."""
    if app is None:
        return 'missing'
    job_id = instance.get('deploy_job_id')
    if job_id:
        try:
            from app.models.deployment_job import DeploymentJob
            job = DeploymentJob.query.get(job_id)
            if job is not None and job.status in ('pending', 'running', 'waiting'):
                return 'deploying'
        except Exception:
            db.session.rollback()
    try:
        from app.services import container_status_service
        status = container_status_service.get_app_status(app.id).get('status')
        if status and status != 'unknown':
            return status
    except Exception:
        pass
    return app.status or 'unknown'


def _instance_url(app):
    if app is None:
        return None
    try:
        domains = app.live_domains
    except Exception:
        return None
    for domain in domains:
        if domain.name:
            return f'https://{domain.name}'
    return None


def instance_view(instance, app=None, detail=False):
    """The API shape for one instance. Never includes secret values."""
    if app is None and instance.get('app_id'):
        app = _load_app(instance)
    view = {
        'slug': instance['slug'],
        'name': instance.get('name'),
        'server_id': instance.get('server_id'),
        'server_name': instance.get('server_name'),
        'domain': instance.get('domain'),
        'app_id': instance.get('app_id'),
        'project_id': instance.get('project_id'),
        'created_at': instance.get('created_at'),
        'status': _live_status(instance, app),
        'url': _instance_url(app),
    }
    job_id = instance.get('deploy_job_id')
    if job_id:
        view['deploy'] = {'job_id': job_id, 'status': None}
        try:
            from app.models.deployment_job import DeploymentJob
            job = DeploymentJob.query.get(job_id)
            if job is not None:
                view['deploy']['status'] = job.status
        except Exception:
            db.session.rollback()
    if detail:
        view['initial_password'] = {
            'vault': 'manifest',
            'secret': generated_secret_name(instance['slug']),
        }
        view['disk'] = _disk_info(app)
        view['backup'] = _backup_info(app)
        if not instance.get('domain'):
            view.setdefault('warnings', []).append(
                'No domain attached: Vela requires VELA_PUBLIC_ORIGIN and '
                'VELA_TRUSTED_PROXIES and refuses to start without them. '
                'Attach a domain to the managed app and set VELA_PUBLIC_ORIGIN '
                'before starting this instance.')
    return view


def _disk_info(app):
    if app is None:
        return None
    try:
        for volume in (app.volumes or []):
            if volume.mount_path == '/data':
                return {
                    'name': volume.name,
                    'mount_path': volume.mount_path,
                    'declared_size': getattr(volume, 'declared_size', None),
                }
    except Exception:
        return None
    return None


def _backup_info(app):
    if app is None:
        return None
    try:
        from app.models.backup_policy import BackupPolicy
        policy = BackupPolicy.query.filter_by(
            target_type='files', target_id=app.id, enabled=True).first()
        if policy is None:
            return None
        return {
            'schedule_cron': policy.schedule_cron,
            'retention_count': policy.retention_count,
        }
    except Exception:
        db.session.rollback()
        return None


def list_instance_views():
    return [instance_view(instance) for instance in _registry().values()]


# ---------------------------------------------------------------------------
# Lifecycle: create / delete / start / stop / restart
# ---------------------------------------------------------------------------

#: The Vela deploy recipe, mirroring vela/serverkit.yaml verbatim with the
#: project, service and disk names templated per instance. VELA_PUBLIC_ORIGIN
#: and the domains block are only rendered when a domain is given.
RECIPE_TEMPLATE = """\
# yaml-language-server: $schema=https://serverkit.ai/serverkit-yaml.schema.json
version: 1
project: {slug}

services:
  - name: {slug}
    type: docker
    dockerfilePath: Dockerfile
    port: 7700
    healthCheckPath: /api/health
    autoDeploy: false
    envVars:
      - key: VELA_DATA_DIR
        value: /data
      # Set the exact browser address, e.g. https://vela.example.com (no slash).
      - key: VELA_PUBLIC_ORIGIN{origin_line}
      # IP of ServerKit's proxy as seen inside the container; see docs/SERVER.md.
      - key: VELA_TRUSTED_PROXIES
        value: "{trusted_proxies}"
      # First-start password only. Retrieve it from ServerKit's secret vault.
      - key: VELA_INITIAL_PASSWORD
        generate: true
    disks:
      - name: {slug}-data
        mountPath: /data
        size: 4GB
        backup:
          schedule: daily
          retain: 7
{domains_block}"""

_DOMAINS_BLOCK = """
domains:
  - host: {domain}
    service: {slug}
    ssl: auto
"""


class InstanceError(ValueError):
    """Validation failure safe to show the caller. Carries an HTTP status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def build_recipe(slug, domain=None, trusted_proxies=DEFAULT_TRUSTED_PROXIES):
    """Render the per-instance serverkit.yaml text."""
    origin_line = f'\n        value: "https://{domain}"' if domain else ''
    domains_block = _DOMAINS_BLOCK.format(domain=domain, slug=slug) if domain else ''
    return RECIPE_TEMPLATE.format(
        slug=slug, origin_line=origin_line,
        trusted_proxies=trusted_proxies, domains_block=domains_block)


def _resolve_target(server_id):
    """Validate the requested deploy target.

    Returns (server_key, server_name): ``(None, 'This server')`` for the panel
    host, or the Server's name for a fleet target. Raises InstanceError for an
    unknown id, an observed (read-only) server, or a remote target — the
    panel's appliance apply only runs Dockerfile builds on the panel host
    today (remote dispatch is a later phase), and we refuse up front instead
    of half-creating a project.
    """
    from app.models.server import Server
    raw = (str(server_id).strip() if server_id is not None else '')
    if raw in ('', 'local'):
        return None, 'This server'
    server = (Server.query.filter_by(id=raw).first()
              or Server.query.filter_by(name=raw).first())
    if server is None:
        raise InstanceError(f'Unknown server: {raw}')
    if not server.is_managed:
        raise InstanceError(
            f'{server.name} is an observed (read-only) server — ServerKit will '
            'not deploy to it. Switch it to managed, or pick the panel host.')
    raise InstanceError(
        f'{server.name} is a remote server — deploying Vela to a fleet server '
        'is not supported yet (the panel only runs Dockerfile builds on the '
        'panel host). Pick "This server" for now.')


def _app_name_clash(slug):
    from app.models.application import Application
    # NOT query_active: a tombstone keeps reserving its name and directory.
    return Application.query.filter_by(name=slug, server_id=None).first() is not None


def create_instance(user, name, server_id=None, domain=None):
    """Deploy one Vela instance through the panel's manifest machinery.

    Flow: validate -> per-instance Project -> store the rendered serverkit.yaml
    (with repo provenance, so the Dockerfile build can clone) -> manifest apply
    (creates the managed app, clones the repo, sets env, generates the
    first-start password into the secret vault, ensures the 4 GB disk and its
    daily backup policy, attaches the domain) -> enqueue the async deploy job.
    """
    display = (name or '').strip()
    slug = slugify(display)
    if not slug or not _SLUG_RE.match(slug):
        raise InstanceError(
            'A name is required (letters, numbers and dashes; e.g. "Home")')
    if get_instance(slug) is not None:
        raise InstanceError(f'An instance named "{display}" already exists', status=409)
    if _app_name_clash(slug):
        raise InstanceError(
            f'The name {slug} is already taken by another app on this panel',
            status=409)

    host = normalize_domain(domain)
    if domain and not host:
        raise InstanceError('Invalid domain')
    if host and not valid_domain(host):
        raise InstanceError(f'Invalid domain: {host}')

    server_key, server_name = _resolve_target(server_id)

    from app.services.manifest_spec_service import ManifestSpecService, ManifestError
    recipe_text = build_recipe(slug, domain=host)
    try:
        normalized = ManifestSpecService.normalize_text(recipe_text)
    except ManifestError as exc:  # pragma: no cover - the template is fixed
        raise InstanceError(f'Recipe failed to validate: {"; ".join(exc.errors)}')

    from app.models.project import Project
    from app.services.workspace_service import WorkspaceService
    workspace = WorkspaceService.ensure_default_workspace()
    project = Project(
        workspace_id=workspace.id,
        name=f'Vela: {display}',
        slug=slug,
        description='Vela instance managed by the serverkit-vela extension',
    )
    db.session.add(project)
    db.session.commit()

    from app.services.manifest_persistence_service import ManifestPersistenceService
    manifest_row = ManifestPersistenceService.store_manifest(
        project_id=project.id,
        normalized=normalized,
        raw_text=recipe_text,
        source_repo=VELA_REPO_URL,
        source_ref=VELA_REPO_BRANCH,
    )
    db.session.commit()

    from app.services.manifest_apply_service import ManifestApplyService
    result = ManifestApplyService.apply(
        project, normalized, user_id=user.id, manifest_row=manifest_row)

    if result.get('refused'):
        # Plan-time blocker (e.g. appliance guard): nothing was executed, so
        # roll the bookkeeping back rather than leaving an empty project.
        message = (result.get('blockers') or [{}])[0].get('message') \
            or 'The panel refused this deploy'
        _delete_project(project)
        raise InstanceError(message)

    app = _find_project_app(project, slug)

    instance = put_instance({
        'slug': slug,
        'name': display,
        'server_id': server_key or 'local',
        'server_name': server_name,
        'domain': host,
        'app_id': app.id if app else None,
        'project_id': project.id,
        'deploy_job_id': None,
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'created_by': user.id,
    })

    if not result.get('success'):
        failure = next((r for r in result.get('results', [])
                        if r.get('status') == 'error'), {})
        raise InstanceError(
            f'The manifest apply failed: {failure.get("error") or "unknown step"}. '
            f'The partial instance "{slug}" was kept so you can inspect it in '
            'the panel; delete it and retry.', status=502)

    deploy_job_id = None
    if app is not None:
        from app.services.deployment_job_service import DeploymentJobService
        deploy = DeploymentJobService.enqueue_app_deploy(
            app, user_id=user.id, trigger='install')
        if deploy.get('success'):
            deploy_job_id = deploy.get('job_id')
            instance['deploy_job_id'] = deploy_job_id
            put_instance(instance)
        else:
            log.warning('%s: instance %s applied but deploy enqueue failed: %s',
                        PLUGIN_SLUG, slug, deploy.get('error'))

    return instance, deploy_job_id


def _find_project_app(project, slug):
    from app.models.application import Application
    return Application.query_active().filter_by(
        project_id=project.id, name=slug).first()


def _delete_project(project):
    """Best-effort removal of the per-instance project and its manifest row."""
    try:
        from app.models.application_manifest import ApplicationManifest
        ApplicationManifest.query.filter_by(project_id=project.id).delete()
        db.session.delete(project)
        db.session.commit()
    except Exception:
        db.session.rollback()
        log.warning('%s: failed to remove project %s', PLUGIN_SLUG, project.id)


def delete_instance(user, instance):
    """Remove the managed app (containers, vhost, disk) through the panel's
    own lifecycle: suspend (the reversible half) then purge with data removal
    — the same path `DELETE /api/v1/apps/<id>?purge=true` runs. Never docker.
    """
    from app.services import application_restore, recycle_bin_service
    app = _load_app(instance)
    cleanup = None
    warning = None
    if app is not None:
        cleanup = application_restore.suspend_application(app, user_id=user.id)
        app._purge_remove_data = True
        _ok, warning = recycle_bin_service.purge('application', app.id)

    project = None
    if instance.get('project_id'):
        from app.models.project import Project
        project = Project.query.get(instance['project_id'])
    if project is not None:
        _delete_project(project)

    remove_instance(instance['slug'])
    return {'cleanup': cleanup, 'warning': warning}


def app_action(user, instance, action):
    """start/stop/restart through the panel's application lifecycle service."""
    from app.services import application_lifecycle_service as lifecycle
    app = _load_app(instance)
    if app is None:
        raise InstanceError(
            'The managed app for this instance is gone — delete the instance '
            'and create it again', status=409)
    handler = {
        'start': lifecycle.start_application,
        'stop': lifecycle.stop_application,
        'restart': lifecycle.restart_application,
    }[action]
    try:
        handler(app, user_id=user.id)
    except lifecycle.ApplicationLifecycleError as exc:
        raise InstanceError(str(exc))
    return app

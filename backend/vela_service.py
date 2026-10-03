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

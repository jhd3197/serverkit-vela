"""Vela plugin — panel-side blueprint.

Exposes the instance registry: named Vela instances deployed as ServerKit
managed apps from the Vela repo's serverkit.yaml recipe. Reads accept a JWT
or a scoped API key (``servers:read``); writes follow the panel's developer
convention for app management (``@developer_required``, same as the panel's
own container routes).
"""
from flask import Blueprint, jsonify, request

from app.middleware.rbac import auth_required, developer_required, get_current_user
from app.middleware.api_scope_middleware import require_scope
from app.plugins_sdk import audit, logger

from . import vela_service

vela_bp = Blueprint('serverkit_vela', __name__)
log = logger(__name__)


def _instance_or_404(slug):
    instance = vela_service.get_instance(slug)
    if instance is None:
        return None, (jsonify({'error': 'Instance not found'}), 404)
    return instance, None


@vela_bp.route('/instances', methods=['GET'])
@auth_required()
@require_scope('servers:read')
def list_instances():
    """List every registered Vela instance with its live status and URL.

    API-key capable on purpose: a Vela host polls this with a scoped key.
    """
    return jsonify({'instances': vela_service.list_instance_views()}), 200


@vela_bp.route('/instances/<slug>', methods=['GET'])
@auth_required()
@require_scope('servers:read')
def get_instance(slug):
    """Instance detail: status, URL, vault reference for the generated
    first-start password (never the value), disk and backup info."""
    instance, err = _instance_or_404(slug)
    if err:
        return err
    return jsonify({'instance': vela_service.instance_view(instance, detail=True)}), 200


@vela_bp.route('/instances', methods=['POST'])
@developer_required
def create_instance():
    """Create and deploy a Vela instance: {server_id?, name, domain?}.

    The name is slugified dns-safe ("Home" -> vela-home). Deploy goes through
    the panel's own serverkit.yaml import path; the build itself runs as an
    async deployment job tracked on the instance.
    """
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        instance, deploy_job_id = vela_service.create_instance(
            user, data.get('name'),
            server_id=data.get('server_id'),
            domain=data.get('domain'))
    except vela_service.InstanceError as exc:
        return jsonify({'error': str(exc)}), exc.status

    audit('vela.instance.create', user_id=user.id, target_type='vela_instance',
          target_id=instance['slug'],
          details={'server_id': instance.get('server_id'),
                   'domain': instance.get('domain'),
                   'deploy_job_id': deploy_job_id})
    return jsonify({
        'instance': vela_service.instance_view(instance, detail=True),
        'deploy_job_id': deploy_job_id,
    }), 201


@vela_bp.route('/instances/<slug>', methods=['PATCH'])
@developer_required
def update_instance(slug):
    """Rename the instance and/or change its attached domain: {name?, domain?}.

    At least one key is required. ``domain: null`` (or an empty string)
    detaches the domain: the recipe is re-rendered and re-applied, the live
    Domain rows are removed and the app redeploys.
    """
    instance, err = _instance_or_404(slug)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if 'name' not in data and 'domain' not in data:
        return jsonify({'error': 'Nothing to update: pass name and/or domain'}), 400
    user = get_current_user()
    try:
        instance, changed = vela_service.update_instance(
            user, instance,
            name=data.get('name'),
            domain=(data['domain'] if 'domain' in data
                    else vela_service.DOMAIN_UNSET))
    except vela_service.InstanceError as exc:
        return jsonify({'error': str(exc)}), exc.status

    audit('vela.instance.update', user_id=user.id, target_type='vela_instance',
          target_id=slug, details=changed)
    return jsonify({'instance': vela_service.instance_view(instance, detail=True)}), 200


@vela_bp.route('/instances/<slug>/<action>', methods=['POST'])
@developer_required
def instance_action(slug, action):
    """start/stop/restart the instance's managed app."""
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'error': 'Unknown action'}), 404
    instance, err = _instance_or_404(slug)
    if err:
        return err
    user = get_current_user()
    try:
        vela_service.app_action(user, instance, action)
    except vela_service.InstanceError as exc:
        return jsonify({'error': str(exc)}), exc.status
    audit(f'vela.instance.{action}', user_id=user.id,
          target_type='vela_instance', target_id=slug)
    return jsonify({'instance': vela_service.instance_view(instance)}), 200


@vela_bp.route('/instances/<slug>', methods=['DELETE'])
@developer_required
def delete_instance(slug):
    """Delete an instance: managed app, disk and vhost, through the panel's
    lifecycle. Confirm-gated: body or query must carry ``confirm`` equal to
    the instance slug.
    """
    instance, err = _instance_or_404(slug)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    confirm = data.get('confirm') or request.args.get('confirm')
    if confirm != slug:
        return jsonify({
            'error': f'Type the instance name "{slug}" to confirm deletion'}), 400
    user = get_current_user()
    result = vela_service.delete_instance(user, instance)
    audit('vela.instance.delete', user_id=user.id,
          target_type='vela_instance', target_id=slug)
    return jsonify({'deleted': True, 'warning': result.get('warning')}), 200

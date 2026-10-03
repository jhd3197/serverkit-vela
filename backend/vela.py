"""Vela plugin — panel-side blueprint.

Exposes the instance registry: named Vela instances deployed as ServerKit
managed apps from the Vela repo's serverkit.yaml recipe. Reads accept a JWT
or a scoped API key (``servers:read``); writes follow the panel's developer
convention for app management.
"""
from flask import Blueprint, jsonify

from app.middleware.rbac import auth_required
from app.middleware.api_scope_middleware import require_scope
from app.plugins_sdk import logger

from . import vela_service

vela_bp = Blueprint('serverkit_vela', __name__)
log = logger(__name__)


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
    instance = vela_service.get_instance(slug)
    if instance is None:
        return jsonify({'error': 'Instance not found'}), 404
    return jsonify({'instance': vela_service.instance_view(instance, detail=True)}), 200

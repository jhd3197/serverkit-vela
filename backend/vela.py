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

vela_bp = Blueprint('serverkit_vela', __name__)
log = logger(__name__)


@vela_bp.route('/instances', methods=['GET'])
@auth_required()
@require_scope('servers:read')
def list_instances():
    """List every registered Vela instance (registry lands with the service)."""
    return jsonify({'instances': []}), 200

"""One credential source for every Plaid request; desktop never falls back to server keys."""
import os
import threading
from .config import settings

operation_lock = threading.RLock()
_desktop_credentials = None


def set_desktop_credentials(values):
    global _desktop_credentials
    if values is None:
        _desktop_credentials = None
        return
    if (not isinstance(values, dict) or values.get('environment') not in ('sandbox', 'production')
            or any(not isinstance(values.get(key), str) or not values[key].strip() or len(values[key]) > 256
                   for key in ('client_id', 'secret'))):
        raise ValueError('Invalid local Plaid configuration')
    _desktop_credentials = {key: values[key] for key in ('client_id', 'secret', 'environment')}


def credentials():
    if os.environ.get('PFOS_DESKTOP_RUNTIME') == '1':
        if not _desktop_credentials:
            raise ValueError('Configure your own Plaid credentials in Settings → Plaid on this computer.')
        return dict(_desktop_credentials)
    if not settings.plaid_client_id or not settings.plaid_secret:
        raise ValueError('Plaid is not configured on the server')
    return {'client_id': settings.plaid_client_id, 'secret': settings.plaid_secret, 'environment': settings.plaid_environment}


def host(values):
    return {'sandbox':'https://sandbox.plaid.com', 'production':'https://production.plaid.com',
            'development':'https://development.plaid.com'}[values['environment']]


def identity(values):
    return {'client_id': values['client_id'], 'environment': values['environment']}

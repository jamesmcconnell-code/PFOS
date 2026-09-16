"""Desktop Hosted Link. Browser callbacks only wake the UI; Plaid verifies results."""
from datetime import datetime, timedelta
import hashlib
import json
import os
import time
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import plaid_configuration
from .connectors import encrypt_credentials, decrypt_credentials
from .database import get_db
from .models import DataConnection, PlaidLinkSession

COMPLETION_URI = 'pfos://plaid-complete'
# Desktop runs one API process under an exclusive profile lock. Serialize duplicate
# polls, cancellation, and token exchange so a result is saved only once.
_lock = plaid_configuration.operation_lock


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def hosted_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == 'https' and parsed.netloc == 'secure.plaid.com'
            and parsed.path.startswith('/hl/') and not parsed.fragment)


def plaid_post(config, route, **values):
    try:
        response = httpx.post(plaid_configuration.host(config) + route,
            json={'client_id': config['client_id'], 'secret': config['secret'], **values}, timeout=30)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError()
        return body
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Plaid could not complete this request. Check your internet connection, credentials, and Hosted Link settings. Add pfos://plaid-complete to the allowed completion redirect URIs in your Plaid dashboard, then retry.') from None


def terminal(row, state, status, db):
    row.status = status
    # Retain only non-secret connection references once the flow ends.
    state = {key: state[key] for key in ('connections','mode','target_id','target_name') if key in state}
    row.encrypted_state = encrypt_credentials(state)
    db.commit()
    return state


def current_state(row, db):
    state = decrypt_credentials(row.encrypted_state)
    if row.status == 'pending':
        try:
            config = plaid_configuration.credentials()
        except ValueError as error:
            raise HTTPException(503, str(error)) from None
        if state['fingerprint'] != fingerprint(config):
            state = terminal(row, state, 'invalidated', db)
        elif datetime.utcnow() >= row.expires_at:
            state = terminal(row, state, 'expired', db)
    return state


def summary(row, state, *, include_url=False):
    can_reopen = row.status == 'pending' and time.time() < state.get('url_expires', 0)
    result = {'session_id': str(row.id), 'status': row.status,
              'can_reopen': can_reopen, 'connections': state.get('connections', []),
              'mode': state.get('mode','new'), 'target_id': state.get('target_id'), 'target_name': state.get('target_name')}
    if include_url and can_reopen:
        result['hosted_link_url'] = state['hosted_link_url']
    return result


def connection_state(connection):
    try: config = plaid_configuration.credentials()
    except ValueError:
        return {'plaid_state':'credentials_missing','can_sync':False,'reconnect_mode':None,
                'plaid_message':'Plaid is disabled. Add your credentials in Settings → Plaid. Imported history is preserved.'}
    try: saved = decrypt_credentials(connection.encrypted_credentials)
    except Exception: saved = {}
    if saved.get('plaid_identity') != plaid_configuration.identity(config):
        return {'plaid_state':'different_credentials','can_sync':False,'reconnect_mode':'new',
                'plaid_message':'This source belongs to different or unknown Plaid credentials. Restore its original Client ID and environment, or connect the bank separately with your current credentials. Existing history is preserved; a separate connection may import overlapping accounts and transactions.'}
    if not saved.get('access_token') or connection.status == 'new_connection_required':
        return {'plaid_state':'new_connection_required','can_sync':False,'reconnect_mode':'new',
                'plaid_message':'Connect this bank separately with your current credentials. Existing history is preserved; review overlapping accounts and transactions before syncing the new source.'}
    needs_login = connection.status == 'reauthorization_required'
    return {'plaid_state':'reauthorization_required' if needs_login else 'ready',
            'can_sync':not needs_login,'reconnect_mode':'update',
            'plaid_message':'Your bank needs authorization again. Reauthorize bank to keep the existing accounts and transaction history.' if needs_login else 'Connected with this installation’s Plaid account.'}


def replace_configuration(values, db):
    """Apply local credentials and permanently invalidate incompatible pending links."""
    with _lock:
        plaid_configuration.set_desktop_credentials(values)
        for row in db.scalars(select(PlaidLinkSession).where(PlaidLinkSession.status=='pending')).all():
            state = decrypt_credentials(row.encrypted_state)
            if values is None or state.get('fingerprint') != fingerprint(plaid_configuration.credentials()):
                terminal(row, state, 'invalidated', db)


def install_routes(app, current_user, household, next_connection_name):
    def desktop_user(user=Depends(current_user)):
        if os.environ.get('PFOS_DESKTOP_RUNTIME') != '1':
            raise HTTPException(404, 'Desktop bank authorization is unavailable here')
        return user

    def owned(session_id, user, db):
        db.expire_all()
        row = db.get(PlaidLinkSession, session_id)
        if not row or row.user_id != user.id or row.household_id != household(user, db):
            raise HTTPException(404, 'Bank authorization session not found')
        return row

    @app.get('/api/v1/connections/plaid/hosted')
    def active(user=Depends(desktop_user), db: Session=Depends(get_db)):
        with _lock:
            row = db.scalar(select(PlaidLinkSession).where(PlaidLinkSession.user_id == user.id,
                PlaidLinkSession.household_id == household(user, db)).order_by(PlaidLinkSession.created_at.desc()))
            return summary(row, current_state(row, db)) if row else {'status': 'idle'}

    @app.post('/api/v1/connections/plaid/hosted/start')
    def start(connection_id: UUID | None=None, user=Depends(desktop_user), db: Session=Depends(get_db)):
        with _lock:
            home = household(user, db)
            row = db.scalar(select(PlaidLinkSession).where(PlaidLinkSession.user_id == user.id,
                PlaidLinkSession.household_id == home, PlaidLinkSession.status == 'pending')
                .order_by(PlaidLinkSession.created_at.desc()))
            if row:
                state = current_state(row, db)
                if row.status == 'pending':
                    if connection_id and state.get('target_id') != str(connection_id):
                        raise HTTPException(409, 'Finish or cancel the pending bank authorization before starting another.')
                    return summary(row, state, include_url=True)
            try:
                config = plaid_configuration.credentials()
            except ValueError as error:
                raise HTTPException(503, str(error)) from None
            target = None
            product_options = {'products':['transactions']}
            if connection_id:
                target = db.get(DataConnection, connection_id)
                if not target or target.household_id != home or target.provider != 'plaid':
                    raise HTTPException(404, 'Bank connection not found')
                if connection_state(target)['reconnect_mode'] != 'update':
                    raise HTTPException(409, 'This source cannot be reauthorized with the current credentials. Restore the original Plaid account or connect the bank separately; existing history is preserved.')
                saved = decrypt_credentials(target.encrypted_credentials)
                product_options = {'access_token':saved['access_token']}
            created = datetime.utcnow()
            body = plaid_post(config, '/link/token/create', client_name='PFOS', language='en',
                country_codes=['US'], **product_options, user={'client_user_id': str(user.id)},
                hosted_link={'completion_redirect_uri': COMPLETION_URI,
                             'is_mobile_app': False, 'url_lifetime_seconds': 1800})
            if not hosted_url(body.get('hosted_link_url')) or not isinstance(body.get('link_token'), str):
                raise HTTPException(502, 'Plaid returned an unexpected Hosted Link response')
            state = {'fingerprint': fingerprint(config), 'link_token': body['link_token'],
                     'hosted_link_url': body['hosted_link_url'],
                     'url_expires': time.time() + 1800, 'connections': [], 'processed': []}
            if target:
                state.update(mode='update', target_id=str(target.id), target_name=target.name,
                             target_token_hash=hashlib.sha256(saved['access_token'].encode()).hexdigest())
            row = PlaidLinkSession(user_id=user.id, household_id=home, expires_at=created + timedelta(hours=6),
                                   encrypted_state=encrypt_credentials(state))
            db.add(row)
            db.commit()
            return summary(row, state, include_url=True)

    @app.post('/api/v1/connections/plaid/hosted/{session_id}/cancel')
    def cancel(session_id: UUID, user=Depends(desktop_user), db: Session=Depends(get_db)):
        with _lock:
            row = owned(session_id, user, db)
            state = decrypt_credentials(row.encrypted_state)
            if row.status == 'pending':
                state = terminal(row, state, 'cancelled', db)
            return summary(row, state)

    @app.post('/api/v1/connections/plaid/hosted/{session_id}/poll')
    def poll(session_id: UUID, user=Depends(desktop_user), db: Session=Depends(get_db)):
        with _lock:
            row = owned(session_id, user, db)
            state = current_state(row, db)
            if row.status != 'pending':
                return summary(row, state)
            target = None
            if state.get('mode') == 'update':
                target = db.get(DataConnection, UUID(state['target_id']))
                if not target or target.household_id != row.household_id:
                    return summary(row, terminal(row, state, 'invalidated', db))
                saved = decrypt_credentials(target.encrypted_credentials)
                if (connection_state(target)['reconnect_mode'] != 'update' or
                    hashlib.sha256(saved.get('access_token','').encode()).hexdigest() != state['target_token_hash']):
                    return summary(row, terminal(row, state, 'invalidated', db))
            now = time.time()
            if now - state.get('last_check', 0) < 5:
                return summary(row, state)
            config = plaid_configuration.credentials()
            # Persist throttling even if Plaid is temporarily unavailable.
            state['last_check'] = now
            row.encrypted_state = encrypt_credentials(state)
            db.commit()
            body = plaid_post(config, '/link/token/get', link_token=state['link_token'])
            sessions = body.get('link_sessions') or []
            if not isinstance(sessions, list):
                raise HTTPException(502, 'Plaid returned an unexpected authorization status')
            results = []
            exited = False
            updated = False
            for session in sessions:
                # OAuth handoffs can have no results yet. Never treat a redirect
                # or merely finished_at as success (or as cancellation).
                results.extend((session.get('results') or {}).get('item_add_results') or [])
                if session.get('on_success') is not None or any(event.get('event_name')=='HANDOFF' for event in session.get('events',[])):
                    updated = True
                legacy = session.get('on_success')
                if legacy and legacy.get('public_token'):
                    results.append({'public_token': legacy['public_token'],
                                    'institution': (legacy.get('metadata') or {}).get('institution')})
                exited = exited or bool(session.get('on_exit') or session.get('exit'))
            if target:
                if updated:
                    item = plaid_post(config, '/item/get', access_token=saved['access_token']).get('item')
                    if not isinstance(item,dict) or 'error' not in item or not item.get('item_id'):
                        raise HTTPException(502, 'Plaid could not verify the renewed bank authorization. Try checking again.')
                    if saved.get('item_id') and saved['item_id'] != item['item_id']:
                        raise HTTPException(502, 'Plaid returned a different bank item. Authorization was not changed.')
                    if item['error'] is not None:
                        raise HTTPException(422, 'Your bank still requires attention. Resume authorization in the browser and check again.')
                    target.status = 'active'
                    state['connections'] = [{'id':str(target.id),'name':target.name}]
                    return summary(row, terminal(row, state, 'complete', db))
                if exited:
                    return summary(row, terminal(row, state, 'cancelled', db))
                return summary(row, state)
            for result in results:
                public_token = result.get('public_token')
                if not isinstance(public_token, str) or not public_token:
                    continue
                token_id = hashlib.sha256(public_token.encode()).hexdigest()
                if token_id in state['processed']:
                    continue
                # Configuration replacement mid-request must not exchange a token
                # using the previous installation credentials.
                if fingerprint(plaid_configuration.credentials()) != state['fingerprint']:
                    return summary(row, terminal(row, state, 'invalidated', db))
                exchanged = plaid_post(config, '/item/public_token/exchange', public_token=public_token)
                if not isinstance(exchanged.get('access_token'), str) or not exchanged['access_token']:
                    raise HTTPException(502, 'Plaid returned an unexpected bank authorization response')
                name = str((result.get('institution') or {}).get('name') or 'Plaid bank')[:100]
                connection = DataConnection(household_id=row.household_id, provider='plaid',
                    name=next_connection_name(row.household_id, 'plaid', name, db),
                    encrypted_credentials=encrypt_credentials({'access_token': exchanged['access_token'],
                                                               'plaid_identity': plaid_configuration.identity(config),
                                                               'item_id': exchanged.get('item_id')}))
                db.add(connection)
                db.flush()
                state['processed'].append(token_id)
                state['connections'].append({'id': str(connection.id), 'name': connection.name})
                row.encrypted_state = encrypt_credentials(state)
                db.commit()
            if state['connections']:
                state = terminal(row, state, 'complete', db)
            elif exited:
                state = terminal(row, state, 'cancelled', db)
            return summary(row, state)

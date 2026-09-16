"""Hosted Link contracts with real migrated SQLite and synthetic Plaid HTTPS."""
from datetime import datetime, timedelta
import shutil
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app import plaid_configuration
from app.connectors import decrypt_credentials, encrypt_credentials
from app.database import create_database_engine, get_db
from app.main import app
from app.models import User, Household, HouseholdMember, PlaidLinkSession, DataConnection
from app.security import create_token

BASE='/api/v1/connections/plaid/hosted'
LOCAL={'client_id':'synthetic-client','secret':'synthetic-secret','environment':'sandbox'}


@pytest.fixture
def context(monkeypatch, tmp_path, migrated_template):
    monkeypatch.setenv('PFOS_DESKTOP_RUNTIME','1')
    plaid_configuration.set_desktop_credentials(LOCAL)
    file=tmp_path/'hosted.db';shutil.copyfile(migrated_template,file)
    engine=create_database_engine('sqlite:///'+str(file))
    with Session(engine) as db:
        home=Household(name='Hosted test');db.add(home);db.flush()
        users=[User(email=f'hosted-{i}@example.com',display_name=f'User {i}',password_hash='unused') for i in range(2)]
        db.add_all(users);db.flush()
        for user in users: db.add(HouseholdMember(household_id=home.id,user_id=user.id))
        db.commit()
        headers=[{'Authorization':'Bearer '+create_token(str(user.id))} for user in users]
    def database():
        with Session(engine) as db: yield db
    app.dependency_overrides[get_db]=database
    calls=[];responses={
        '/link/token/create':{'link_token':'link-synthetic','hosted_link_url':'https://secure.plaid.com/hl/synthetic'},
        '/link/token/get':{'link_sessions':[]},
        '/item/public_token/exchange':{'access_token':'access-synthetic','item_id':'item-synthetic'},
        '/transactions/sync':{'accounts':[{'account_id':'account-synthetic','name':'Sandbox checking','type':'depository','subtype':'checking','balances':{'current':123.45}}],
                              'added':[],'modified':[],'has_more':False,'next_cursor':'cursor-synthetic'}}
    def post(url, **kwargs):
        assert url.startswith('https://sandbox.plaid.com/')
        route=url[len('https://sandbox.plaid.com'):]
        assert kwargs['json']['client_id']==LOCAL['client_id']
        assert kwargs['json']['secret']==LOCAL['secret']
        calls.append((route,kwargs['json']))
        result=responses[route]
        if isinstance(result,Exception):raise result
        return httpx.Response(200,json=result,request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    with TestClient(app) as client:
        yield client,headers,engine,calls,responses
    app.dependency_overrides.pop(get_db,None)
    plaid_configuration.set_desktop_credentials(None)
    engine.dispose()


def start(context):
    client,headers,*_=context
    response=client.post(BASE+'/start',headers=headers[0])
    assert response.status_code==200,response.text
    return response.json()['session_id']


def reset_throttle(engine,session_id):
    with Session(engine) as db:
        row=db.get(PlaidLinkSession,UUID(session_id));state=decrypt_credentials(row.encrypted_state)
        state['last_check']=0;row.encrypted_state=encrypt_credentials(state);db.commit()


def test_success_is_owned_persistent_and_idempotent_with_encrypted_tokens(context):
    client,headers,engine,calls,responses=context
    session_id=start(context)
    assert calls[0][1]['hosted_link']=={'completion_redirect_uri':'pfos://plaid-complete','is_mobile_app':False,'url_lifetime_seconds':1800}
    assert client.post(BASE+'/start',headers=headers[0]).json()['session_id']==session_id
    assert len(calls)==1
    with Session(engine) as db:
        row=db.get(PlaidLinkSession,UUID(session_id))
        assert 'link-synthetic' not in row.encrypted_state
        assert 'synthetic-secret' not in row.encrypted_state
    assert client.get(BASE,headers=headers[1]).json()['status']=='idle'
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[1]).status_code==404
    assert client.post(BASE+f'/{session_id}/cancel',headers=headers[1]).status_code==404
    assert len(calls)==1
    # Reloading from a new request/DB session resumes the durable Link mapping.
    assert client.get(BASE,headers=headers[0]).json()['session_id']==session_id
    result={'public_token':'public-synthetic','institution':{'name':'Synthetic bank'}}
    responses['/link/token/get']={'link_sessions':[{'results':{'item_add_results':[result]},'on_success':{'public_token':'public-synthetic','metadata':result}}]}
    done=client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()
    assert done['status']=='complete'
    assert len(done['connections'])==1
    assert 'public-synthetic' not in str(done) and 'access-synthetic' not in str(done)
    for _ in range(3):assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()==done
    assert len([route for route,_ in calls if route.endswith('/exchange')])==1
    with Session(engine) as db:
        connection=db.scalar(select(DataConnection))
        assert 'access-synthetic' not in connection.encrypted_credentials
        assert decrypt_credentials(connection.encrypted_credentials)['plaid_identity']==plaid_configuration.identity(LOCAL)
        assert set(decrypt_credentials(db.get(PlaidLinkSession,UUID(session_id)).encrypted_state))=={'connections'}
    synced=client.post('/api/v1/connections/'+done['connections'][0]['id']+'/sync',headers=headers[0])
    assert synced.status_code==200,synced.text
    assert client.get('/api/v1/accounts',headers=headers[0]).json()[0]['name']=='Sandbox checking'


def test_oauth_handoff_is_pending_then_verified_not_trusted_from_callback(context):
    client,headers,engine,calls,responses=context
    session_id=start(context)
    responses['/link/token/get']={'link_sessions':[{'finished_at':'synthetic-time','events':[{'event_name':'OPEN_OAUTH'}],'results':None,'on_exit':None}]}
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='pending'
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='pending'
    assert len(calls)==2  # local poll throttle
    reset_throttle(engine,session_id)
    responses['/link/token/get']={'link_sessions':[{'on_success':{'public_token':'legacy-public','metadata':{'institution':{'name':'OAuth bank'}}}}]}
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='complete'


def test_cancel_ignores_late_success_and_allows_new_session(context):
    client,headers,engine,calls,responses=context
    session_id=start(context)
    assert client.post(BASE+f'/{session_id}/cancel',headers=headers[0]).json()['status']=='cancelled'
    responses['/link/token/get']={'link_sessions':[{'results':{'item_add_results':[{'public_token':'late-public'}]}}]}
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='cancelled'
    assert len(calls)==1
    assert start(context)!=session_id


def test_plaid_exit_and_expiration_end_pending_sessions(context):
    client,headers,engine,calls,responses=context
    session_id=start(context)
    responses['/link/token/get']={'link_sessions':[{'on_exit':{'error':None,'metadata':{'status':'requires_credentials'}}}]}
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='cancelled'
    session_id=start(context)
    with Session(engine) as db:
        db.get(PlaidLinkSession,UUID(session_id)).expires_at=datetime.utcnow()-timedelta(seconds=1);db.commit()
    count=len(calls)
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='expired'
    assert len(calls)==count


def test_secret_rotation_invalidates_without_using_previous_credentials(context):
    client,headers,engine,calls,responses=context
    session_id=start(context)
    plaid_configuration.set_desktop_credentials({**LOCAL,'secret':'replacement-secret'})
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='invalidated'
    assert len(calls)==1


def test_provider_failure_can_retry_without_echoing_tokens(context):
    client,headers,engine,calls,responses=context
    session_id=start(context)
    responses['/link/token/get']=httpx.ReadTimeout('synthetic-secret public-synthetic')
    response=client.post(BASE+f'/{session_id}/poll',headers=headers[0])
    assert response.status_code==502
    assert 'synthetic-secret' not in response.text and 'public-synthetic' not in response.text
    assert client.get(BASE,headers=headers[0]).json()['status']=='pending'
    reset_throttle(engine,session_id)
    responses['/link/token/get']={'link_sessions':[]}
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).status_code==200


def test_no_credentials_no_auth_or_bad_browser_url_fail_closed(context,monkeypatch):
    client,headers,engine,calls,responses=context
    assert client.post(BASE+'/start').status_code in (401,403)
    assert not calls
    plaid_configuration.set_desktop_credentials(None)
    assert client.post(BASE+'/start',headers=headers[0]).status_code==503
    assert not calls
    plaid_configuration.set_desktop_credentials(LOCAL)
    responses['/link/token/create']['hosted_link_url']='https://secure.plaid.com.evil.invalid/hl/stolen'
    assert client.post(BASE+'/start',headers=headers[0]).status_code==502
    with Session(engine) as db:assert db.scalar(select(PlaidLinkSession)) is None
    monkeypatch.delenv('PFOS_DESKTOP_RUNTIME')
    assert client.post(BASE+'/start',headers=headers[0]).status_code==404


def existing_bank(context, *, identity=None, status='reauthorization_required'):
    from app.models import Account, Transaction
    from datetime import date
    _,_,engine,_,_=context
    with Session(engine) as db:
        home=db.scalar(select(Household))
        connection=DataConnection(household_id=home.id,provider='plaid',name='Existing bank',status=status,cursor='keep-cursor',
            encrypted_credentials=encrypt_credentials({'access_token':'existing-access','item_id':'existing-item',
                'plaid_identity':identity if identity is not None else plaid_configuration.identity(LOCAL)}))
        db.add(connection);db.flush()
        account=Account(household_id=home.id,connection_id=connection.id,name='Keep checking',type='checking',balance=123.45)
        db.add(account);db.flush()
        transaction=Transaction(household_id=home.id,account_id=account.id,connection_id=connection.id,date=date(2026,1,1),description='Keep history',amount=42)
        db.add(transaction);db.commit()
        return str(connection.id),str(account.id),str(transaction.id),connection.encrypted_credentials


def test_update_mode_keeps_bank_token_accounts_history_and_cursor(context):
    client,headers,engine,calls,responses=context
    from app.models import Account, Transaction
    connection_id,account_id,transaction_id,original=existing_bank(context)
    response=client.post(BASE+'/start?connection_id='+connection_id,headers=headers[0])
    assert response.status_code==200,response.text
    session_id=response.json()['session_id']
    assert response.json()['mode']=='update'
    assert calls[-1][1]['access_token']=='existing-access' and 'products' not in calls[-1][1]
    assert 'existing-access' not in response.text
    responses['/link/token/get']={'link_sessions':[{'events':[{'event_name':'HANDOFF'}], 'results':None}]}
    responses['/item/get']={'item':{'item_id':'existing-item','error':None}}
    done=client.post(BASE+f'/{session_id}/poll',headers=headers[0])
    assert done.status_code==200,done.text
    assert done.json()['status']=='complete'
    assert done.json()['connections']==[{'id':connection_id,'name':'Existing bank'}]
    assert not any(route.endswith('/exchange') for route,_ in calls)
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()==done.json()
    with Session(engine) as db:
        bank=db.get(DataConnection,UUID(connection_id))
        assert bank.status=='active' and bank.cursor=='keep-cursor'
        assert bank.encrypted_credentials==original
        assert db.get(Account,UUID(account_id)).balance==123.45 or float(db.get(Account,UUID(account_id)).balance)==123.45
        assert db.get(Transaction,UUID(transaction_id)).description=='Keep history'
        assert len(db.scalars(select(DataConnection)).all())==1


def test_update_waits_for_verified_handoff_and_healthy_same_item(context):
    client,headers,engine,calls,responses=context
    connection_id,*_=existing_bank(context)
    session_id=client.post(BASE+'/start?connection_id='+connection_id,headers=headers[0]).json()['session_id']
    responses['/link/token/get']={'link_sessions':[{'events':[{'event_name':'OPEN_OAUTH'}],'finished_at':'not-proof'}]}
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='pending'
    assert not any(route=='/item/get' for route,_ in calls)
    responses['/link/token/get']={'link_sessions':[{'on_success':{'public_token':'must-not-exchange'}}]}
    responses['/item/get']={'item':{'item_id':'existing-item','error':{'error_code':'ITEM_LOGIN_REQUIRED','error_message':'secret-do-not-return'}}}
    reset_throttle(engine,session_id)
    response=client.post(BASE+f'/{session_id}/poll',headers=headers[0])
    assert response.status_code==422 and 'secret-do-not-return' not in response.text
    with Session(engine) as db:assert db.get(DataConnection,UUID(connection_id)).status=='reauthorization_required'
    responses['/item/get']={'item':{'item_id':'different-item','error':None}}
    reset_throttle(engine,session_id)
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).status_code==502
    assert not any(route.endswith('/exchange') for route,_ in calls)


def test_different_credentials_never_reuse_old_bank_token(context):
    client,headers,engine,calls,responses=context
    connection_id,*_=existing_bank(context,identity={'client_id':'another-client','environment':'sandbox'})
    row=client.get('/api/v1/connections',headers=headers[0]).json()[0]
    assert row['plaid_state']=='different_credentials' and row['can_sync'] is False and row['reconnect_mode']=='new'
    assert 'existing-access' not in str(row) and 'another-client' not in str(row)
    assert client.post(BASE+'/start?connection_id='+connection_id,headers=headers[0]).status_code==409
    assert client.post('/api/v1/connections/'+connection_id+'/sync',headers=headers[0]).status_code==422
    assert calls==[]


def test_removing_credentials_disables_banks_invalidates_sessions_and_preserves_history(context):
    client,headers,engine,calls,responses=context
    from app.plaid_hosted import replace_configuration
    from app.models import Account, Transaction
    connection_id,account_id,transaction_id,original=existing_bank(context,status='active')
    session_id=start(context)
    with Session(engine) as db:replace_configuration(None,db)
    row=client.get('/api/v1/connections',headers=headers[0]).json()[0]
    assert row['plaid_state']=='credentials_missing' and row['can_sync'] is False
    assert client.get(BASE,headers=headers[0]).json()['status']=='invalidated'
    with Session(engine) as db:
        assert db.get(DataConnection,UUID(connection_id)).encrypted_credentials==original
        assert db.get(Account,UUID(account_id)) and db.get(Transaction,UUID(transaction_id))
        replace_configuration(LOCAL,db)
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='invalidated'
    assert client.get('/api/v1/connections',headers=headers[0]).json()[0]['can_sync'] is True
    assert len(calls)==1


def test_secret_rotation_preserves_bank_identity_but_invalidates_pending_authorization(context):
    client,headers,engine,calls,responses=context
    from app.plaid_hosted import replace_configuration
    existing_bank(context,status='active');session_id=start(context)
    with Session(engine) as db:replace_configuration({**LOCAL,'secret':'rotated-secret'},db)
    row=client.get('/api/v1/connections',headers=headers[0]).json()[0]
    assert row['can_sync'] is True and row['reconnect_mode']=='update'
    assert client.post(BASE+f'/{session_id}/poll',headers=headers[0]).json()['status']=='invalidated'
    assert len(calls)==1


def test_sync_marks_bank_login_failure_without_exposing_provider_errors(context,monkeypatch):
    client,headers,engine,calls,responses=context
    connection_id,*_=existing_bank(context,status='active')
    monkeypatch.setattr(httpx,'post',lambda url,**kwargs:httpx.Response(400,json={'error_code':'ITEM_LOGIN_REQUIRED','error_message':'sensitive-provider-message'},request=httpx.Request('POST',url)))
    response=client.post('/api/v1/connections/'+connection_id+'/sync',headers=headers[0])
    assert response.status_code==422 and 'sensitive-provider-message' not in response.text
    row=client.get('/api/v1/connections',headers=headers[0]).json()[0]
    assert row['plaid_state']=='reauthorization_required' and row['reconnect_mode']=='update'
    monkeypatch.setattr(httpx,'post',lambda url,**kwargs:httpx.Response(400,json={'error_code':'INVALID_ACCESS_TOKEN'},request=httpx.Request('POST',url)))
    assert client.post('/api/v1/connections/'+connection_id+'/sync',headers=headers[0]).status_code==422
    assert client.get('/api/v1/connections',headers=headers[0]).json()[0]['reconnect_mode']=='new'

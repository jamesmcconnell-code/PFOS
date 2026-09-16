import pytest
from app import plaid_configuration as plaid
from app.config import settings
from app.connectors import PlaidConnector, ConnectorAuthenticationError


@pytest.fixture(autouse=True)
def local_configuration(monkeypatch):
    monkeypatch.setenv('PFOS_DESKTOP_RUNTIME','1')
    monkeypatch.setattr(settings,'plaid_client_id','server-owner-id')
    monkeypatch.setattr(settings,'plaid_secret','server-owner-secret')
    plaid.set_desktop_credentials(None)
    yield
    plaid.set_desktop_credentials(None)


def test_desktop_never_falls_back_to_server_settings():
    with pytest.raises(ValueError,match='Configure your own'):
        plaid.credentials()
    with pytest.raises(ConnectorAuthenticationError,match='Configure your own'):
        PlaidConnector().fetch({'access_token':'test-token'},None)


def test_sync_uses_local_identity_and_rejects_other_installation(monkeypatch):
    calls=[]
    class Response:
        def raise_for_status(self): return self
        def json(self): return {'accounts':[],'added':[],'modified':[],'next_cursor':'cursor','has_more':False}
    def post(url,**kwargs):
        calls.append((url,kwargs['json']))
        return Response()
    monkeypatch.setattr('app.connectors.httpx.post',post)
    first={'client_id':'first','secret':'first-secret','environment':'sandbox'}
    second={'client_id':'second','secret':'second-secret','environment':'production'}
    plaid.set_desktop_credentials(first)
    token={'access_token':'test-token','plaid_identity':plaid.identity(first)}
    PlaidConnector().fetch(token,None)
    assert calls[0][0]=='https://sandbox.plaid.com/transactions/sync'
    assert calls[0][1]['client_id']=='first' and calls[0][1]['secret']=='first-secret'
    plaid.set_desktop_credentials(second)
    with pytest.raises(ConnectorAuthenticationError,match='relinked'):
        PlaidConnector().fetch(token,None)
    assert len(calls)==1
    PlaidConnector().fetch({'access_token':'second-token','plaid_identity':plaid.identity(second)},None)
    assert calls[-1][0]=='https://production.plaid.com/transactions/sync'
    assert calls[-1][1]['secret']=='second-secret'


def test_invalid_configuration_is_rejected_without_changing_active_credentials():
    values={'client_id':'local','secret':'local-secret','environment':'sandbox'}
    plaid.set_desktop_credentials(values)
    with pytest.raises(ValueError): plaid.set_desktop_credentials({**values,'environment':'http://untrusted'})
    assert plaid.credentials()==values


def test_server_deployment_retains_its_explicit_server_configuration(monkeypatch):
    monkeypatch.delenv('PFOS_DESKTOP_RUNTIME')
    assert plaid.credentials()['client_id']=='server-owner-id'


def test_link_and_exchange_use_local_credentials(monkeypatch, tmp_path, migrated_template):
    import shutil
    from sqlalchemy.orm import Session
    from app.database import create_database_engine
    from app.main import plaid_link_token, plaid_exchange
    from app.models import User, Household, HouseholdMember
    from app.schemas import PlaidExchangeIn
    calls=[]
    class Response:
        def raise_for_status(self): return self
        def json(self): return {'link_token':'link-test','access_token':'access-test'}
    def post(url,**kwargs):
        calls.append((url,kwargs['json']))
        return Response()
    monkeypatch.setattr('httpx.post',post)
    database=tmp_path/'local.db';shutil.copyfile(migrated_template,database)
    engine=create_database_engine('sqlite:///'+str(database))
    with Session(engine) as db:
        user=User(email='local@example.com',display_name='Local',password_hash='unused')
        home=Household(name='Local');db.add_all([user,home]);db.flush()
        db.add(HouseholdMember(user_id=user.id,household_id=home.id));db.commit()
        config={'client_id':'local-client','secret':'local-secret','environment':'sandbox'}
        plaid.set_desktop_credentials(config)
        assert plaid_link_token(user,db)['link_token']=='link-test'
        plaid_exchange(PlaidExchangeIn(public_token='public-test',name='Test bank'),user,db)
        assert [url.rsplit('/',1)[-1] for url,_ in calls]==['create','exchange']
        assert all(body['client_id']=='local-client' and body['secret']=='local-secret' for _,body in calls)
    engine.dispose()


def test_removal_during_paginated_sync_prevents_another_request(monkeypatch):
    values={'client_id':'local','secret':'local-secret','environment':'sandbox'}
    plaid.set_desktop_credentials(values)
    calls=[]
    class Response:
        def raise_for_status(self): return self
        def json(self): return {'accounts':[],'added':[],'modified':[],'has_more':True,'next_cursor':'next'}
    def post(*args,**kwargs):
        calls.append(args)
        plaid.set_desktop_credentials(None)
        return Response()
    monkeypatch.setattr('app.connectors.httpx.post',post)
    with pytest.raises(ConnectorAuthenticationError,match='Configure your own'):
        PlaidConnector().fetch({'access_token':'test-token','plaid_identity':plaid.identity(values)},None)
    assert len(calls)==1

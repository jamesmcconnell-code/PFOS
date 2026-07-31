import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from app.connectors import CsvConnector, _coinbase_rest_jwt, decrypt_credentials, encrypt_credentials
from app.database import Base
from app.main import next_connection_name
from app.models import DataConnection, Household
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def test_credentials_are_encrypted_round_trip():
    secret=encrypt_credentials({'api_key':'visible-never','api_secret':'not-plaintext'})
    assert 'visible-never' not in secret
    assert decrypt_credentials(secret)['api_secret']=='not-plaintext'

def test_csv_normalizes_to_canonical_transaction():
    payload=CsvConnector().parse(b'date,description,amount\n2026-07-01,Coffee,-5.25\n', 'account-1')
    assert payload.transactions[0].account_external_id=='account-1'
    assert payload.transactions[0].description=='Coffee'
    assert str(payload.transactions[0].amount)=='-5.25'

def test_coinbase_rest_jwt_is_request_bound():
    key=ec.generate_private_key(ec.SECP256R1()); pem=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.TraditionalOpenSSL,serialization.NoEncryption()).decode()
    token=_coinbase_rest_jwt('organizations/org/apiKeys/key',pem,'GET','/api/v3/brokerage/accounts')
    claims=jwt.decode(token,key.public_key(),algorithms=['ES256'])
    assert claims['uri']=='GET api.coinbase.com/api/v3/brokerage/accounts'

def test_plaid_links_for_the_same_institution_get_distinct_source_names():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    household=Household(name='Test household');db.add(household);db.flush()
    db.add(DataConnection(household_id=household.id,provider='plaid',name='Capital One'));db.commit()
    assert next_connection_name(household.id,'plaid','Capital One',db)=='Capital One · 2'

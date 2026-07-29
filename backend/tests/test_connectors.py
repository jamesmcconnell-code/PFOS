from app.connectors import CsvConnector, decrypt_credentials, encrypt_credentials

def test_credentials_are_encrypted_round_trip():
    secret=encrypt_credentials({'api_key':'visible-never','api_secret':'not-plaintext'})
    assert 'visible-never' not in secret
    assert decrypt_credentials(secret)['api_secret']=='not-plaintext'

def test_csv_normalizes_to_canonical_transaction():
    payload=CsvConnector().parse(b'date,description,amount\n2026-07-01,Coffee,-5.25\n', 'account-1')
    assert payload.transactions[0].account_external_id=='account-1'
    assert payload.transactions[0].description=='Coffee'
    assert str(payload.transactions[0].amount)=='-5.25'

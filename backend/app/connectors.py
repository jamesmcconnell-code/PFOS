"""Provider adapters and the canonical PFOS normalization/persistence pipeline."""
import base64, binascii, csv, hashlib, hmac, io, json, secrets, time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
import httpx
import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .models import Account, Category, DataConnection, Transaction

@dataclass
class NormalizedAccount:
    external_id: str; name: str; type: str; balance: Decimal = Decimal('0')
@dataclass
class NormalizedTransaction:
    external_id: str | None; account_external_id: str; posted_on: date; description: str; amount: Decimal; notes: str | None = None; source_category: str | None = None; is_pending: bool = False
@dataclass
class SyncPayload:
    accounts: list[NormalizedAccount]; transactions: list[NormalizedTransaction]; cursor: str | None = None

def _fernet() -> Fernet:
    # A Fernet key is preferred; deriving one keeps local development usable while never returning secrets to clients.
    raw=(settings.credential_encryption_key or settings.jwt_secret).encode()
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw).digest()))
def encrypt_credentials(value: dict[str, Any]) -> str: return _fernet().encrypt(json.dumps(value).encode()).decode()
def decrypt_credentials(value: str | None) -> dict[str, Any]: return json.loads(_fernet().decrypt(value.encode()).decode()) if value else {}

class Connector(ABC):
    @abstractmethod
    def fetch(self, credentials: dict[str, Any], cursor: str | None) -> SyncPayload: ...
class ConnectorAuthenticationError(Exception): pass

class CsvConnector(Connector):
    """Accepts conventional date/description/amount rows; callers supply an account external id."""
    def parse(self, content: bytes, account_external_id: str) -> SyncPayload:
        rows=csv.DictReader(io.StringIO(content.decode('utf-8-sig'))); tx=[]
        for row in rows:
            raw_date=row.get('date') or row.get('Date') or row.get('posted_date')
            raw_amount=row.get('amount') or row.get('Amount') or row.get('transaction_amount')
            description=row.get('description') or row.get('Description') or row.get('name') or ''
            if not raw_date or raw_amount is None: raise ValueError('CSV requires date and amount columns')
            tx.append(NormalizedTransaction(row.get('id') or row.get('transaction_id'),account_external_id,date.fromisoformat(raw_date),description,Decimal(str(raw_amount)),row.get('notes')))
        return SyncPayload([],tx)
    def fetch(self, credentials: dict[str, Any], cursor: str | None) -> SyncPayload: raise ValueError('CSV connectors are uploaded, not synced remotely')

class PlaidConnector(Connector):
    def fetch(self, credentials: dict[str, Any], cursor: str | None) -> SyncPayload:
        if not settings.plaid_client_id or not settings.plaid_secret: raise ValueError('Plaid server credentials are not configured')
        host={'sandbox':'https://sandbox.plaid.com','development':'https://development.plaid.com','production':'https://production.plaid.com'}[settings.plaid_environment]
        page_cursor=cursor or ''; accounts={}; transactions=[]
        while True:
            data={'client_id':settings.plaid_client_id,'secret':settings.plaid_secret,'access_token':credentials['access_token'],'cursor':page_cursor,'count':500}
            body=httpx.post(f'{host}/transactions/sync',json=data,timeout=45).raise_for_status().json()
            for a in body.get('accounts',[]): accounts[a['account_id']]=NormalizedAccount(a['account_id'],a['name'],_plaid_type(a.get('subtype'),a.get('type')),Decimal(str(a['balances'].get('current') or 0)))
            transactions.extend(NormalizedTransaction(t['transaction_id'],t['account_id'],date.fromisoformat(t['date']),t['name'],Decimal(str(-t['amount'])),t.get('merchant_name'),(t.get('personal_finance_category') or {}).get('primary'),bool(t.get('pending'))) for t in body.get('added',[])+body.get('modified',[]))
            page_cursor=body.get('next_cursor')
            if not body.get('has_more'): break
        return SyncPayload(list(accounts.values()),transactions,page_cursor)
def _plaid_type(subtype: str | None, kind: str | None) -> str:
    if kind=='credit': return 'credit_card'
    if subtype in ('checking','savings'): return subtype
    return 'checking'

class CoinbaseConnector(Connector):
    def fetch(self, credentials: dict[str, Any], cursor: str | None) -> SyncPayload:
        path='/api/v3/brokerage/accounts'; token=_coinbase_rest_jwt(credentials['api_key'],credentials['api_secret'],'GET',path); accounts=[]; page_cursor=None
        try:
            while True:
                params={'limit':250};
                if page_cursor: params['cursor']=page_cursor
                body=httpx.get('https://api.coinbase.com'+path,params=params,headers={'Authorization':f'Bearer {token}'},timeout=30).raise_for_status().json()
                accounts.extend(NormalizedAccount(a['uuid'],a.get('name') or f"Coinbase {a['currency']}",'crypto',Decimal(str(a.get('available_balance',{}).get('value') or 0))) for a in body.get('accounts',[]) if a.get('active',True))
                page_cursor=body.get('cursor')
                if not body.get('has_next'): break
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401,403): raise ConnectorAuthenticationError('Coinbase rejected this connection. Use a CDP Advanced Trade API key with View permission and its private-key secret.') from exc
            raise
        return SyncPayload(accounts,[],cursor)

def _coinbase_rest_jwt(api_key: str, api_secret: str, method: str, path: str) -> str:
    """Build the request-bound JWT required by Coinbase Advanced Trade CDP keys."""
    secret=api_secret.replace('\\n','\n')
    if secret.lstrip().startswith('-----BEGIN'):
        try: private_key=serialization.load_pem_private_key(secret.encode(),password=None)
        except ValueError as exc: raise ConnectorAuthenticationError('Coinbase private key is not a valid PEM private key.') from exc
    else:
        try: raw=base64.b64decode(''.join(secret.split()),validate=True)
        except (ValueError,binascii.Error) as exc: raise ConnectorAuthenticationError('Coinbase private key is neither PEM nor valid base64.') from exc
        if len(raw) not in (32,64): raise ConnectorAuthenticationError('Coinbase private key must be a PEM key or a 32/64-byte base64 Ed25519 key.')
        private_key=ed25519.Ed25519PrivateKey.from_private_bytes(raw[:32])
    if isinstance(private_key,ed25519.Ed25519PrivateKey): algorithm='EdDSA'
    elif isinstance(private_key,ec.EllipticCurvePrivateKey): algorithm='ES256'
    else: raise ConnectorAuthenticationError('Coinbase key must use ECDSA P-256 or Ed25519.')
    now=int(time.time()); uri=f'{method.upper()} api.coinbase.com{path}'
    return jwt.encode({'sub':api_key,'iss':'cdp','nbf':now,'exp':now+120,'uri':uri},private_key,algorithm=algorithm,headers={'kid':api_key,'nonce':secrets.token_hex()})

class GeminiConnector(Connector):
    def fetch(self, credentials: dict[str, Any], cursor: str | None) -> SyncPayload:
        payload={'request':'/v1/balances','nonce':str(int(time.time()*1000))}; encoded=base64.b64encode(json.dumps(payload).encode()).decode(); signature=hmac.new(credentials['api_secret'].encode(),encoded.encode(),hashlib.sha384).hexdigest()
        body=httpx.post('https://api.gemini.com/v1/balances',headers={'X-GEMINI-APIKEY':credentials['api_key'],'X-GEMINI-PAYLOAD':encoded,'X-GEMINI-SIGNATURE':signature},timeout=30).raise_for_status().json()
        accounts=[NormalizedAccount(x['currency'],f"Gemini {x['currency']}",'crypto',Decimal(str(x.get('amount') or 0))) for x in body]
        return SyncPayload(accounts,[],cursor)

CONNECTORS={'plaid':PlaidConnector(),'coinbase':CoinbaseConnector(),'gemini':GeminiConnector()}

def persist_payload(db: Session, connection: DataConnection, payload: SyncPayload) -> tuple[int,int]:
    account_map={x.external_id:x for x in db.scalars(select(Account).where(Account.connection_id==connection.id)).all()}
    ignored=set(json.loads(connection.ignored_account_ids or '[]'))
    for source in payload.accounts:
        if source.external_id in ignored: continue
        target=account_map.get(source.external_id)
        if not target:
            target=Account(household_id=connection.household_id,connection_id=connection.id,external_id=source.external_id,name=source.name,type=source.type,balance=source.balance); db.add(target); db.flush(); account_map[source.external_id]=target
        else: target.name, target.type, target.balance=source.name,source.type,source.balance
    categories={c.name:c for c in db.scalars(select(Category).where(Category.household_id==connection.household_id)).all()}
    added=duplicates=0
    for source in payload.transactions:
        if source.account_external_id in ignored: continue
        account=account_map.get(source.account_external_id)
        if not account: continue
        fingerprint=hashlib.sha256(f'{account.id}|{source.posted_on}|{source.amount}|{source.description.lower()}'.encode()).hexdigest()
        existing=db.scalar(select(Transaction).where(Transaction.connection_id==connection.id,Transaction.external_id==source.external_id)) if source.external_id else None
        category=_category_for(db, categories, connection.household_id, source.source_category, source.amount)
        if existing:
            existing.account_id,existing.date,existing.description,existing.amount,existing.notes,existing.fingerprint,existing.category_id,existing.source_category,existing.is_pending,existing.is_essential=account.id,source.posted_on,source.description,source.amount,source.notes,fingerprint,category.id if category else None,source.source_category,source.is_pending,category.is_essential_default if category else False
            continue
        if db.scalar(select(Transaction.id).where(Transaction.fingerprint==fingerprint)): duplicates+=1; continue
        db.add(Transaction(household_id=connection.household_id,account_id=account.id,connection_id=connection.id,external_id=source.external_id,date=source.posted_on,description=source.description,amount=source.amount,notes=source.notes,fingerprint=fingerprint,category_id=category.id if category else None,source_category=source.source_category,is_pending=source.is_pending,is_essential=category.is_essential_default if category else False)); added+=1
    return added,duplicates

def _category_for(db: Session, cache: dict, household_id, source_category: str | None, amount: Decimal):
    if not source_category: return None
    names={'INCOME':'Income','TRANSFER_IN':'Transfers','TRANSFER_OUT':'Transfers','LOAN_PAYMENTS':'Debt payments','BANK_FEES':'Bank fees','FOOD_AND_DRINK':'Food & dining','GENERAL_MERCHANDISE':'Shopping','TRANSPORTATION':'Transportation','RENT_AND_UTILITIES':'Housing & utilities','MEDICAL':'Healthcare','PERSONAL_CARE':'Personal care','ENTERTAINMENT':'Entertainment','TRAVEL':'Travel','HOME_IMPROVEMENT':'Home improvement'}
    name=names.get(source_category,source_category.replace('_',' ').title()); category=cache.get(name)
    if category: return category
    essential=source_category in {'RENT_AND_UTILITIES','MEDICAL','LOAN_PAYMENTS','TRANSPORTATION'}
    category=Category(household_id=household_id,name=name,kind='income' if amount>0 and source_category=='INCOME' else 'expense',is_essential_default=essential);db.add(category);db.flush();cache[name]=category;return category

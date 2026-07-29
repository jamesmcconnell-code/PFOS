"""Provider adapters and the canonical PFOS normalization/persistence pipeline."""
import base64, csv, hashlib, hmac, io, json, time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .models import Account, DataConnection, Transaction

@dataclass
class NormalizedAccount:
    external_id: str; name: str; type: str; balance: Decimal = Decimal('0')
@dataclass
class NormalizedTransaction:
    external_id: str | None; account_external_id: str; posted_on: date; description: str; amount: Decimal; notes: str | None = None
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
            transactions.extend(NormalizedTransaction(t['transaction_id'],t['account_id'],date.fromisoformat(t['date']),t['name'],Decimal(str(-t['amount'])),t.get('merchant_name')) for t in body.get('added',[])+body.get('modified',[]))
            page_cursor=body.get('next_cursor')
            if not body.get('has_more'): break
        return SyncPayload(list(accounts.values()),transactions,page_cursor)
def _plaid_type(subtype: str | None, kind: str | None) -> str:
    if kind=='credit': return 'credit_card'
    if subtype in ('checking','savings'): return subtype
    return 'checking'

class CoinbaseConnector(Connector):
    def fetch(self, credentials: dict[str, Any], cursor: str | None) -> SyncPayload:
        # Coinbase Advanced Trade authentication signs METHOD + PATH + timestamp + body.
        ts=str(int(time.time())); path='/api/v3/brokerage/accounts'; secret=credentials['api_secret'].encode(); message=f'{ts}GET{path}'.encode()
        signature=hmac.new(secret,message,hashlib.sha256).hexdigest(); headers={'CB-ACCESS-KEY':credentials['api_key'],'CB-ACCESS-SIGN':signature,'CB-ACCESS-TIMESTAMP':ts}
        body=httpx.get('https://api.coinbase.com'+path,headers=headers,timeout=30).raise_for_status().json()
        accounts=[NormalizedAccount(a['uuid'],f"Coinbase {a['currency']}",'crypto',Decimal(str(a.get('available_balance',{}).get('value') or 0))) for a in body.get('accounts',[])]
        return SyncPayload(accounts,[],cursor)

class GeminiConnector(Connector):
    def fetch(self, credentials: dict[str, Any], cursor: str | None) -> SyncPayload:
        payload={'request':'/v1/balances','nonce':str(int(time.time()*1000))}; encoded=base64.b64encode(json.dumps(payload).encode()).decode(); signature=hmac.new(credentials['api_secret'].encode(),encoded.encode(),hashlib.sha384).hexdigest()
        body=httpx.post('https://api.gemini.com/v1/balances',headers={'X-GEMINI-APIKEY':credentials['api_key'],'X-GEMINI-PAYLOAD':encoded,'X-GEMINI-SIGNATURE':signature},timeout=30).raise_for_status().json()
        accounts=[NormalizedAccount(x['currency'],f"Gemini {x['currency']}",'crypto',Decimal(str(x.get('amount') or 0))) for x in body]
        return SyncPayload(accounts,[],cursor)

CONNECTORS={'plaid':PlaidConnector(),'coinbase':CoinbaseConnector(),'gemini':GeminiConnector()}

def persist_payload(db: Session, connection: DataConnection, payload: SyncPayload) -> tuple[int,int]:
    account_map={x.external_id:x for x in db.scalars(select(Account).where(Account.connection_id==connection.id)).all()}
    for source in payload.accounts:
        target=account_map.get(source.external_id)
        if not target:
            target=Account(household_id=connection.household_id,connection_id=connection.id,external_id=source.external_id,name=source.name,type=source.type,balance=source.balance); db.add(target); db.flush(); account_map[source.external_id]=target
        else: target.name, target.type, target.balance=source.name,source.type,source.balance
    added=duplicates=0
    for source in payload.transactions:
        account=account_map.get(source.account_external_id)
        if not account: continue
        fingerprint=hashlib.sha256(f'{account.id}|{source.posted_on}|{source.amount}|{source.description.lower()}'.encode()).hexdigest()
        existing=db.scalar(select(Transaction).where(Transaction.connection_id==connection.id,Transaction.external_id==source.external_id)) if source.external_id else None
        if existing:
            existing.account_id,existing.date,existing.description,existing.amount,existing.notes,existing.fingerprint=account.id,source.posted_on,source.description,source.amount,source.notes,fingerprint
            continue
        if db.scalar(select(Transaction.id).where(Transaction.fingerprint==fingerprint)): duplicates+=1; continue
        db.add(Transaction(household_id=connection.household_id,account_id=account.id,connection_id=connection.id,external_id=source.external_id,date=source.posted_on,description=source.description,amount=source.amount,notes=source.notes,fingerprint=fingerprint)); added+=1
    return added,duplicates

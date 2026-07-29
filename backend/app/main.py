import csv, hashlib, io, json
from datetime import date, datetime
from uuid import UUID
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session
from .database import get_db
from .models import *
from .schemas import *
from .security import hash_password, verify_password, create_token, decode_token
from .connectors import CONNECTORS, ConnectorAuthenticationError, CsvConnector, decrypt_credentials, encrypt_credentials, persist_payload
from .config import settings

app=FastAPI(title='PFOS API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.cors_origins.split(',') if origin.strip()], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
bearer=HTTPBearer()
def plaid_host() -> str:
    hosts={'sandbox':'https://sandbox.plaid.com','development':'https://development.plaid.com','production':'https://production.plaid.com'}
    try: return hosts[settings.plaid_environment]
    except KeyError: raise HTTPException(500,'Invalid PLAID_ENVIRONMENT configuration')
def current_user(c: HTTPAuthorizationCredentials=Depends(bearer), db: Session=Depends(get_db)):
    user=db.get(User, decode_token(c.credentials))
    if not user: raise HTTPException(401,'User not found')
    return user
def household(user: User, db: Session):
    member=db.scalar(select(HouseholdMember).where(HouseholdMember.user_id==user.id))
    if not member: raise HTTPException(400,'No household configured')
    return member.household_id
def serialize(o):
    return {c.name: (str(getattr(o,c.name)) if getattr(o,c.name) is not None else None) for c in o.__table__.columns}
def serialize_connection(connection: DataConnection):
    """Connection credentials are write-only: never return ciphertext to any client."""
    row=serialize(connection); row.pop('encrypted_credentials',None); row['credentials_configured']=bool(connection.encrypted_credentials); return row

@app.get('/health')
def health(): return {'status':'ok'}
@app.post('/api/v1/auth/register', response_model=Token)
def register(body:Register, db:Session=Depends(get_db)):
    if db.scalar(select(User).where(User.email==body.email)): raise HTTPException(409,'Email already registered')
    user=User(email=body.email,display_name=body.display_name,password_hash=hash_password(body.password)); db.add(user); db.flush()
    home=Household(name=f"{body.display_name}'s Household"); db.add(home); db.flush(); db.add(HouseholdMember(household_id=home.id,user_id=user.id,role='owner')); db.commit()
    return {'access_token':create_token(str(user.id))}
@app.post('/api/v1/auth/login', response_model=Token)
def login(body:Login, db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==body.email))
    if not user or not verify_password(body.password,user.password_hash): raise HTTPException(401,'Invalid email or password')
    return {'access_token':create_token(str(user.id))}
@app.get('/api/v1/auth/me')
def me(user=Depends(current_user)): return {'id':str(user.id),'email':user.email,'display_name':user.display_name}
@app.patch('/api/v1/auth/me')
def update_me(body:UserUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    other=db.scalar(select(User).where(User.email==body.email,User.id!=user.id))
    if other: raise HTTPException(409,'Email already in use')
    user.display_name,user.email=body.display_name,body.email
    if body.password: user.password_hash=hash_password(body.password)
    db.commit();return {'id':str(user.id),'email':user.email,'display_name':user.display_name}

@app.get('/api/v1/household')
def get_household(user=Depends(current_user),db:Session=Depends(get_db)):
    h=db.get(Household,household(user,db)); return serialize(h)
@app.get('/api/v1/household/members')
def household_members(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); members=db.scalars(select(HouseholdMember).where(HouseholdMember.household_id==h)).all(); return [{'id':str(m.user_id),'display_name':db.get(User,m.user_id).display_name,'email':db.get(User,m.user_id).email,'role':m.role} for m in members]
@app.get('/api/v1/accounts')
def accounts(view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); connections={x.id:x.name for x in db.scalars(select(DataConnection).where(DataConnection.household_id==h)).all()}; users={x.id:x.display_name for x in db.scalars(select(User).join(HouseholdMember,HouseholdMember.user_id==User.id).where(HouseholdMember.household_id==h)).all()}; result=[]
    q=select(Account).where(Account.household_id==h,Account.is_active==True)
    if view_user_id: q=q.where(or_(Account.ownership=='joint',Account.owner_id==view_user_id))
    for x in db.scalars(q).all():
        row=serialize(x);row.update(source_name=connections.get(x.connection_id,'Manual'),owner_name=users.get(x.owner_id,'Joint household'));result.append(row)
    return result
@app.post('/api/v1/accounts')
def add_account(body:AccountIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db)
    if body.account_type not in {'debt','brokerage','income','spending','crypto'}: raise HTTPException(400,'Invalid account type')
    if body.ownership=='individual' and (not body.owner_id or not db.scalar(select(HouseholdMember).where(HouseholdMember.household_id==h,HouseholdMember.user_id==body.owner_id))): raise HTTPException(400,'Select a household member for an individual account')
    a=Account(household_id=h,**body.model_dump()); db.add(a); db.commit(); return serialize(a)
@app.patch('/api/v1/accounts/{account_id}')
def update_account(account_id:UUID,body:AccountUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    a=db.get(Account,account_id)
    if not a or a.household_id!=household(user,db): raise HTTPException(404,'Account not found')
    if body.account_type not in {'debt','brokerage','income','spending','crypto'}: raise HTTPException(400,'Invalid account type')
    if body.ownership=='individual' and (not body.owner_id or not db.scalar(select(HouseholdMember).where(HouseholdMember.household_id==a.household_id,HouseholdMember.user_id==body.owner_id))): raise HTTPException(400,'Select a household member for an individual account')
    a.name,a.balance,a.account_type,a.ownership,a.owner_id=body.name,body.balance,body.account_type,body.ownership,body.owner_id if body.ownership=='individual' else None
    db.commit(); return serialize(a)
@app.delete('/api/v1/accounts/{account_id}',status_code=204)
def delete_account(account_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    a=db.get(Account,account_id)
    if not a or a.household_id!=household(user,db): raise HTTPException(404,'Account not found')
    # Linked accounts are excluded before deletion, preventing future provider syncs from recreating them.
    if a.connection_id and a.external_id:
        connection=db.get(DataConnection,a.connection_id)
        if connection:
            ignored=set(json.loads(connection.ignored_account_ids or '[]'));ignored.add(a.external_id);connection.ignored_account_ids=json.dumps(sorted(ignored))
    db.delete(a);db.commit()

@app.get('/api/v1/transactions')
def transactions(search:str|None=None,account_id:UUID|None=None,category_id:UUID|None=None,limit:int=100,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db)
    visible_accounts=select(Account.id).where(Account.household_id==h)
    if view_user_id: visible_accounts=visible_accounts.where(or_(Account.ownership=='joint',Account.owner_id==view_user_id))
    q=select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(visible_accounts)).order_by(Transaction.date.desc()).limit(min(limit,500))
    if search: q=q.where(Transaction.description.ilike(f'%{search}%'))
    if account_id: q=q.where(Transaction.account_id==account_id)
    if category_id: q=q.where(Transaction.category_id==category_id)
    accounts_by_id={x.id:x for x in db.scalars(select(Account).where(Account.household_id==h)).all()}; categories_by_id={x.id:x for x in db.scalars(select(Category).where(Category.household_id==h)).all()}; connections_by_id={x.id:x for x in db.scalars(select(DataConnection).where(DataConnection.household_id==h)).all()}; result=[]
    for x in db.scalars(q).all():
        row=serialize(x);account=accounts_by_id.get(x.account_id);row.update(account_name=account.name if account else 'Unknown account',account_type=account.account_type if account else None,category_name=categories_by_id.get(x.category_id).name if x.category_id in categories_by_id else None,source_name=connections_by_id.get(x.connection_id).name if x.connection_id in connections_by_id else 'Manual');result.append(row)
    return result
@app.post('/api/v1/transactions')
def add_transaction(body:TransactionIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); a=db.get(Account,body.account_id)
    if not a or a.household_id!=h: raise HTTPException(400,'Invalid account')
    data=body.model_dump(); data['fingerprint']=hashlib.sha256(f'{body.account_id}|{body.date}|{body.amount}|{body.description.lower()}'.encode()).hexdigest()
    t=Transaction(household_id=h,**data); db.add(t); a.balance=float(a.balance)+body.amount; db.commit(); return serialize(t)
@app.patch('/api/v1/transactions/{transaction_id}')
def update_transaction(transaction_id:UUID,body:TransactionIn,user=Depends(current_user),db:Session=Depends(get_db)):
    t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=household(user,db): raise HTTPException(404,'Transaction not found')
    for k,v in body.model_dump().items(): setattr(t,k,v)
    db.commit(); return serialize(t)

@app.get('/api/v1/categories')
def categories(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(Category).where(Category.household_id==household(user,db))).all()]
@app.post('/api/v1/categories')
def add_category(name:str,kind:str='expense',essential:bool=False,user=Depends(current_user),db:Session=Depends(get_db)):
    c=Category(household_id=household(user,db),name=name,kind=kind,is_essential_default=essential);db.add(c);db.commit();return serialize(c)
@app.get('/api/v1/tags')
def tags(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(Tag).where(Tag.household_id==household(user,db))).all()]
@app.post('/api/v1/tags')
def add_tag(name:str,user=Depends(current_user),db:Session=Depends(get_db)):
    x=Tag(household_id=household(user,db),name=name);db.add(x);db.commit();return serialize(x)
@app.get('/api/v1/income-sources')
def income_sources(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(IncomeSource).where(IncomeSource.household_id==household(user,db))).all()]
@app.post('/api/v1/income-sources')
def add_income(body:IncomeIn,user=Depends(current_user),db:Session=Depends(get_db)):
    x=IncomeSource(household_id=household(user,db),**body.model_dump());db.add(x);db.commit();return serialize(x)
@app.get('/api/v1/debts')
def debts(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(Debt).where(Debt.household_id==household(user,db))).all()]
@app.get('/api/v1/forecasting-profiles')
def profiles(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(ForecastingProfile).where(ForecastingProfile.household_id==household(user,db))).all()]

@app.get('/api/v1/goals')
def goals(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); result=[]
    for g in db.scalars(select(Goal).where(Goal.household_id==h)).all():
        saved=float(db.scalar(select(func.coalesce(func.sum(GoalContribution.amount),0)).where(GoalContribution.goal_id==g.id)) or 0); row=serialize(g); row.update(saved_amount=saved,progress=round(saved/float(g.target_amount)*100,1) if g.target_amount else 0); result.append(row)
    return result
@app.post('/api/v1/goals')
def add_goal(body:GoalIn,user=Depends(current_user),db:Session=Depends(get_db)):
    g=Goal(household_id=household(user,db),**body.model_dump());db.add(g);db.commit();return serialize(g)
@app.patch('/api/v1/goals/{goal_id}')
def update_goal(goal_id:UUID,body:GoalUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    g=db.get(Goal,goal_id)
    if not g or g.household_id!=household(user,db): raise HTTPException(404,'Goal not found')
    g.name=body.name;g.target_amount=body.target_amount
    db.commit();return serialize(g)
@app.delete('/api/v1/goals/{goal_id}',status_code=204)
def delete_goal(goal_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    g=db.get(Goal,goal_id)
    if not g or g.household_id!=household(user,db): raise HTTPException(404,'Goal not found')
    db.delete(g);db.commit()
@app.post('/api/v1/goals/{goal_id}/contributions')
def contribute(goal_id:UUID,amount:float,user=Depends(current_user),db:Session=Depends(get_db)):
    g=db.get(Goal,goal_id)
    if not g or g.household_id!=household(user,db): raise HTTPException(404,'Goal not found')
    x=GoalContribution(goal_id=goal_id,amount=amount);db.add(x);db.commit();return serialize(x)

@app.post('/api/v1/imports/preview')
async def preview_import(account_id:UUID, file:UploadFile=File(...),user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); account=db.get(Account,account_id)
    if not account or account.household_id!=h: raise HTTPException(400,'Invalid account')
    rows=list(csv.DictReader(io.StringIO((await file.read()).decode('utf-8-sig')))); preview=[]; duplicates=0
    for r in rows[:100]:
        amount=float(r.get('amount') or r.get('Amount') or 0); d=r.get('date') or r.get('Date'); desc=r.get('description') or r.get('Description') or ''
        fp=hashlib.sha256(f'{account_id}|{d}|{amount}|{desc.lower()}'.encode()).hexdigest(); dup=db.scalar(select(Transaction.id).where(Transaction.fingerprint==fp)) is not None; duplicates+=dup; preview.append({'date':d,'description':desc,'amount':amount,'duplicate':dup})
    return {'rows':preview,'total_rows':len(rows),'duplicates':duplicates}
@app.post('/api/v1/imports/commit')
async def commit_import(account_id:UUID,file:UploadFile=File(...),user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); rows=list(csv.DictReader(io.StringIO((await file.read()).decode('utf-8-sig')))); added=dupes=0
    batch=ImportBatch(household_id=h,account_id=account_id,filename=file.filename);db.add(batch)
    for r in rows:
        amount=float(r.get('amount') or r.get('Amount') or 0); d=date.fromisoformat(r.get('date') or r.get('Date')); desc=r.get('description') or r.get('Description') or ''; fp=hashlib.sha256(f'{account_id}|{d}|{amount}|{desc.lower()}'.encode()).hexdigest()
        if db.scalar(select(Transaction.id).where(Transaction.fingerprint==fp)): dupes+=1;continue
        db.add(Transaction(household_id=h,account_id=account_id,date=d,description=desc,amount=amount,fingerprint=fp));added+=1
    batch.imported_count=added;batch.duplicate_count=dupes;db.commit();return {'imported':added,'duplicates':dupes}
@app.get('/api/v1/imports')
def imports(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(ImportBatch).where(ImportBatch.household_id==household(user,db)).order_by(ImportBatch.created_at.desc())).all()]

@app.get('/api/v1/connections')
def connections(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); rows=[]
    for x in db.scalars(select(DataConnection).where(DataConnection.household_id==h).order_by(DataConnection.created_at.desc())).all():
        rows.append(serialize_connection(x))
    return rows
@app.delete('/api/v1/connections/{connection_id}',status_code=204)
def unlink_connection(connection_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(DataConnection,connection_id)
    if not x or x.household_id!=household(user,db): raise HTTPException(404,'Connection not found')
    # An unlink removes source-owned data; manually created accounts are never affected.
    for account in db.scalars(select(Account).where(Account.connection_id==x.id)).all(): db.delete(account)
    db.delete(x);db.commit()
@app.post('/api/v1/connections')
def create_connection(body:ConnectionIn,user=Depends(current_user),db:Session=Depends(get_db)):
    if body.provider not in CONNECTORS: raise HTTPException(400,'Provider must be plaid, coinbase, or gemini')
    required={'coinbase':{'api_key','api_secret'},'gemini':{'api_key','api_secret'},'plaid':{'access_token'}}[body.provider]
    if not required.issubset(body.credentials): raise HTTPException(400,f'Missing credentials: {", ".join(sorted(required-set(body.credentials)))}')
    h=household(user,db); x=db.scalar(select(DataConnection).where(DataConnection.household_id==h,DataConnection.provider==body.provider,DataConnection.name==body.name))
    if x:
        x.encrypted_credentials=encrypt_credentials(body.credentials);x.cursor=None;x.status='active'
    else: x=DataConnection(household_id=h,provider=body.provider,name=body.name,encrypted_credentials=encrypt_credentials(body.credentials));db.add(x)
    db.commit();return serialize_connection(x)
@app.post('/api/v1/connections/plaid/link-token')
def plaid_link_token(user=Depends(current_user),db:Session=Depends(get_db)):
    if not settings.plaid_client_id or not settings.plaid_secret: raise HTTPException(503,'Plaid is not configured on the server')
    import httpx
    try: response=httpx.post(f'{plaid_host()}/link/token/create',json={'client_id':settings.plaid_client_id,'secret':settings.plaid_secret,'client_name':'PFOS','language':'en','country_codes':['US'],'products':['transactions'],'user':{'client_user_id':str(user.id)}},timeout=30).raise_for_status().json()
    except httpx.HTTPError as exc: raise HTTPException(502,'Plaid Link could not be initialized; verify your Plaid production configuration') from exc
    return {'link_token':response['link_token']}
@app.post('/api/v1/connections/plaid/exchange')
def plaid_exchange(body:PlaidExchangeIn,user=Depends(current_user),db:Session=Depends(get_db)):
    if not settings.plaid_client_id or not settings.plaid_secret: raise HTTPException(503,'Plaid is not configured on the server')
    import httpx
    try: raw=httpx.post(f'{plaid_host()}/item/public_token/exchange',json={'client_id':settings.plaid_client_id,'secret':settings.plaid_secret,'public_token':body.public_token},timeout=30).raise_for_status().json()
    except httpx.HTTPError as exc: raise HTTPException(502,'Plaid account authorization could not be saved') from exc
    x=DataConnection(household_id=household(user,db),provider='plaid',name=body.name,encrypted_credentials=encrypt_credentials({'access_token':raw['access_token']}));db.add(x);db.commit();return serialize_connection(x)
@app.post('/api/v1/connections/{connection_id}/sync')
def sync_connection(connection_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(DataConnection,connection_id)
    if not x or x.household_id!=household(user,db): raise HTTPException(404,'Connection not found')
    run=ConnectionSync(connection_id=x.id,status='running');db.add(run);db.flush()
    try:
        payload=CONNECTORS[x.provider].fetch(decrypt_credentials(x.encrypted_credentials),x.cursor); added,dupes=persist_payload(db,x,payload);x.cursor=payload.cursor;x.last_synced_at=datetime.utcnow();run.status='complete';run.imported_count=added;run.duplicate_count=dupes;db.commit();return {'imported':added,'duplicates':dupes,'connection':serialize_connection(x)}
    except ConnectorAuthenticationError as exc:
        db.rollback();run=ConnectionSync(connection_id=x.id,status='failed',error_message=str(exc));db.add(run);db.commit();raise HTTPException(422,str(exc))
    except Exception as exc:
        db.rollback();run=ConnectionSync(connection_id=x.id,status='failed',error_message=str(exc)[:500]);db.add(run);db.commit();raise HTTPException(502,'Sync failed; review the connection credentials and provider status')
@app.post('/api/v1/connections/csv/{account_id}')
async def import_csv_normalized(account_id:UUID,file:UploadFile=File(...),user=Depends(current_user),db:Session=Depends(get_db)):
    account=db.get(Account,account_id)
    if not account or account.household_id!=household(user,db): raise HTTPException(404,'Account not found')
    # CSV is normalized through the same pipeline; a temporary in-database connection preserves provenance.
    connection=db.scalar(select(DataConnection).where(DataConnection.household_id==account.household_id,DataConnection.provider=='csv',DataConnection.name==f'CSV: {account.name}'))
    if not connection: connection=DataConnection(household_id=account.household_id,provider='csv',name=f'CSV: {account.name}');db.add(connection);db.flush()
    account.connection_id=connection.id; account.external_id=str(account.id)
    try: payload=CsvConnector().parse(await file.read(),str(account.id)); added,dupes=persist_payload(db,connection,payload);db.commit();return {'imported':added,'duplicates':dupes}
    except ValueError as exc: raise HTTPException(400,str(exc))
@app.get('/api/v1/connections/{connection_id}/syncs')
def connection_syncs(connection_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(DataConnection,connection_id)
    if not x or x.household_id!=household(user,db): raise HTTPException(404,'Connection not found')
    return [serialize(run) for run in db.scalars(select(ConnectionSync).where(ConnectionSync.connection_id==x.id).order_by(ConnectionSync.created_at.desc())).all()]

def metrics(h,db,view_user_id=None):
    q=select(Account).where(Account.household_id==h,Account.is_active==True)
    if view_user_id: q=q.where(or_(Account.ownership=='joint',Account.owner_id==view_user_id))
    accounts=db.scalars(q).all(); account_ids=[x.id for x in accounts]; accounts_by_id={x.id:x for x in accounts}; debt_accounts=sum(abs(float(x.balance)) for x in accounts if x.account_type=='debt'); assets=sum(float(x.balance) for x in accounts if x.account_type!='debt'); legacy_debt=float(db.scalar(select(func.coalesce(func.sum(Debt.balance),0)).where(Debt.household_id==h)) or 0); debt=debt_accounts+legacy_debt
    income_q=select(func.coalesce(func.sum(IncomeSource.monthly_amount),0)).where(IncomeSource.household_id==h,IncomeSource.is_active==True)
    if view_user_id: income_q=income_q.where(or_(IncomeSource.owner_id==None,IncomeSource.owner_id==view_user_id))
    manual_income=float(db.scalar(income_q) or 0)
    tx=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.date>=date.today().replace(day=1))).all() if account_ids else []
    payroll=sum(float(x.amount) for x in tx if float(x.amount)>0 and accounts_by_id.get(x.account_id) and accounts_by_id[x.account_id].account_type=='spending'); income=manual_income+payroll; expenses=-sum(float(x.amount) for x in tx if float(x.amount)<0); savings=income-expenses
    essential=-sum(float(x.amount) for x in tx if float(x.amount)<0 and x.is_essential); return {'net_worth':assets-debt,'cash_available':sum(float(x.balance) for x in accounts if x.account_type in ('spending','income')),'debt_total':debt,'monthly_income':income,'monthly_expenses':expenses,'monthly_savings':savings,'savings_rate':round(savings/income*100,1) if income else 0,'essential_monthly':essential}
@app.get('/api/v1/dashboard')
def dashboard(view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); m=metrics(h,db,view_user_id); q=select(Account).where(Account.household_id==h,Account.account_type=='crypto',Account.is_active==True)
    if view_user_id: q=q.where(or_(Account.ownership=='joint',Account.owner_id==view_user_id))
    crypto={}
    for a in db.scalars(q).all():
        if float(a.balance): crypto[a.asset_symbol or a.name]=crypto.get(a.asset_symbol or a.name,0)+float(a.balance)
    m.update(goals=goals(user,db),crypto_assets=[{'symbol':k,'amount':v} for k,v in sorted(crypto.items())],alerts=['Emergency fund is below six months of essential spending'] if m['cash_available']<m['essential_monthly']*6 else []);return m
@app.get('/api/v1/forecast')
def forecast(monthly_savings:float|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); m=metrics(h,db,view_user_id); savings=monthly_savings if monthly_savings is not None else m['monthly_savings']; output=[]
    for g in goals(user,db):
        remaining=max(0,float(g['target_amount'])-g['saved_amount']); months=remaining/savings if savings>0 else None; output.append({'goal':g['name'],'monthly_savings':savings,'months_to_complete':round(months,1) if months is not None else None,'projected_completion':str(date.today().replace(year=date.today().year+int(months//12))) if months is not None else None})
    return {'projected_savings_12_months':savings*12,'goals':output}
@app.get('/api/v1/analysis/live-on-one-income')
def one_income(view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db);m=metrics(h,db,view_user_id); income_q=select(IncomeSource).where(IncomeSource.household_id==h,IncomeSource.is_active==True)
    if view_user_id: income_q=income_q.where(or_(IncomeSource.owner_id==None,IncomeSource.owner_id==view_user_id))
    incomes=db.scalars(income_q).all(); return {'monthly_expenses':m['monthly_expenses'],'scenarios':[{'name':x.name,'income':float(x.monthly_amount),'surplus':float(x.monthly_amount)-m['monthly_expenses'],'sustainable':float(x.monthly_amount)>=m['monthly_expenses']} for x in incomes]+[{'name':'Combined income','income':m['monthly_income'],'surplus':m['monthly_savings'],'sustainable':m['monthly_savings']>=0}]}

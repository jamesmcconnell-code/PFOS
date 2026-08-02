import calendar, csv, hashlib, io, json
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, func, or_, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import *
from .schemas import *
from .security import hash_password, verify_password, create_token, decode_token
from .connectors import CONNECTORS, ConnectorAuthenticationError, CsvConnector, decrypt_credentials, encrypt_credentials, persist_payload
from .crypto_prices import refresh_usd_values
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
def require_admin(user: User=Depends(current_user)):
    if user.role!='ADMIN': raise HTTPException(403,'Administrator access required')
    return user
def validate_password(password: str):
    if len(password)<10 or not any(character.isalpha() for character in password) or not any(character.isdigit() for character in password):
        raise HTTPException(400,'Password must be at least 10 characters and include a letter and a number')
def household(user: User, db: Session):
    member=db.scalar(select(HouseholdMember).where(HouseholdMember.user_id==user.id))
    if not member: raise HTTPException(400,'No household configured')
    return member.household_id
def validate_view_member(household_id, view_user_id: UUID|None, db: Session):
    if view_user_id and not db.scalar(select(HouseholdMember).where(HouseholdMember.household_id==household_id,HouseholdMember.user_id==view_user_id)):
        raise HTTPException(400,'Selected user is not part of this household')
def ensure_groceries_category(household_id, db: Session):
    category=db.scalar(select(Category).where(Category.household_id==household_id,func.lower(Category.name)=='groceries'))
    if not category:
        try:
            category=Category(household_id=household_id,name='Groceries',kind='expense')
            db.add(category); db.commit(); db.refresh(category)
        except IntegrityError:
            db.rollback()
            category=db.scalar(select(Category).where(Category.household_id==household_id,func.lower(Category.name)=='groceries'))
    return category
def serialize(o):
    def value(raw):
        return str(raw) if isinstance(raw,(UUID,date,datetime,Decimal)) else raw
    return {c.name:value(getattr(o,c.name)) if getattr(o,c.name) is not None else None for c in o.__table__.columns}
def serialize_connection(connection: DataConnection):
    """Connection credentials are write-only: never return ciphertext to any client."""
    row=serialize(connection); row.pop('encrypted_credentials',None); row['credentials_configured']=bool(connection.encrypted_credentials); return row
def record_balance_snapshots(db: Session, accounts: list[Account], snapshot_date: date|None=None, source: str='calculated'):
    """Upsert one point-in-time balance per account/day without changing balances."""
    captured_on=snapshot_date or date.today()
    for account in accounts:
        snapshot=db.scalar(select(AccountBalanceSnapshot).where(AccountBalanceSnapshot.account_id==account.id,AccountBalanceSnapshot.snapshot_date==captured_on))
        usd_value=float(account.crypto_usd_value) if account.account_type=='crypto' and account.crypto_usd_value is not None else None
        if snapshot:
            snapshot.balance=account.balance; snapshot.usd_value=usd_value; snapshot.source=source
        else:
            db.add(AccountBalanceSnapshot(household_id=account.household_id,account_id=account.id,snapshot_date=captured_on,balance=account.balance,usd_value=usd_value,source=source))
def next_connection_name(household_id, provider: str, requested_name: str, db: Session):
    """Give separately authorized items a stable, readable source name."""
    base=requested_name.strip()[:120] or provider.title()
    existing=set(db.scalars(select(DataConnection.name).where(DataConnection.household_id==household_id,DataConnection.provider==provider)).all())
    if base not in existing: return base
    index=2
    while True:
        suffix=f' · {index}'
        candidate=f'{base[:120-len(suffix)]}{suffix}'
        if candidate not in existing: return candidate
        index+=1

@app.get('/health')
def health(): return {'status':'ok'}
@app.post('/api/v1/auth/register', response_model=Token)
def register(body:Register, db:Session=Depends(get_db)):
    if db.scalar(select(User).where(User.email==body.email)): raise HTTPException(409,'Email already registered')
    validate_password(body.password); user=User(email=body.email,display_name=body.display_name,password_hash=hash_password(body.password),role='ADMIN' if not db.scalar(select(func.count()).select_from(User)) else 'USER'); db.add(user); db.flush()
    home=Household(name=f"{body.display_name}'s Household"); db.add(home); db.flush(); db.add(HouseholdMember(household_id=home.id,user_id=user.id,role='owner')); db.commit()
    return {'access_token':create_token(str(user.id))}
@app.post('/api/v1/auth/login', response_model=Token)
def login(body:Login, db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==body.email))
    if not user or not verify_password(body.password,user.password_hash): raise HTTPException(401,'Invalid email or password')
    return {'access_token':create_token(str(user.id))}
@app.get('/api/v1/auth/me')
def me(user=Depends(current_user)): return {'id':str(user.id),'email':user.email,'display_name':user.display_name,'role':user.role,'theme_preference':user.theme_preference,'simple_mode_enabled':user.simple_mode_enabled}
@app.patch('/api/v1/auth/me')
def update_me(body:UserUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    other=db.scalar(select(User).where(User.email==body.email,User.id!=user.id))
    if other: raise HTTPException(409,'Email already in use')
    user.display_name,user.email=body.display_name,body.email
    db.commit();return {'id':str(user.id),'email':user.email,'display_name':user.display_name}
@app.patch('/api/v1/users/me/password')
def update_own_password(body:PasswordUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    if not verify_password(body.current_password,user.password_hash): raise HTTPException(400,'Current password is incorrect')
    validate_password(body.new_password); user.password_hash=hash_password(body.new_password); db.commit(); return {'status':'updated'}
@app.patch('/api/v1/users/me/theme')
def update_theme(body:ThemeUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    if body.theme_preference not in {'system','emerald','midnight'}: raise HTTPException(400,'Invalid theme preference')
    user.theme_preference=body.theme_preference; db.commit(); return {'theme_preference':user.theme_preference}
@app.patch('/api/v1/users/me/simple-mode')
def update_simple_mode(body:SimpleModeUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    user.simple_mode_enabled=body.simple_mode_enabled; db.commit(); return {'simple_mode_enabled':user.simple_mode_enabled}
@app.get('/api/v1/admin/users')
def admin_users(user=Depends(require_admin),db:Session=Depends(get_db)):
    return [{'id':str(item.id),'display_name':item.display_name,'email':item.email,'role':item.role,'theme_preference':item.theme_preference,'simple_mode_enabled':item.simple_mode_enabled,'is_active':item.is_active,'created_at':item.created_at.isoformat()} for item in db.scalars(select(User).order_by(User.created_at)).all()]
@app.patch('/api/v1/admin/users/{user_id}/password')
def admin_update_password(user_id:UUID,body:AdminPasswordUpdate,user=Depends(require_admin),db:Session=Depends(get_db)):
    target=db.get(User,user_id)
    if not target: raise HTTPException(404,'User not found')
    validate_password(body.new_password); target.password_hash=hash_password(body.new_password); db.commit(); return {'status':'updated','user_id':str(target.id)}

@app.get('/api/v1/household')
def get_household(user=Depends(current_user),db:Session=Depends(get_db)):
    h=db.get(Household,household(user,db)); return serialize(h)
@app.get('/api/v1/household/financial-settings')
def get_financial_settings(user=Depends(current_user),db:Session=Depends(get_db)):
    h=db.get(Household,household(user,db));return {'checking_account_ceiling':float(h.checking_account_ceiling)}
@app.patch('/api/v1/household/financial-settings')
def update_financial_settings(body:FinancialSettingsUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    h=db.get(Household,household(user,db));h.checking_account_ceiling=body.checking_account_ceiling;db.commit();return {'checking_account_ceiling':float(h.checking_account_ceiling)}
@app.get('/api/v1/household/members')
def household_members(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); members=db.scalars(select(HouseholdMember).where(HouseholdMember.household_id==h)).all(); return [{'id':str(m.user_id),'display_name':db.get(User,m.user_id).display_name,'email':db.get(User,m.user_id).email,'role':m.role} for m in members]
@app.post('/api/v1/household/members')
def add_household_member(body:HouseholdUserIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db)
    if user.role!='ADMIN': raise HTTPException(403,'Only an administrator can add members')
    if db.scalar(select(User).where(User.email==body.email)): raise HTTPException(409,'Email already registered')
    validate_password(body.password); member_user=User(email=body.email,display_name=body.display_name,password_hash=hash_password(body.password),role='USER');db.add(member_user);db.flush();db.add(HouseholdMember(household_id=h,user_id=member_user.id,role='member'));db.commit()
    return {'id':str(member_user.id),'display_name':member_user.display_name,'email':member_user.email,'role':'member'}
@app.get('/api/v1/accounts')
def accounts(view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); connections={x.id:x.name for x in db.scalars(select(DataConnection).where(DataConnection.household_id==h)).all()}; users={x.id:x.display_name for x in db.scalars(select(User).join(HouseholdMember,HouseholdMember.user_id==User.id).where(HouseholdMember.household_id==h)).all()}; result=[]
    q=select(Account).where(Account.household_id==h,Account.is_active==True)
    validate_view_member(h,view_user_id,db)
    if view_user_id: q=q.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    for x in db.scalars(q).all():
        row=serialize(x);row.update(source_name=connections.get(x.connection_id,'Manual'),owner_name=users.get(x.owner_id,'Joint household'));result.append(row)
    return result
@app.post('/api/v1/accounts')
def add_account(body:AccountIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db)
    if body.account_type not in {'debt','brokerage','income','spending','crypto'}: raise HTTPException(400,'Invalid account type')
    if body.ownership=='individual' and (not body.owner_id or not db.scalar(select(HouseholdMember).where(HouseholdMember.household_id==h,HouseholdMember.user_id==body.owner_id))): raise HTTPException(400,'Select a household member for an individual account')
    a=Account(household_id=h,**body.model_dump()); db.add(a); db.flush(); record_balance_snapshots(db,[a],source='manual'); db.commit(); return serialize(a)
@app.patch('/api/v1/accounts/{account_id}')
def update_account(account_id:UUID,body:AccountUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    a=db.get(Account,account_id)
    if not a or a.household_id!=household(user,db): raise HTTPException(404,'Account not found')
    if body.account_type not in {'debt','brokerage','income','spending','crypto'}: raise HTTPException(400,'Invalid account type')
    if body.ownership=='individual' and (not body.owner_id or not db.scalar(select(HouseholdMember).where(HouseholdMember.household_id==a.household_id,HouseholdMember.user_id==body.owner_id))): raise HTTPException(400,'Select a household member for an individual account')
    a.name,a.balance,a.account_type,a.ownership,a.owner_id,a.is_savings_direct_deposit=body.name,body.balance,body.account_type,body.ownership,body.owner_id if body.ownership=='individual' else None,body.is_savings_direct_deposit
    record_balance_snapshots(db,[a],source='manual')
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
def transactions(search:str|None=None,account_id:UUID|None=None,category_id:UUID|None=None,category_ids:list[UUID]=Query(default=[]),financial_roles:list[str]=Query(default=[]),connection_ids:list[UUID]=Query(default=[]),transaction_type:str|None=None,start_date:date|None=None,end_date:date|None=None,sort:str='date_desc',page:int=1,page_size:int=25,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db)
    ensure_groceries_category(h,db)
    visible_accounts=select(Account.id).where(Account.household_id==h)
    validate_view_member(h,view_user_id,db)
    if view_user_id: visible_accounts=visible_accounts.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    if page<1: raise HTTPException(400,'Page must be at least 1')
    if page_size<1 or page_size>100: raise HTTPException(400,'Page size must be between 1 and 100')
    valid_roles={'spending','income','debt','brokerage','crypto'}
    if not set(financial_roles).issubset(valid_roles): raise HTTPException(400,'Invalid financial role filter')
    if transaction_type not in {None,'credit','debit'}: raise HTTPException(400,'Transaction type must be credit or debit')
    if start_date and end_date and start_date>end_date: raise HTTPException(400,'Start date must be on or before end date')
    filters=[Transaction.household_id==h,Transaction.account_id.in_(visible_accounts)]
    if search: filters.append(Transaction.description.ilike(f'%{search.strip()}%'))
    if account_id: filters.append(Transaction.account_id==account_id)
    selected_categories=category_ids+([category_id] if category_id else [])
    if selected_categories: filters.append(Transaction.category_id.in_(selected_categories))
    if financial_roles: filters.append(Transaction.account_id.in_(select(Account.id).where(Account.household_id==h,Account.account_type.in_(financial_roles))))
    if connection_ids: filters.append(Transaction.connection_id.in_(connection_ids))
    if transaction_type=='credit': filters.append(Transaction.amount>0)
    if transaction_type=='debit': filters.append(Transaction.amount<0)
    if start_date: filters.append(Transaction.date>=start_date)
    if end_date: filters.append(Transaction.date<=end_date)
    orders={'date_desc':Transaction.date.desc(),'date_asc':Transaction.date.asc(),'amount_desc':Transaction.amount.desc(),'amount_asc':Transaction.amount.asc()}
    if sort not in orders: raise HTTPException(400,'Invalid sort option')
    total=int(db.scalar(select(func.count()).select_from(Transaction).where(*filters)) or 0)
    q=select(Transaction).where(*filters).order_by(orders[sort],Transaction.id).offset((page-1)*page_size).limit(page_size)
    accounts_by_id={x.id:x for x in db.scalars(select(Account).where(Account.household_id==h)).all()}; categories_by_id={x.id:x for x in db.scalars(select(Category).where(Category.household_id==h)).all()}; connections_by_id={x.id:x for x in db.scalars(select(DataConnection).where(DataConnection.household_id==h)).all()}; result=[]
    page_transactions=db.scalars(q).all(); page_ids=[item.id for item in page_transactions]
    tags_by_transaction={transaction_id:[] for transaction_id in page_ids}
    if page_ids:
        for transaction_id,tag_id,tag_name in db.execute(select(TransactionTag.transaction_id,Tag.id,Tag.name).join(Tag,Tag.id==TransactionTag.tag_id).where(TransactionTag.transaction_id.in_(page_ids))).all(): tags_by_transaction[transaction_id].append({'id':str(tag_id),'name':tag_name})
    for x in page_transactions:
        row=serialize(x);account=accounts_by_id.get(x.account_id);transaction_tags=tags_by_transaction[x.id];row.update(account_name=account.name if account else 'Unknown account',account_type=account.account_type if account else None,category_name=categories_by_id.get(x.category_id).name if x.category_id in categories_by_id else None,source_name=connections_by_id.get(x.connection_id).name if x.connection_id in connections_by_id else 'Manual',tags=transaction_tags,tag_ids=[tag['id'] for tag in transaction_tags]);result.append(row)
    return {'items':result,'page':page,'page_size':page_size,'total':total,'total_pages':max(1,(total+page_size-1)//page_size),'sort':sort}

def category_tracker_filters(h, start_date, end_date, view_user_id, db):
    validate_view_member(h,view_user_id,db)
    if start_date>end_date: raise HTTPException(400,'Start date must be on or before end date')
    account_ids=select(Account.id).where(Account.household_id==h)
    if view_user_id: account_ids=account_ids.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    return [Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.date>=start_date,Transaction.date<=end_date,Transaction.is_pending==False]

@app.get('/api/v1/category-tracker')
def category_tracker(start_date:date|None=None,end_date:date|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); today=date.today(); end=end_date or today; start=start_date or end.replace(day=1)
    ensure_groceries_category(h,db); categories=db.scalars(select(Category).where(Category.household_id==h).order_by(Category.name)).all()
    totals={str(category.id):{'id':str(category.id),'name':category.name,'kind':category.kind,'transaction_count':0,'debits':0.0,'credits':0.0,'net_amount':0.0,'activity_total':0.0} for category in categories}
    totals['uncategorized']={'id':None,'name':'Uncategorized','kind':'uncategorized','transaction_count':0,'debits':0.0,'credits':0.0,'net_amount':0.0,'activity_total':0.0}
    for transaction in db.scalars(select(Transaction).where(*category_tracker_filters(h,start,end,view_user_id,db))).all():
        row=totals.get(str(transaction.category_id),totals['uncategorized']); amount=float(transaction.amount); row['transaction_count']+=1; row['credits']+=max(amount,0); row['debits']+=abs(min(amount,0)); row['net_amount']+=amount; row['activity_total']+=abs(amount)
    return {'start_date':str(start),'end_date':str(end),'categories':list(totals.values())}

@app.get('/api/v1/category-tracker/transactions')
def category_tracker_transactions(start_date:date,end_date:date,category_id:UUID|None=None,uncategorized:bool=False,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); filters=category_tracker_filters(h,start_date,end_date,view_user_id,db)
    if uncategorized: filters.append(Transaction.category_id.is_(None))
    elif category_id:
        if not db.scalar(select(Category.id).where(Category.id==category_id,Category.household_id==h)): raise HTTPException(404,'Category not found')
        filters.append(Transaction.category_id==category_id)
    else: raise HTTPException(400,'A category is required')
    items=db.scalars(select(Transaction).where(*filters).order_by(Transaction.date.desc(),Transaction.id).limit(1000)).all(); accounts={x.id:x for x in db.scalars(select(Account).where(Account.household_id==h)).all()}
    return {'items':[dict(serialize(item),account_name=accounts.get(item.account_id).name if item.account_id in accounts else 'Unknown account') for item in items]}
@app.post('/api/v1/transactions')
def add_transaction(body:TransactionIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); a=db.get(Account,body.account_id)
    if not a or a.household_id!=h: raise HTTPException(400,'Invalid account')
    data=body.model_dump(); data['fingerprint']=hashlib.sha256(f'{body.account_id}|{body.date}|{body.amount}|{body.description.lower()}'.encode()).hexdigest()
    t=Transaction(household_id=h,**data); db.add(t); a.balance=float(a.balance)+body.amount; record_balance_snapshots(db,[a],source='manual'); db.commit(); return serialize(t)
@app.patch('/api/v1/transactions/{transaction_id}')
def update_transaction(transaction_id:UUID,body:TransactionIn,user=Depends(current_user),db:Session=Depends(get_db)):
    t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=household(user,db): raise HTTPException(404,'Transaction not found')
    for k,v in body.model_dump().items(): setattr(t,k,v)
    db.commit(); return serialize(t)
@app.patch('/api/v1/transactions/{transaction_id}/internal-transfer')
def update_internal_transfer(transaction_id:UUID,body:TransactionTransferUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=household(user,db): raise HTTPException(404,'Transaction not found')
    t.is_internal_transfer=body.is_internal_transfer;db.commit();return serialize(t)
@app.patch('/api/v1/transactions/{transaction_id}/category')
def update_transaction_category(transaction_id:UUID,body:TransactionCategoryUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=h: raise HTTPException(404,'Transaction not found')
    if body.category_id and not db.scalar(select(Category.id).where(Category.id==body.category_id,Category.household_id==h)): raise HTTPException(400,'Invalid category')
    t.category_id=body.category_id; db.commit(); return serialize(t)
@app.put('/api/v1/transactions/{transaction_id}/tags')
def update_transaction_tags(transaction_id:UUID,body:TransactionTagsUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=h: raise HTTPException(404,'Transaction not found')
    tag_ids=list(dict.fromkeys(body.tag_ids)); valid_ids=set(db.scalars(select(Tag.id).where(Tag.household_id==h,Tag.id.in_(tag_ids))).all()) if tag_ids else set()
    if len(valid_ids)!=len(tag_ids): raise HTTPException(400,'Invalid tag')
    db.execute(delete(TransactionTag).where(TransactionTag.transaction_id==t.id))
    db.add_all([TransactionTag(transaction_id=t.id,tag_id=tag_id) for tag_id in tag_ids]); db.commit()
    return {'transaction_id':str(t.id),'tag_ids':[str(tag_id) for tag_id in tag_ids]}

@app.patch('/api/v1/transactions/{transaction_id}/planner-flags')
def update_transaction_planner_flags(transaction_id:UUID,body:TransactionPlannerFlagsUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=household(user,db): raise HTTPException(404,'Transaction not found')
    changes=body.model_dump(exclude_unset=True)
    if changes.get('is_refund') and float(t.amount)<=0: raise HTTPException(400,'Only positive transactions can be refunds')
    for field,value in changes.items(): setattr(t,field,value)
    if changes.get('is_refund') is False: t.refund_included=True
    db.commit();return serialize(t)

def planner_window(period, anchor):
    if period=='monthly':
        start=anchor.replace(day=1);return start,(start.replace(day=28)+timedelta(days=4)).replace(day=1),'Monthly view',2
    if period=='paycheck':
        if anchor.day<=15: return anchor.replace(day=1),anchor.replace(day=16),'Paycheck view',1
        start=anchor.replace(day=16);return start,(start.replace(day=28)+timedelta(days=4)).replace(day=1),'Paycheck view',1
    raise HTTPException(400,'Period must be paycheck or monthly')

def add_months(value: date, months: int) -> date:
    """Return the inclusive-start date shifted by whole calendar months."""
    month_index=value.month-1+months; year=value.year+month_index//12; month=month_index%12+1
    return date(year,month,min(value.day,calendar.monthrange(year,month)[1]))

@app.get('/api/v1/available-cash-planner')
def available_cash_planner(period:str='paycheck',anchor_date:date|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    """Server-side available-cash inputs; savings-rate what-if is intentionally client-only."""
    h=household(user,db); validate_view_member(h,view_user_id,db)
    anchor=anchor_date or date.today(); start,end,label,multiplier=planner_window(period,anchor)
    account_q=select(Account).where(Account.household_id==h,Account.is_active==True)
    if view_user_id: account_q=account_q.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    accounts=db.scalars(account_q).all(); account_ids=[account.id for account in accounts]; accounts_by_id={account.id:account for account in accounts}
    categories={category.id:category for category in db.scalars(select(Category).where(Category.household_id==h)).all()}
    transactions_in_period=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.date>=start,Transaction.date<end,Transaction.is_pending==False)).all() if account_ids else []
    rules=db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.is_active==True)).all()
    designated_accounts={account.id for account in accounts if account.is_savings_direct_deposit}|{rule.account_id for rule in rules if rule.account_id}; designated_categories={rule.category_id for rule in rules if rule.category_id}; designated_tags={rule.tag_id for rule in rules if rule.tag_id}
    tagged={transaction_id for transaction_id,tag_id in db.execute(select(TransactionTag.transaction_id,TransactionTag.tag_id).where(TransactionTag.transaction_id.in_([item.id for item in transactions_in_period]),TransactionTag.tag_id.in_(designated_tags))).all()} if transactions_in_period and designated_tags else set()
    def is_debt_payment(item,account):
        category_name=(categories.get(item.category_id).name if item.category_id in categories else '').lower()
        return item.is_internal_transfer or (account.account_type!='debt' and category_name in {'debt payments','transfers'})
    paycheck=automated=refunds_total=fixed_regular=expected=0.0; refunds=[]; paycheck_sources=[]; automated_savings_sources=[]; expense_input_sources=[]; debt_items=[]
    for item in transactions_in_period:
        account=accounts_by_id[item.account_id]; amount=float(item.amount)
        # An explicit refund classification takes precedence over the transfer
        # heuristic. A reimbursement may be received in any account role.
        if amount>0 and item.is_refund:
            refunds.append({'id':str(item.id),'date':str(item.date),'description':item.description,'account_name':account.name,'amount':amount,'refund_included':item.refund_included})
            if item.refund_included: refunds_total+=amount
            continue
        if item.is_internal_transfer: continue
        automated_target=item.account_id in designated_accounts or item.category_id in designated_categories or item.id in tagged
        if amount>0:
            if automated_target:
                automated+=amount
                automated_savings_sources.append({'id':str(item.id),'date':str(item.date),'description':item.description,'account_name':account.name,'amount':amount})
            elif account.account_type=='spending':
                paycheck+=amount
                paycheck_sources.append({'id':str(item.id),'date':str(item.date),'description':item.description,'account_name':account.name,'amount':amount})
            continue
        if amount>=0 or is_debt_payment(item,account) or item.is_prorated: continue
        value=abs(amount)
        if item.is_expected:
            expected+=value
            expense_input_sources.append({'id':str(item.id),'type':'Expected','date':str(item.date),'description':item.description,'account_name':account.name,'amount':value,'period_amount':value})
        elif account.account_type=='debt':
            # Debt purchases are an as-of value: within the active paycheck or
            # month, include only activity dated on or before the selected date.
            if item.date<=anchor:
                debt_items.append({'id':str(item.id),'date':str(item.date),'description':item.description,'account_name':account.name,'amount':value})
        elif account.account_type=='spending':
            fixed_regular+=value
            expense_input_sources.append({'id':str(item.id),'type':'Fixed','date':str(item.date),'description':item.description,'account_name':account.name,'amount':value,'period_amount':value})
    prorated_candidates=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.is_prorated==True,Transaction.is_pending==False,Transaction.date<=anchor).order_by(Transaction.date.desc())).all() if account_ids else []
    active_prorated=[]
    for item in prorated_candidates:
        account=accounts_by_id[item.account_id]; duration=max(1,int(item.proration_months or 12))
        # A purchase contributes from its purchase date up to, but not including,
        # the matching duration anniversary (3, 6, 12 months, or another choice).
        if float(item.amount)<0 and not is_debt_payment(item,account) and anchor<add_months(item.date,duration): active_prorated.append(item)
    prorated_total=sum(abs(float(item.amount)) for item in active_prorated); period_divisor=(24 if period=='paycheck' else 12); prorated_expenses=sum(abs(float(item.amount))/(int(item.proration_months or 12)*period_divisor/12) for item in active_prorated)
    for item in active_prorated:
        account=accounts_by_id[item.account_id]; value=abs(float(item.amount)); duration=int(item.proration_months or 12); expense_input_sources.append({'id':str(item.id),'type':'Prorated','date':str(item.date),'description':item.description,'account_name':account.name,'amount':value,'proration_months':duration,'period_amount':value/(duration*period_divisor/12)})
    # Refunds are expense credits, rather than income. This keeps NMP limited to
    # paycheck and automated-savings inflows while transparently reducing costs.
    raw_nmp=paycheck+automated; nmp_paycheck=raw_nmp/multiplier; net_monthly_pay=nmp_paycheck*2
    regular_expected_prorated=fixed_regular+expected+prorated_expenses; debt_total=sum(item['amount'] for item in debt_items)
    gross_total_expenses=regular_expected_prorated+debt_total; total_expenses=gross_total_expenses-refunds_total
    return {'period':period,'period_label':label,'period_start':str(start),'period_end':str(end-timedelta(days=1)),'debt_line_item_through':str(anchor),'paycheck_amount':paycheck,'paycheck_sources':paycheck_sources,'automated_savings_amount':automated,'automated_savings_sources':automated_savings_sources,'included_refunds':refunds_total,'refund_expense_offset':refunds_total,'nmp_paycheck':nmp_paycheck,'net_monthly_pay':net_monthly_pay,'fixed_regular_expenses':fixed_regular,'expected_expenses':expected,'prorated_expense_total':prorated_total,'prorated_expenses':prorated_expenses,'regular_expected_prorated_expenses':regular_expected_prorated,'expense_input_sources':expense_input_sources,'debt_line_items':debt_items,'debt_line_item_total':debt_total,'gross_total_period_expenses':gross_total_expenses,'total_period_expenses':total_expenses,'free_spending_before_savings':net_monthly_pay-total_expenses,'refunds':refunds}

@app.get('/api/v1/categories')
def categories(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); ensure_groceries_category(h,db); return [serialize(x) for x in db.scalars(select(Category).where(Category.household_id==h).order_by(Category.name)).all()]
@app.post('/api/v1/categories')
def add_category(body:CategoryIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); name=body.name.strip()
    if body.kind not in {'income','expense','transfer','other'}: raise HTTPException(400,'Invalid category kind')
    if db.scalar(select(Category.id).where(Category.household_id==h,func.lower(Category.name)==name.lower())): raise HTTPException(409,'A category with this name already exists')
    c=Category(household_id=h,name=name,kind=body.kind,is_essential_default=body.is_essential_default);db.add(c);db.commit();return serialize(c)
@app.patch('/api/v1/categories/{category_id}')
def rename_category(category_id:UUID,body:CategoryRename,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); category=db.get(Category,category_id); name=body.name.strip()
    if not category or category.household_id!=h: raise HTTPException(404,'Category not found')
    if db.scalar(select(Category.id).where(Category.household_id==h,func.lower(Category.name)==name.lower(),Category.id!=category.id)): raise HTTPException(409,'A category with this name already exists')
    category.name=name;db.commit();return serialize(category)
@app.delete('/api/v1/categories/{category_id}')
def delete_category(category_id:UUID,body:CategoryDelete,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); category=db.get(Category,category_id); replacement=db.get(Category,body.replacement_category_id)
    if not category or category.household_id!=h: raise HTTPException(404,'Category not found')
    if not replacement or replacement.household_id!=h or replacement.id==category.id: raise HTTPException(400,'Select a different replacement category')
    # Keep all financial records intact: only their category pointer is reassigned.
    for transaction in db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.category_id==category.id)).all(): transaction.category_id=replacement.id
    for rule in db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.category_id==category.id)).all(): rule.category_id=replacement.id
    db.delete(category);db.commit();return {'deleted_category_id':str(category_id),'replacement_category_id':str(replacement.id)}
@app.get('/api/v1/tags')
def tags(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(Tag).where(Tag.household_id==household(user,db))).all()]
@app.post('/api/v1/tags')
def add_tag(name:str,user=Depends(current_user),db:Session=Depends(get_db)):
    x=Tag(household_id=household(user,db),name=name);db.add(x);db.commit();return serialize(x)
@app.get('/api/v1/savings-rules')
def savings_rules(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); rows=[]
    for rule in db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.is_active==True)).all():
        target_type,target_id,label=('account',rule.account_id,db.get(Account,rule.account_id).name) if rule.account_id else ('category',rule.category_id,db.get(Category,rule.category_id).name) if rule.category_id else ('tag',rule.tag_id,db.get(Tag,rule.tag_id).name)
        rows.append({**serialize(rule),'target_type':target_type,'target_id':str(target_id),'label':label})
    return rows
@app.post('/api/v1/savings-rules')
def add_savings_rule(body:SavingsRuleIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); targets={'account':Account,'category':Category,'tag':Tag}
    if body.target_type not in targets: raise HTTPException(400,'Target type must be account, category, or tag')
    target=db.get(targets[body.target_type],body.target_id)
    if not target or target.household_id!=h: raise HTTPException(400,'Invalid savings rule target')
    field=f'{body.target_type}_id'
    if db.scalar(select(SavingsRule).where(SavingsRule.household_id==h,getattr(SavingsRule,field)==body.target_id,SavingsRule.is_active==True)): raise HTTPException(409,'Savings rule already exists')
    rule=SavingsRule(household_id=h,**{field:body.target_id});db.add(rule);db.commit();return serialize(rule)
@app.delete('/api/v1/savings-rules/{rule_id}',status_code=204)
def delete_savings_rule(rule_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    rule=db.get(SavingsRule,rule_id)
    if not rule or rule.household_id!=household(user,db): raise HTTPException(404,'Savings rule not found')
    db.delete(rule);db.commit()
@app.get('/api/v1/income-sources')
def income_sources(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(IncomeSource).where(IncomeSource.household_id==household(user,db))).all()]
@app.post('/api/v1/income-sources')
def add_income(body:IncomeIn,user=Depends(current_user),db:Session=Depends(get_db)):
    x=IncomeSource(household_id=household(user,db),**body.model_dump());db.add(x);db.commit();return serialize(x)
@app.get('/api/v1/debts')
def debts(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(Debt).where(Debt.household_id==household(user,db))).all()]
@app.get('/api/v1/forecasting-profiles')
def profiles(user=Depends(current_user),db:Session=Depends(get_db)): return [serialize(x) for x in db.scalars(select(ForecastingProfile).where(ForecastingProfile.household_id==household(user,db))).all()]

def _months_remaining(target_date):
    if not target_date or target_date<date.today(): return None
    return max(1,(target_date.year-date.today().year)*12+target_date.month-date.today().month+(1 if target_date.day>date.today().day else 0))

@app.get('/api/v1/goals')
def goals(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); result=[]
    for g in db.scalars(select(Goal).where(Goal.household_id==h).order_by(Goal.priority_order,Goal.created_at)).all():
        current=float(g.current_amount);target=float(g.target_amount);months=_months_remaining(g.target_date);remaining=max(0,target-current);row=serialize(g);row.update(saved_amount=current,progress=round(current/target*100,1) if target else 0,remaining_amount=remaining,months_remaining=months,required_monthly_contribution=round(remaining/months,2) if months else None);result.append(row)
    return result
@app.post('/api/v1/goals')
def add_goal(body:GoalIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db);last_priority=db.scalar(select(func.max(Goal.priority_order)).where(Goal.household_id==h));priority=(int(last_priority) if last_priority is not None else -1)+1;g=Goal(household_id=h,priority_order=priority,**body.model_dump());db.add(g);db.commit();return serialize(g)
@app.patch('/api/v1/goals/{goal_id}')
def update_goal(goal_id:UUID,body:GoalUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    g=db.get(Goal,goal_id)
    if not g or g.household_id!=household(user,db): raise HTTPException(404,'Goal not found')
    g.name,g.target_amount,g.current_amount,g.target_date=body.name,body.target_amount,body.current_amount,body.target_date
    db.commit();return serialize(g)
@app.put('/api/v1/goals/reorder')
def reorder_goals(body:GoalPriorityUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db);existing=db.scalars(select(Goal).where(Goal.household_id==h)).all();by_id={x.id:x for x in existing}
    if len(body.goal_ids)!=len(existing) or len(set(body.goal_ids))!=len(body.goal_ids) or set(body.goal_ids)!=set(by_id): raise HTTPException(400,'Goal order must contain every household goal exactly once')
    for priority,goal_id in enumerate(body.goal_ids): by_id[goal_id].priority_order=priority
    db.commit();return goals(user,db)
@app.delete('/api/v1/goals/{goal_id}',status_code=204)
def delete_goal(goal_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    g=db.get(Goal,goal_id)
    if not g or g.household_id!=household(user,db): raise HTTPException(404,'Goal not found')
    db.delete(g);db.commit()
@app.post('/api/v1/goals/{goal_id}/contributions')
def contribute(goal_id:UUID,amount:float,user=Depends(current_user),db:Session=Depends(get_db)):
    g=db.get(Goal,goal_id)
    if not g or g.household_id!=household(user,db): raise HTTPException(404,'Goal not found')
    x=GoalContribution(goal_id=goal_id,amount=amount);g.current_amount=float(g.current_amount)+amount;db.add(x);db.commit();return serialize(x)

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
    # This transaction intentionally touches only data owned by this connection.
    # The connection row contains its encrypted provider token; its deletion removes it.
    for transaction in db.scalars(select(Transaction).where(Transaction.connection_id==x.id)).all(): db.delete(transaction)
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
    h=household(user,db)
    x=DataConnection(household_id=h,provider='plaid',name=next_connection_name(h,'plaid',body.name,db),encrypted_credentials=encrypt_credentials({'access_token':raw['access_token']}))
    try:
        db.add(x);db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409,'This Plaid authorization could not be saved. Please retry the link flow.') from exc
    return serialize_connection(x)
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

def monthly_breakdown(accounts, transactions, rules, db, manual_income=0.0):
    """Apply the savings engine to one calendar month's transactions."""
    accounts_by_id={account.id:account for account in accounts}
    designated_accounts={account.id for account in accounts if account.is_savings_direct_deposit}|{rule.account_id for rule in rules if rule.account_id}
    designated_categories={rule.category_id for rule in rules if rule.category_id}
    designated_tags={rule.tag_id for rule in rules if rule.tag_id}
    tagged_transactions={transaction_id for transaction_id,tag_id in db.execute(select(TransactionTag.transaction_id,TransactionTag.tag_id).where(TransactionTag.transaction_id.in_([item.id for item in transactions]),TransactionTag.tag_id.in_(designated_tags))).all()} if transactions and designated_tags else set()
    connection_names=dict(db.execute(select(DataConnection.id,DataConnection.name).where(DataConnection.id.in_([account.connection_id for account in accounts if account.connection_id]))).all())
    sources={}
    def source_row(account):
        if account.id not in sources:
            sources[account.id]={'account_id':str(account.id),'account_name':account.name,'source_name':connection_names.get(account.connection_id,'Manual'),'account_type':account.account_type,'income':0.0,'expenses':0.0,'automated_savings':0.0,'spending_cash_flow':0.0}
        return sources[account.id]
    automated=spending_net=expenses=essential=transaction_income=0.0
    for item in transactions:
        if item.is_internal_transfer: continue
        account=accounts_by_id[item.account_id]; amount=float(item.amount)
        automated_target=item.account_id in designated_accounts or item.category_id in designated_categories or item.id in tagged_transactions
        if amount>0 and automated_target:
            automated+=amount; transaction_income+=amount
            source=source_row(account); source['income']+=amount; source['automated_savings']+=amount
            continue
        if account.account_type=='spending' and item.account_id not in designated_accounts:
            spending_net+=amount
            source=source_row(account); source['spending_cash_flow']+=amount
            if amount>0:
                transaction_income+=amount; source['income']+=amount
            elif amount<0:
                expenses-=amount; source['expenses']-=amount
                if item.is_essential: essential-=amount
    income=transaction_income if transaction_income else manual_income
    return {'monthly_income':income,'monthly_expenses':expenses,'monthly_savings':automated+spending_net,'automated_savings':automated,'spending_net_cash_flow':spending_net,'savings_rate':round((automated+spending_net)/income*100,1) if income else 0,'essential_monthly':essential,'monthly_sources':[ {**row,**{key:round(value,2) if isinstance(value,float) else value for key,value in row.items()}} for row in sorted(sources.values(),key=lambda row:row['account_name'].lower())]}

def metrics(h,db,view_user_id=None,period='calendar_month'):
    q=select(Account).where(Account.household_id==h,Account.is_active==True)
    validate_view_member(h,view_user_id,db)
    if view_user_id: q=q.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    accounts=db.scalars(q).all(); account_ids=[x.id for x in accounts]; accounts_by_id={x.id:x for x in accounts}; debt_accounts=sum(abs(float(x.balance)) for x in accounts if x.account_type=='debt'); assets=sum(float(x.crypto_usd_value or 0) if x.account_type=='crypto' else float(x.balance) for x in accounts if x.account_type!='debt'); legacy_debt=float(db.scalar(select(func.coalesce(func.sum(Debt.balance),0)).where(Debt.household_id==h)) or 0); debt=debt_accounts+legacy_debt
    income_q=select(func.coalesce(func.sum(IncomeSource.monthly_amount),0)).where(IncomeSource.household_id==h,IncomeSource.is_active==True)
    if view_user_id: income_q=income_q.where(or_(IncomeSource.owner_id==None,IncomeSource.owner_id==view_user_id))
    manual_income=float(db.scalar(income_q) or 0)
    if period=='rolling_30_days':
        month_start=date.today()-timedelta(days=29);month_end=date.today()+timedelta(days=1)
    elif period=='calendar_month':
        month_start=date.today().replace(day=1);month_end=(month_start.replace(day=28)+timedelta(days=4)).replace(day=1)
    else: raise HTTPException(400,'Period must be calendar_month or rolling_30_days')
    tx=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.date>=month_start,Transaction.date<month_end,Transaction.is_pending==False)).all() if account_ids else []
    rules=db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.is_active==True)).all()
    monthly=monthly_breakdown(accounts,tx,rules,db,manual_income)
    designated_accounts={x.id for x in accounts if x.is_savings_direct_deposit}|{x.account_id for x in rules if x.account_id}
    spending_balance=sum(float(x.balance) for x in accounts if x.account_type=='spending' and x.id not in designated_accounts);ceiling=float(db.get(Household,h).checking_account_ceiling)
    return {'net_worth':assets-debt,'cash_available':sum(float(x.balance) for x in accounts if x.account_type in ('spending','income')),'debt_total':debt,**monthly,'period':period,'period_start':str(month_start),'period_end':str(month_end-timedelta(days=1)),'checking_account_ceiling':ceiling,'spending_balance':spending_balance,'sweep_surplus':max(0,spending_balance-ceiling)}
@app.get('/api/v1/dashboard')
def dashboard(period:str='calendar_month',view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); q=select(Account).where(Account.household_id==h,Account.account_type=='crypto',Account.is_active==True)
    if view_user_id: q=q.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    crypto_accounts=db.scalars(q).all()
    if refresh_usd_values(crypto_accounts): db.commit()
    m=metrics(h,db,view_user_id,period); crypto={}
    for a in crypto_accounts:
        if float(a.balance):
            symbol=a.asset_symbol or a.name
            entry=crypto.setdefault(symbol,{'symbol':symbol,'quantity':0.0,'usd_value':0.0,'quote_available':False,'price_updated_at':None})
            entry['quantity']+=float(a.balance)
            if a.crypto_usd_value is not None: entry['usd_value']+=float(a.crypto_usd_value);entry['quote_available']=True;entry['price_updated_at']=str(a.crypto_price_updated_at) if a.crypto_price_updated_at else entry['price_updated_at']
    m.update(goals=goals(user,db),crypto_assets=[crypto[k] for k in sorted(crypto)],alerts=['Emergency fund is below six months of essential spending'] if m['cash_available']<m['essential_monthly']*6 else []);return m
@app.get('/api/v1/finance/trends')
def finance_trends(months:int=6,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    """Monthly, scope-aware trend points calculated from normalized transactions."""
    if months<3 or months>24: raise HTTPException(400,'Months must be between 3 and 24')
    h=household(user,db); validate_view_member(h,view_user_id,db)
    accounts_q=select(Account).where(Account.household_id==h,Account.is_active==True)
    if view_user_id: accounts_q=accounts_q.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    accounts=db.scalars(accounts_q).all(); account_ids=[account.id for account in accounts]
    income_q=select(func.coalesce(func.sum(IncomeSource.monthly_amount),0)).where(IncomeSource.household_id==h,IncomeSource.is_active==True)
    if view_user_id: income_q=income_q.where(or_(IncomeSource.owner_id==None,IncomeSource.owner_id==view_user_id))
    manual_income=float(db.scalar(income_q) or 0)
    current_month=date.today().replace(day=1)
    month_starts=[]
    for offset in range(months-1,-1,-1):
        absolute_month=current_month.year*12+(current_month.month-1)-offset
        month_starts.append(date(absolute_month//12,absolute_month%12+1,1))
    range_end=(current_month.replace(day=28)+timedelta(days=4)).replace(day=1)
    transactions_in_range=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.date>=month_starts[0],Transaction.date<range_end,Transaction.is_pending==False)).all() if account_ids else []
    rules=db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.is_active==True)).all()
    series=[]
    for month_start in month_starts:
        month_end=(month_start.replace(day=28)+timedelta(days=4)).replace(day=1)
        point=monthly_breakdown(accounts,[item for item in transactions_in_range if month_start<=item.date<month_end],rules,db,manual_income)
        series.append({'month':str(month_start),'label':month_start.strftime('%b %Y'),**point})
    return {'months':months,'series':series}

def report_timeframe_dates(timeframe: str, db: Session, household_id, account_ids: list[UUID]) -> list[date]:
    today=date.today(); valid={'1M','3M','6M','YTD','1Y','All'}
    if timeframe not in valid: raise HTTPException(400,'Timeframe must be 1M, 3M, 6M, YTD, 1Y, or All')
    if timeframe=='1M': return [today-timedelta(days=offset) for offset in range(29,-1,-1)]
    if timeframe=='3M': start=today-timedelta(days=89); return [start+timedelta(days=offset) for offset in range(0,90,7)]+[today]
    if timeframe=='6M': months=6
    elif timeframe=='YTD': months=today.month
    elif timeframe=='1Y': months=12
    else:
        earliest=db.scalar(select(func.min(Transaction.date)).where(Transaction.household_id==household_id,Transaction.account_id.in_(account_ids))) if account_ids else None
        snapshot_earliest=db.scalar(select(func.min(AccountBalanceSnapshot.snapshot_date)).where(AccountBalanceSnapshot.household_id==household_id,AccountBalanceSnapshot.account_id.in_(account_ids))) if account_ids else None
        starts=[value for value in (earliest,snapshot_earliest) if value]
        first=min(starts) if starts else today
        months=min(60,max(1,(today.year-first.year)*12+today.month-first.month+1))
    first_month=today.replace(day=1)
    return [date((first_month.year*12+first_month.month-1-offset-1)//12,(first_month.year*12+first_month.month-1-offset-1)%12+1,1) for offset in range(months-1,-1,-1)] + [today]

@app.get('/api/v1/reports')
def reports(timeframe:str='3M',view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    """Scope-aware reporting built from snapshots, normalized transactions, and current account data."""
    h=household(user,db); validate_view_member(h,view_user_id,db)
    account_q=select(Account).where(Account.household_id==h,Account.is_active==True)
    if view_user_id: account_q=account_q.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    accounts=db.scalars(account_q).all(); account_ids=[account.id for account in accounts]; account_by_id={account.id:account for account in accounts}
    record_balance_snapshots(db,accounts); db.commit()
    dates=report_timeframe_dates(timeframe,db,h,account_ids)
    snapshots=db.scalars(select(AccountBalanceSnapshot).where(AccountBalanceSnapshot.account_id.in_(account_ids),AccountBalanceSnapshot.snapshot_date<=date.today()).order_by(AccountBalanceSnapshot.snapshot_date) if account_ids else select(AccountBalanceSnapshot).where(False)).all()
    snapshots_by_account={account.id:[] for account in accounts}
    for snapshot in snapshots: snapshots_by_account.setdefault(snapshot.account_id,[]).append(snapshot)
    all_transactions=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.date<=date.today(),Transaction.is_pending==False) if account_ids else select(Transaction).where(False)).all()
    def historical_value(account, point):
        matches=[snapshot for snapshot in snapshots_by_account.get(account.id,[]) if snapshot.snapshot_date<=point]
        if matches:
            latest=matches[-1]; return float(latest.usd_value) if account.account_type=='crypto' and latest.usd_value is not None else float(latest.balance)
        # Pre-snapshot transaction backfill is an estimate. Future snapshots replace it with observed balances.
        later=sum(float(item.amount) for item in all_transactions if item.account_id==account.id and item.date>point)
        if account.account_type=='crypto': return float(account.crypto_usd_value or 0)
        return float(account.balance)-later
    net_worth_series=[]
    for point in dates:
        types={name:0.0 for name in ('spending','income','brokerage','crypto','debt')}; assets=debt=0.0
        for account in accounts:
            value=historical_value(account,point)
            if account.account_type=='debt': debt+=abs(value); types['debt']+=abs(value)
            else: assets+=value; types[account.account_type]=types.get(account.account_type,0)+value
        net_worth_series.append({'date':str(point),'label':point.strftime('%b %-d' if timeframe in {'1M','3M'} else '%b %Y'),'assets':round(assets,2),'liabilities':round(debt,2),'net_worth':round(assets-debt,2),'by_account_type':{key:round(value,2) for key,value in types.items()}})
    start=dates[0]; expense_transactions=[item for item in all_transactions if start<=item.date<=date.today() and float(item.amount)<0 and not item.is_internal_transfer and account_by_id[item.account_id].account_type in {'spending','debt'}]
    categories={category.id:category.name for category in db.scalars(select(Category).where(Category.household_id==h)).all()}
    category_totals={}
    for item in expense_transactions: category_totals[categories.get(item.category_id,'Uncategorized')]=category_totals.get(categories.get(item.category_id,'Uncategorized'),0)+abs(float(item.amount))
    monthly_points=[]; month_cursor=start.replace(day=1); current_month=date.today().replace(day=1)
    while month_cursor<=current_month:
        month_end=(month_cursor.replace(day=28)+timedelta(days=4)).replace(day=1)
        month_items=[item for item in expense_transactions if month_cursor<=item.date<month_end]
        recurring=sum(abs(float(item.amount)) for item in month_items if item.is_recurring or item.is_expected or item.is_prorated)
        discretionary=sum(abs(float(item.amount)) for item in month_items if not (item.is_recurring or item.is_expected or item.is_prorated))
        monthly_points.append({'month':str(month_cursor),'label':month_cursor.strftime('%b %Y'),'recurring':round(recurring,2),'discretionary':round(discretionary,2),'total':round(recurring+discretionary,2)})
        month_cursor=month_end
    latest_spend=monthly_points[-1]['total'] if monthly_points else 0; previous_spend=monthly_points[-2]['total'] if len(monthly_points)>1 else 0
    month_days=((current_month.replace(day=28)+timedelta(days=4)).replace(day=1)-current_month).days; elapsed=max(1,(date.today()-current_month).days+1)
    average_spend=sum(point['total'] for point in monthly_points)/len(monthly_points) if monthly_points else 0
    current_values={account.id:(float(account.crypto_usd_value or 0) if account.account_type=='crypto' else float(account.balance)) for account in accounts}
    investment_accounts=[account for account in accounts if account.account_type in {'brokerage','crypto'}]
    investment_value=sum(current_values[account.id] for account in investment_accounts)
    investment_contributions=sum(float(item.amount) for item in all_transactions if item.account_id in {account.id for account in investment_accounts} and float(item.amount)>0 and not item.is_internal_transfer)
    allocation=[{'name':account.name,'type':account.account_type,'value':round(current_values[account.id],2)} for account in investment_accounts if current_values[account.id]!=0]
    latest_month_transactions=[item for item in all_transactions if current_month<=item.date<=date.today()]
    rules=db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.is_active==True)).all()
    current_cash=monthly_breakdown(accounts,latest_month_transactions,rules,db)
    target=float(db.get(Household,h).checking_account_ceiling or 0) or average_spend
    current_net=net_worth_series[-1]['net_worth'] if net_worth_series else 0; previous_net=net_worth_series[0]['net_worth'] if net_worth_series else 0
    return {'timeframe':timeframe,'net_worth':{'current':current_net,'change':round(current_net-previous_net,2),'change_percent':round(((current_net-previous_net)/abs(previous_net))*100,1) if previous_net else 0,'series':net_worth_series},'investments':{'current_value':round(investment_value,2),'net_contributions':round(investment_contributions,2),'return_amount':round(investment_value-investment_contributions,2),'return_percent':round(((investment_value-investment_contributions)/investment_contributions)*100,1) if investment_contributions else None,'allocation':allocation},'cost_of_living':{'average_monthly_spend':round(average_spend,2),'projected_month_end_spend':round(latest_spend/elapsed*month_days,2),'month_over_month_percent':round(((latest_spend-previous_spend)/previous_spend)*100,1) if previous_spend else None,'series':monthly_points,'recurring_total':round(sum(point['recurring'] for point in monthly_points),2),'discretionary_total':round(sum(point['discretionary'] for point in monthly_points),2)},'cash_flow':{'income':current_cash['monthly_income'],'savings':current_cash['monthly_savings'],'expenses':current_cash['monthly_expenses'],'categories':[{'name':name,'value':round(value,2)} for name,value in sorted(category_totals.items(),key=lambda row:row[1],reverse=True)]},'simple_mode':{'net_worth_trend':net_worth_series,'spend_target':{'actual':round(latest_spend,2),'target':round(target,2),'target_source':'Checking ceiling' if float(db.get(Household,h).checking_account_ceiling or 0) else 'Average monthly spend'},'top_categories':[{'name':name,'value':round(value,2)} for name,value in sorted(category_totals.items(),key=lambda row:row[1],reverse=True)[:3]]}}
@app.get('/api/v1/forecast')
def forecast(monthly_savings:float|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); m=metrics(h,db,view_user_id); savings=monthly_savings if monthly_savings is not None else m['monthly_savings']; output=[];elapsed=0.0;lump_sum=m['sweep_surplus']
    for g in goals(user,db):
        remaining=float(g['remaining_amount']);sweep=min(remaining,lump_sum);remaining-=sweep;lump_sum-=sweep;months=remaining/savings if savings>0 else (0 if remaining==0 else None);completion=elapsed+(months or 0) if months is not None else None
        output.append({'goal':g['name'],'priority_order':g['priority_order'],'monthly_savings':savings,'one_time_sweep':sweep,'months_to_complete':round(completion,1) if completion is not None else None,'projected_completion':str(date.today()+timedelta(days=round(completion*30.44))) if completion is not None else None,'required_monthly_contribution':g['required_monthly_contribution']})
        if months is not None: elapsed+=months
    return {'projected_savings_12_months':savings*12,'one_time_sweep_surplus':m['sweep_surplus'],'goals':output}
@app.get('/api/v1/analysis/live-on-one-income')
def one_income(view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db);m=metrics(h,db,view_user_id); income_q=select(IncomeSource).where(IncomeSource.household_id==h,IncomeSource.is_active==True)
    if view_user_id: income_q=income_q.where(or_(IncomeSource.owner_id==None,IncomeSource.owner_id==view_user_id))
    incomes=db.scalars(income_q).all(); return {'monthly_expenses':m['monthly_expenses'],'scenarios':[{'name':x.name,'income':float(x.monthly_amount),'surplus':float(x.monthly_amount)-m['monthly_expenses'],'sustainable':float(x.monthly_amount)>=m['monthly_expenses']} for x in incomes]+[{'name':'Combined income','income':m['monthly_income'],'surplus':m['monthly_savings'],'sustainable':m['monthly_savings']>=0}]}

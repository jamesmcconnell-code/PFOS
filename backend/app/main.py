import calendar, csv, hashlib, io, json
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, func, or_, and_, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .database import get_db
from .models import *
from .schemas import *
from .security import hash_password, verify_password, create_token, decode_token
from .connectors import CONNECTORS, ConnectorAuthenticationError, PlaidReauthorizationRequired, PlaidNewConnectionRequired, CsvConnector, decrypt_credentials, encrypt_credentials, persist_payload
from .crypto_prices import refresh_usd_values
from .config import settings
from . import plaid_configuration
from .planner_schedule import adjacent_period_start, biweekly_period_bounds, period_bounds, periods_per_year, semimonthly_period_bounds
from .smart_tagging import apply_suggestion, evaluate_new_transaction, latest_suggestion, matching_rule, normalize_merchant_key
from .smart_tagging_learning import generate_historical_suggestion

app=FastAPI(title='PFOS API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=[origin.strip() for origin in settings.cors_origins.split(',') if origin.strip()], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
bearer=HTTPBearer()
def plaid_request_credentials():
    try: return plaid_configuration.credentials()
    except ValueError as error: raise HTTPException(503, str(error)) from None
def current_user(c: HTTPAuthorizationCredentials=Depends(bearer), db: Session=Depends(get_db)):
    try: user_id=UUID(decode_token(c.credentials))
    except (ValueError, TypeError, AttributeError): raise HTTPException(401,'Invalid token subject')
    user=db.get(User, user_id)
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
def ensure_loan_reimbursement_tag(household_id, db: Session):
    """Provide the household-wide tag used to exclude loan reimbursements from savings."""
    tag=db.scalar(select(Tag).where(Tag.household_id==household_id,func.lower(Tag.name)=='loan reimbursement'))
    if not tag:
        try:
            tag=Tag(household_id=household_id,name='Loan reimbursement')
            db.add(tag); db.commit(); db.refresh(tag)
        except IntegrityError:
            db.rollback()
            tag=db.scalar(select(Tag).where(Tag.household_id==household_id,func.lower(Tag.name)=='loan reimbursement'))
    return tag
def category_matches_rule(category_id, rule_category_ids, parent_ids):
    """A child inherits every category-level rule from its ancestor chain."""
    current=category_id; seen=set()
    while current and current not in seen:
        if current in rule_category_ids: return True
        seen.add(current); current=parent_ids.get(current)
    return False
def category_descendants(category_id, parent_ids):
    descendants=set(); pending=[category_id]
    while pending:
        parent=pending.pop()
        children=[child for child,child_parent in parent_ids.items() if child_parent==parent and child not in descendants]
        descendants.update(children); pending.extend(children)
    return descendants
def serialize(o):
    def value(raw):
        return str(raw) if isinstance(raw,(UUID,date,datetime,Decimal)) else raw
    return {c.name:value(getattr(o,c.name)) if getattr(o,c.name) is not None else None for c in o.__table__.columns}
def smart_tagging_scope(query, model, view_user_id: UUID|None):
    return query.where(or_(model.owner_id.is_(None),model.owner_id==view_user_id)) if view_user_id else query.where(model.owner_id.is_(None))
def validate_smart_tagging_references(h, values, db: Session):
    if not values.get('normalized_merchant_key') and not values.get('description_pattern'):
        raise HTTPException(400,'A merchant key or description pattern is required')
    if values.get('direction','any') not in {'any','credit','debit'}: raise HTTPException(400,'Direction must be any, credit, or debit')
    if values.get('financial_role') not in {None,'spending','income','debt','brokerage','crypto'}: raise HTTPException(400,'Invalid financial role')
    if values.get('source_type','user_authored') not in {'user_authored','learned'}: raise HTTPException(400,'Source type must be user_authored or learned')
    if values.get('prorated') is False and values.get('proration_months') is not None: raise HTTPException(400,'Proration months require a prorated rule')
    for field,model in [('owner_id',User),('classified_owner_id',User)]:
        identifier=values.get(field)
        if identifier and not db.scalar(select(HouseholdMember).where(HouseholdMember.household_id==h,HouseholdMember.user_id==identifier)): raise HTTPException(400,f'{field} must belong to this household')
    account_id=values.get('account_id')
    if account_id:
        account=db.get(Account,account_id)
        if not account or account.household_id!=h: raise HTTPException(400,'Account must belong to this household')
        if account.ownership=='individual' and values.get('classified_owner_id') and account.owner_id!=values['classified_owner_id']: raise HTTPException(400,'An individual-account owner assignment must match the account owner')
    category_id=values.get('category_id')
    if category_id:
        category=db.get(Category,category_id)
        if not category or category.household_id!=h: raise HTTPException(400,'Category must belong to this household')
    tag_ids=values.get('tag_ids',[])
    if len(tag_ids)!=len(set(tag_ids)): raise HTTPException(400,'Tag IDs must be unique')
    if tag_ids and db.scalar(select(func.count(Tag.id)).where(Tag.household_id==h,Tag.id.in_(tag_ids)))!=len(tag_ids): raise HTTPException(400,'Tags must belong to this household')
def serialize_classification_rule(rule, h, db: Session):
    tags=db.execute(select(Tag.id,Tag.name).join(TransactionClassificationRuleTag,TransactionClassificationRuleTag.tag_id==Tag.id).where(TransactionClassificationRuleTag.rule_id==rule.id,Tag.household_id==h)).all()
    return dict(serialize(rule),tag_ids=[str(tag.id) for tag in tags],tags=[{'id':str(tag.id),'name':tag.name} for tag in tags])
def serialize_classification_suggestion(suggestion, h, db: Session):
    tags=db.execute(select(Tag.id,Tag.name).join(TransactionClassificationSuggestionTag,TransactionClassificationSuggestionTag.tag_id==Tag.id).where(TransactionClassificationSuggestionTag.suggestion_id==suggestion.id,Tag.household_id==h)).all()
    decisions=[serialize(item) for item in db.scalars(select(TransactionClassificationSuggestionDecision).where(TransactionClassificationSuggestionDecision.suggestion_id==suggestion.id).order_by(TransactionClassificationSuggestionDecision.created_at)).all()]
    row=serialize(suggestion);row['proposal_data']=json.loads(suggestion.proposal_data or '{}');row['evidence_data']=json.loads(suggestion.evidence_data or '{}')
    transaction=db.get(Transaction,suggestion.transaction_id);account=db.get(Account,transaction.account_id) if transaction else None
    source=None if not transaction else {'id':str(transaction.id),'date':str(transaction.date),'description':transaction.description,'amount':float(transaction.amount),'account_id':str(transaction.account_id),'account_name':account.name if account else 'Unknown account','account_type':account.account_type if account else None,'owner_id':str(transaction.owner_id or (account.owner_id if account else '')) or None}
    return dict(row,tag_ids=[str(tag.id) for tag in tags],tags=[{'id':str(tag.id),'name':tag.name} for tag in tags],decisions=decisions,transaction=source)
def smart_tagging_metadata(transaction, h, db: Session):
    key=normalize_merchant_key(transaction.description)
    identity=db.scalar(select(MerchantIdentity).where(MerchantIdentity.household_id==h,MerchantIdentity.normalized_merchant_key==key))
    rule=db.get(TransactionClassificationRule,transaction.classification_rule_id) if transaction.classification_rule_id else None
    suggestion=latest_suggestion(transaction.id,db)
    return {'normalized_merchant_key':key,'merchant_display_name':identity.display_name if identity else None,'smart_tagging':{'applied_rule_id':str(rule.id) if rule else None,'applied_rule_name':rule.name if rule else None,'suggestion_id':str(suggestion.id) if suggestion else None,'suggestion_status':suggestion.status if suggestion else None,'confidence_score':float(suggestion.confidence_score) if suggestion else None,'proposal_data':json.loads(suggestion.proposal_data or '{}') if suggestion else {},'evidence_data':json.loads(suggestion.evidence_data or '{}') if suggestion else {},'explanation':transaction.classification_explanation or (suggestion.explanation if suggestion else None)}}
def suggestion_fields(suggestion, db: Session|None=None):
    proposed=(json.loads(suggestion.proposal_data or '{}').get('fields') or {})
    if proposed: return proposed
    fields={}
    for name in ('category_id','owner_id','essential','internal_transfer','refund_credit','loan_reimbursement','expected','prorated','proration_months'):
        value=getattr(suggestion,name)
        if value is not None: fields[name]={'value':str(value) if isinstance(value,UUID) else value}
    if db:
        tag_ids=[str(tag_id) for tag_id in db.scalars(select(TransactionClassificationSuggestionTag.tag_id).where(TransactionClassificationSuggestionTag.suggestion_id==suggestion.id)).all()]
        if tag_ids: fields['tag_ids']={'value':tag_ids}
    return fields
def record_suggestion_decision(suggestion, field_name, decision, value, db: Session):
    row=db.scalar(select(TransactionClassificationSuggestionDecision).where(TransactionClassificationSuggestionDecision.suggestion_id==suggestion.id,TransactionClassificationSuggestionDecision.field_name==field_name))
    if row:
        if row.decision!=decision: raise HTTPException(409,f'{field_name} was already {row.decision}')
        return row
    row=TransactionClassificationSuggestionDecision(suggestion_id=suggestion.id,field_name=field_name,decision=decision,value_data=json.dumps(value));db.add(row);return row
def apply_suggestion_fields(suggestion, fields, db: Session):
    transaction=db.get(Transaction,suggestion.transaction_id)
    if not transaction: raise HTTPException(404,'Transaction not found')
    proposed=suggestion_fields(suggestion,db); requested=set(fields or proposed.keys())
    if not requested or not requested.issubset(set(proposed)): raise HTTPException(400,'Select only proposed suggestion fields')
    account=db.get(Account,transaction.account_id)
    for field in requested:
        value=proposed[field]['value'] if isinstance(proposed[field],dict) else proposed[field]
        record_suggestion_decision(suggestion,field,'accepted',value,db)
        if field=='category_id': transaction.category_id=UUID(str(value))
        elif field=='owner_id' and (account.ownership!='individual' or account.owner_id==UUID(str(value))): transaction.owner_id=UUID(str(value))
        elif field=='essential': transaction.is_essential=bool(value)
        elif field=='recurring': transaction.is_recurring=bool(value)
        elif field=='tag_ids':
            for tag_id in value:
                parsed=UUID(str(tag_id))
                if not db.get(TransactionTag,(transaction.id,parsed)): db.add(TransactionTag(transaction_id=transaction.id,tag_id=parsed))
        elif field=='internal_transfer': transaction.is_internal_transfer=bool(value)
        elif field=='refund_credit': transaction.is_refund=bool(value)
        elif field=='loan_reimbursement':
            tag=ensure_loan_reimbursement_tag(transaction.household_id,db)
            if bool(value) and not db.get(TransactionTag,(transaction.id,tag.id)): db.add(TransactionTag(transaction_id=transaction.id,tag_id=tag.id))
        elif field=='expected': transaction.is_expected=bool(value)
        elif field=='prorated': transaction.is_prorated=bool(value)
        elif field=='proration_months': transaction.proration_months=int(value)
    suggestion.status='applied';transaction.classification_explanation=suggestion.explanation
    return transaction
def serialize_transaction_splits(transaction_id, h, db: Session):
    categories={item.id:item.name for item in db.scalars(select(Category).where(Category.household_id==h)).all()}
    users={item.id:item.display_name for item in db.scalars(select(User).join(HouseholdMember,HouseholdMember.user_id==User.id).where(HouseholdMember.household_id==h)).all()}
    splits=db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id==transaction_id).order_by(TransactionSplit.created_at,TransactionSplit.id)).all(); tag_rows={split.id:[] for split in splits}
    if splits:
        for split_id,tag_id,tag_name in db.execute(select(TransactionSplitTag.split_id,Tag.id,Tag.name).join(Tag,Tag.id==TransactionSplitTag.tag_id).where(TransactionSplitTag.split_id.in_([split.id for split in splits]))).all(): tag_rows[split_id].append({'id':str(tag_id),'name':tag_name})
    return [dict(serialize(split),category_name=categories.get(split.category_id),owner_name=users.get(split.owner_id,'Joint household'),tags=tag_rows[split.id],tag_ids=[tag['id'] for tag in tag_rows[split.id]]) for split in splits]
def transaction_allocation_rows(transactions, db: Session, view_user_id: UUID|None=None):
    """Return split allocations, or the parent transaction as its sole allocation.

    Parent flags deliberately stay on every allocation; category and owner are the
    only split-level fields in this first delivery.
    """
    transaction_ids=[item.id for item in transactions]
    grouped={item.id:[] for item in transactions}; split_tags={}
    if transaction_ids:
        for split in db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(transaction_ids)).order_by(TransactionSplit.created_at,TransactionSplit.id)).all(): grouped.setdefault(split.transaction_id,[]).append(split)
        for split_id,tag_id in db.execute(select(TransactionSplitTag.split_id,TransactionSplitTag.tag_id).where(TransactionSplitTag.split_id.in_(select(TransactionSplit.id).where(TransactionSplit.transaction_id.in_(transaction_ids))))).all(): split_tags.setdefault(split_id,set()).add(tag_id)
    rows=[]
    for item in transactions:
        splits=grouped.get(item.id,[])
        if splits:
            for split in splits:
                if view_user_id and split.owner_id!=view_user_id: continue
                rows.append({'transaction':item,'amount':float(split.amount),'category_id':split.category_id,'owner_id':split.owner_id,'is_refund':split.is_refund,'refund_included':split.refund_included,'tag_ids':split_tags.get(split.id,set()),'is_split':True,'split_id':split.id})
        else:
            rows.append({'transaction':item,'amount':float(item.amount),'category_id':item.category_id,'owner_id':None,'is_refund':item.is_refund,'refund_included':item.refund_included,'tag_ids':set(),'is_split':False,'split_id':None})
    return rows
def scope_aware_transaction_allocations(transactions, db: Session, view_user_id: UUID|None=None):
    """Expand raw allocations with explicit HouseholdSettlement view treatment.

    Imported transaction data remains immutable.  A payer debit is represented as
    a distinct settlement expense only in that payer's individual scope; a linked
    recipient credit is informational only; and both legs are excluded jointly.
    Normal residual amounts continue through the existing split allocation rules.
    """
    items=list(transactions)
    raw_rows=transaction_allocation_rows(items,db,None)
    transaction_ids={item.id for item in items}
    if not transaction_ids:
        return []
    settlements=db.scalars(select(HouseholdSettlement).where(HouseholdSettlement.household_id==items[0].household_id,HouseholdSettlement.status=='active',or_(HouseholdSettlement.payer_transaction_id.in_(transaction_ids),HouseholdSettlement.recipient_transaction_id.in_(transaction_ids))).order_by(HouseholdSettlement.created_at,HouseholdSettlement.id)).all()
    payer_by_allocation={}; recipient_by_transaction={}
    for settlement in settlements:
        payer_by_allocation.setdefault((settlement.payer_transaction_id,settlement.source_split_id),[]).append(settlement)
        if settlement.recipient_transaction_id:
            recipient_by_transaction.setdefault(settlement.recipient_transaction_id,[]).append([settlement,float(settlement.settlement_amount)])
    def belongs_to_view(row):
        return view_user_id is None or not row['is_split'] or row['owner_id']==view_user_id
    def output(row, amount, treatment='normal', settlement=None, include_in_totals=True, category_id=None):
        if abs(amount)<0.005: return None
        return {**row,'amount':round(amount,2),'category_id':category_id if category_id is not None else row['category_id'],'scope_treatment':treatment,'include_in_totals':include_in_totals,'settlement_id':str(settlement.id) if settlement else None,'settlement_amount':float(settlement.settlement_amount) if settlement else None,'settlement_payer_user_id':str(settlement.payer_user_id) if settlement else None,'settlement_recipient_user_id':str(settlement.recipient_user_id) if settlement else None,'settlement_note':settlement.note if settlement else None}
    rows=[]
    for row in raw_rows:
        item=row['transaction']; amount=float(row['amount']); visible=belongs_to_view(row)
        payer_settlements=payer_by_allocation.get((item.id,row['split_id']),[])
        if payer_settlements:
            remaining=amount
            for settlement in payer_settlements:
                portion=-min(abs(remaining),float(settlement.settlement_amount))
                remaining-=portion
                treatment='household_settlement_expense' if view_user_id==settlement.payer_user_id else 'household_settlement_excluded'
                derived=output(row,portion,treatment,settlement,view_user_id==settlement.payer_user_id,settlement.category_id or row['category_id'])
                if derived: rows.append(derived)
            normal=output(row,remaining)
            if normal and visible: rows.append(normal)
            continue
        recipient_settlements=recipient_by_transaction.get(item.id,[])
        if recipient_settlements and amount>0:
            remaining=amount
            for claim in recipient_settlements:
                settlement,unassigned=claim
                if unassigned<=0 or remaining<=0: continue
                portion=min(remaining,unassigned);claim[1]-=portion;remaining-=portion
                treatment='settlement_received' if view_user_id==settlement.recipient_user_id else 'household_settlement_excluded'
                derived=output(row,portion,treatment,settlement,False,settlement.category_id or row['category_id'])
                if derived: rows.append(derived)
            normal=output(row,remaining)
            if normal and visible: rows.append(normal)
            continue
        normal=output(row,amount)
        if normal and visible: rows.append(normal)
    return rows
def active_settlement_transaction_ids(transactions, db: Session):
    items=list(transactions); transaction_ids={item.id for item in items}
    if not transaction_ids: return set()
    return set(db.scalars(select(HouseholdSettlement.payer_transaction_id).where(HouseholdSettlement.household_id==items[0].household_id,HouseholdSettlement.status=='active',HouseholdSettlement.payer_transaction_id.in_(transaction_ids))).all())|set(db.scalars(select(HouseholdSettlement.recipient_transaction_id).where(HouseholdSettlement.household_id==items[0].household_id,HouseholdSettlement.status=='active',HouseholdSettlement.recipient_transaction_id.in_(transaction_ids))).all())
def serialize_connection(connection: DataConnection):
    """Connection credentials are write-only: never return ciphertext to any client."""
    row=serialize(connection); row.pop('encrypted_credentials',None); row['credentials_configured']=bool(connection.encrypted_credentials)
    if connection.provider=='plaid' and __import__('os').environ.get('PFOS_DESKTOP_RUNTIME')=='1':
        from .plaid_hosted import connection_state
        row.update(connection_state(connection))
    return row
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
def planner_schedule_owner(h, view_user_id, user, db):
    owner_id=view_user_id or user.id; validate_view_member(h,owner_id,db); return owner_id
def serialize_pay_schedule(schedule, configured: bool):
    if not schedule: return {'configured':False,'schedule_type':'semimonthly','biweekly_anchor_start_date':None,'paycheck_availability_policy':'next_period','is_active':True}
    return {**serialize(schedule),'configured':configured}
def validate_pay_schedule(body):
    if body.schedule_type not in {'semimonthly','biweekly'}: raise HTTPException(400,'Schedule type must be semimonthly or biweekly')
    if body.paycheck_availability_policy not in {'current_period','next_period'}: raise HTTPException(400,'Paycheck availability policy must be current_period or next_period')
    if body.schedule_type=='biweekly' and not body.biweekly_anchor_start_date: raise HTTPException(400,'Biweekly schedule requires an anchor start date')
@app.get('/api/v1/planner-pay-schedule')
def planner_pay_schedule(view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); owner_id=planner_schedule_owner(h,view_user_id,user,db); schedule=db.scalar(select(PlannerPaySchedule).where(PlannerPaySchedule.household_id==h,PlannerPaySchedule.owner_id==owner_id)); return serialize_pay_schedule(schedule,bool(schedule))
@app.put('/api/v1/planner-pay-schedule')
def update_planner_pay_schedule(body:PlannerPayScheduleIn,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); owner_id=planner_schedule_owner(h,view_user_id,user,db); validate_pay_schedule(body); schedule=db.scalar(select(PlannerPaySchedule).where(PlannerPaySchedule.household_id==h,PlannerPaySchedule.owner_id==owner_id))
    if not schedule: schedule=PlannerPaySchedule(household_id=h,owner_id=owner_id,**body.model_dump()); db.add(schedule)
    else:
        for field,value in body.model_dump().items(): setattr(schedule,field,value)
    db.commit(); return serialize_pay_schedule(schedule,True)
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
    ensure_loan_reimbursement_tag(h,db)
    visible_accounts=select(Account.id).where(Account.household_id==h)
    validate_view_member(h,view_user_id,db)
    if view_user_id: visible_accounts=visible_accounts.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    if page<1: raise HTTPException(400,'Page must be at least 1')
    if page_size<1 or page_size>100: raise HTTPException(400,'Page size must be between 1 and 100')
    valid_roles={'spending','income','debt','brokerage','crypto'}
    if not set(financial_roles).issubset(valid_roles): raise HTTPException(400,'Invalid financial role filter')
    if transaction_type not in {None,'credit','debit'}: raise HTTPException(400,'Transaction type must be credit or debit')
    if start_date and end_date and start_date>end_date: raise HTTPException(400,'Start date must be on or before end date')
    visibility=Transaction.account_id.in_(visible_accounts)
    if view_user_id: visibility=or_(visibility,Transaction.id.in_(select(TransactionSplit.transaction_id).where(TransactionSplit.ownership=='individual',TransactionSplit.owner_id==view_user_id)))
    filters=[Transaction.household_id==h,visibility]
    if search: filters.append(Transaction.description.ilike(f'%{search.strip()}%'))
    if account_id: filters.append(Transaction.account_id==account_id)
    selected_categories=category_ids+([category_id] if category_id else [])
    if selected_categories: filters.append(or_(Transaction.category_id.in_(selected_categories),Transaction.id.in_(select(TransactionSplit.transaction_id).where(TransactionSplit.category_id.in_(selected_categories)))))
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
        row=serialize(x);account=accounts_by_id.get(x.account_id);transaction_tags=tags_by_transaction[x.id];row.update(account_name=account.name if account else 'Unknown account',account_type=account.account_type if account else None,category_name=categories_by_id.get(x.category_id).name if x.category_id in categories_by_id else None,source_name=connections_by_id.get(x.connection_id).name if x.connection_id in connections_by_id else 'Manual',tags=transaction_tags,tag_ids=[tag['id'] for tag in transaction_tags],splits=serialize_transaction_splits(x.id,h,db),**smart_tagging_metadata(x,h,db));result.append(row)
    return {'items':result,'page':page,'page_size':page_size,'total':total,'total_pages':max(1,(total+page_size-1)//page_size),'sort':sort}

def category_tracker_filters(h, start_date, end_date, view_user_id, db):
    validate_view_member(h,view_user_id,db)
    if start_date>end_date: raise HTTPException(400,'Start date must be on or before end date')
    account_ids=select(Account.id).where(Account.household_id==h)
    if view_user_id:
        account_ids=account_ids.where(Account.ownership=='individual',Account.owner_id==view_user_id)
        visibility=or_(Transaction.account_id.in_(account_ids),Transaction.id.in_(select(TransactionSplit.transaction_id).where(TransactionSplit.ownership=='individual',TransactionSplit.owner_id==view_user_id)))
    else: visibility=Transaction.account_id.in_(account_ids)
    return [Transaction.household_id==h,visibility,Transaction.date>=start_date,Transaction.date<=end_date,Transaction.is_pending==False]

@app.get('/api/v1/category-tracker')
def category_tracker(start_date:date|None=None,end_date:date|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); today=date.today(); end=end_date or today; start=start_date or end.replace(day=1)
    ensure_groceries_category(h,db); categories=db.scalars(select(Category).where(Category.household_id==h).order_by(Category.name)).all()
    totals={str(category.id):{'id':str(category.id),'parent_id':str(category.parent_id) if category.parent_id else None,'name':category.name,'kind':category.kind,'transaction_count':0,'debits':0.0,'credits':0.0,'net_amount':0.0,'activity_total':0.0} for category in categories}
    totals['uncategorized']={'id':None,'name':'Uncategorized','kind':'uncategorized','transaction_count':0,'debits':0.0,'credits':0.0,'net_amount':0.0,'activity_total':0.0}
    transactions=db.scalars(select(Transaction).where(*category_tracker_filters(h,start,end,view_user_id,db))).all()
    for allocation in scope_aware_transaction_allocations(transactions,db,view_user_id):
        if not allocation['include_in_totals']: continue
        row=totals.get(str(allocation['category_id']),totals['uncategorized']); amount=allocation['amount']; row['transaction_count']+=1; row['credits']+=max(amount,0); row['debits']+=abs(min(amount,0)); row['net_amount']+=amount; row['activity_total']+=abs(amount)
    return {'start_date':str(start),'end_date':str(end),'categories':list(totals.values())}

@app.get('/api/v1/category-tracker/transactions')
def category_tracker_transactions(start_date:date,end_date:date,category_id:UUID|None=None,uncategorized:bool=False,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); filters=category_tracker_filters(h,start_date,end_date,view_user_id,db)
    if not uncategorized and not category_id: raise HTTPException(400,'A category is required')
    if category_id:
        if not db.scalar(select(Category.id).where(Category.id==category_id,Category.household_id==h)): raise HTTPException(404,'Category not found')
    items=db.scalars(select(Transaction).where(*filters).order_by(Transaction.date.desc(),Transaction.id).limit(1000)).all(); accounts={x.id:x for x in db.scalars(select(Account).where(Account.household_id==h)).all()}
    result=[]
    for allocation in scope_aware_transaction_allocations(items,db,view_user_id):
        if not allocation['include_in_totals']: continue
        if (uncategorized and allocation['category_id'] is not None) or (category_id and allocation['category_id']!=category_id): continue
        item=allocation['transaction']; result.append(dict(serialize(item),id=str(allocation['split_id'] or item.id),parent_transaction_id=str(item.id),amount=allocation['amount'],category_id=str(allocation['category_id']) if allocation['category_id'] else None,is_split=allocation['is_split'],scope_treatment=allocation['scope_treatment'],account_name=accounts.get(item.account_id).name if item.account_id in accounts else 'Unknown account'))
    return {'items':result}
@app.post('/api/v1/transactions')
def add_transaction(body:ManualTransactionIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); a=db.get(Account,body.account_id)
    if not a or a.household_id!=h: raise HTTPException(400,'Invalid account')
    if body.owner_id and not db.scalar(select(HouseholdMember.id).where(HouseholdMember.household_id==h,HouseholdMember.user_id==body.owner_id)): raise HTTPException(400,'Invalid transaction owner')
    if body.category_id and not db.scalar(select(Category.id).where(Category.household_id==h,Category.id==body.category_id)): raise HTTPException(400,'Invalid category')
    tag_ids=list(dict.fromkeys(body.tag_ids)); valid_tags=set(db.scalars(select(Tag.id).where(Tag.household_id==h,Tag.id.in_(tag_ids))).all()) if tag_ids else set()
    if len(valid_tags)!=len(tag_ids): raise HTTPException(400,'Invalid tag')
    if body.is_refund and body.amount<=0: raise HTTPException(400,'Only positive transactions can be refund credits')
    data=body.model_dump(exclude={'tag_ids'}); data['fingerprint']=hashlib.sha256(f'{body.account_id}|{body.date}|{body.amount}|{body.description.lower()}'.encode()).hexdigest()
    t=Transaction(household_id=h,**data); db.add(t); db.flush(); db.add_all([TransactionTag(transaction_id=t.id,tag_id=tag_id) for tag_id in tag_ids]);evaluate_new_transaction(t,db,source='manual',preserve_fields=body.model_fields_set); a.balance=float(a.balance)+body.amount; record_balance_snapshots(db,[a],source='manual'); db.commit(); return dict(serialize(t),tags=[{'id':str(row.tag_id),'name':db.get(Tag,row.tag_id).name} for row in db.scalars(select(TransactionTag).where(TransactionTag.transaction_id==t.id)).all()],tag_ids=[str(row.tag_id) for row in db.scalars(select(TransactionTag).where(TransactionTag.transaction_id==t.id)).all()],splits=[],**smart_tagging_metadata(t,h,db))
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
@app.get('/api/v1/transactions/{transaction_id}/splits')
def get_transaction_splits(transaction_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); transaction=db.get(Transaction,transaction_id)
    if not transaction or transaction.household_id!=h: raise HTTPException(404,'Transaction not found')
    return {'transaction_id':str(transaction.id),'amount':float(transaction.amount),'splits':serialize_transaction_splits(transaction.id,h,db)}
@app.put('/api/v1/transactions/{transaction_id}/splits')
def replace_transaction_splits(transaction_id:UUID,body:TransactionSplitsUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); transaction=db.get(Transaction,transaction_id)
    if not transaction or transaction.household_id!=h: raise HTTPException(404,'Transaction not found')
    total=round(sum(item.amount for item in body.splits),2); parent_amount=round(float(transaction.amount),2)
    if total!=parent_amount: raise HTTPException(400,f'Split amounts must total {parent_amount:.2f}')
    if any((item.amount>0)!=(parent_amount>0) or item.amount==0 for item in body.splits): raise HTTPException(400,'Every split must have the same debit or credit direction as the transaction')
    category_ids={item.category_id for item in body.splits if item.category_id}
    valid_categories=set(db.scalars(select(Category.id).where(Category.household_id==h,Category.id.in_(category_ids))).all()) if category_ids else set()
    if valid_categories!=category_ids: raise HTTPException(400,'Invalid split category')
    owner_ids={item.owner_id for item in body.splits if item.owner_id}
    valid_owners=set(db.scalars(select(HouseholdMember.user_id).where(HouseholdMember.household_id==h,HouseholdMember.user_id.in_(owner_ids))).all()) if owner_ids else set()
    if valid_owners!=owner_ids: raise HTTPException(400,'Invalid split owner')
    tag_ids={tag_id for item in body.splits for tag_id in item.tag_ids}
    valid_tags=set(db.scalars(select(Tag.id).where(Tag.household_id==h,Tag.id.in_(tag_ids))).all()) if tag_ids else set()
    if valid_tags!=tag_ids: raise HTTPException(400,'Invalid split tag')
    for item in body.splits:
        if item.ownership not in {'joint','individual'}: raise HTTPException(400,'Split ownership must be joint or individual')
        if item.ownership=='individual' and not item.owner_id: raise HTTPException(400,'Select an owner for an individual split')
        if item.ownership=='joint' and item.owner_id: raise HTTPException(400,'Joint splits cannot have an individual owner')
        if item.is_refund and item.amount<=0: raise HTTPException(400,'Only positive split allocations can be refund credits')
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id==transaction.id))
    created=[]
    for item in body.splits:
        split=TransactionSplit(transaction_id=transaction.id,amount=item.amount,category_id=item.category_id,ownership=item.ownership,owner_id=item.owner_id,is_refund=item.is_refund,refund_included=item.refund_included);db.add(split);created.append((split,item.tag_ids))
    db.flush()
    for split,split_tag_ids in created: db.add_all([TransactionSplitTag(split_id=split.id,tag_id=tag_id) for tag_id in dict.fromkeys(split_tag_ids)])
    db.commit()
    return {'transaction_id':str(transaction.id),'amount':parent_amount,'splits':serialize_transaction_splits(transaction.id,h,db)}
@app.delete('/api/v1/transactions/{transaction_id}/splits',status_code=204)
def clear_transaction_splits(transaction_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    transaction=db.get(Transaction,transaction_id)
    if not transaction or transaction.household_id!=household(user,db): raise HTTPException(404,'Transaction not found')
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id==transaction.id));db.commit()
@app.patch('/api/v1/transactions/{transaction_id}/category')
def update_transaction_category(transaction_id:UUID,body:TransactionCategoryUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=h: raise HTTPException(404,'Transaction not found')
    if body.category_id and not db.scalar(select(Category.id).where(Category.id==body.category_id,Category.household_id==h)): raise HTTPException(400,'Invalid category')
    t.category_id=body.category_id; db.commit(); return serialize(t)
@app.patch('/api/v1/transactions/{transaction_id}/date')
def update_transaction_date(transaction_id:UUID,body:TransactionDateUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=household(user,db): raise HTTPException(404,'Transaction not found')
    t.date=body.date;db.commit();return serialize(t)
@app.patch('/api/v1/transactions/{transaction_id}/planner-effective-date')
def update_transaction_planner_effective_date(transaction_id:UUID,body:PlannerExpenseEffectiveDateUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=household(user,db): raise HTTPException(404,'Transaction not found')
    if t.is_internal_transfer: raise HTTPException(400,'Internal transfers cannot have a planner date')
    t.planner_effective_date=body.planner_effective_date
    db.commit();return serialize(t)
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

def active_household_member_ids(h, db: Session):
    return set(db.scalars(select(HouseholdMember.user_id).join(User,User.id==HouseholdMember.user_id).where(HouseholdMember.household_id==h,User.is_active==True)).all())
def _settlement_links_from_values(values):
    return values.get('purchase_links') or []
def validate_household_settlement(h, values, db: Session, exclude_settlement_id: UUID|None=None):
    """Validate a settlement treatment without changing its imported sources."""
    payer_transaction=db.get(Transaction,values['payer_transaction_id'])
    if not payer_transaction or payer_transaction.household_id!=h or float(payer_transaction.amount)>=0:
        raise HTTPException(400,'Payer source must be a negative household transaction')
    if values['payer_user_id']==values['recipient_user_id']:
        raise HTTPException(400,'Payer and recipient must be different household members')
    members=active_household_member_ids(h,db)
    if values['payer_user_id'] not in members or values['recipient_user_id'] not in members:
        raise HTTPException(400,'Payer and recipient must be active household members')
    payer_account=db.get(Account,payer_transaction.account_id)
    if payer_account and payer_account.ownership=='individual' and payer_account.owner_id and payer_account.owner_id!=values['payer_user_id']:
        raise HTTPException(400,'Payer must match the owner of an individual source account')
    source_split=None
    if values.get('source_split_id'):
        source_split=db.get(TransactionSplit,values['source_split_id'])
        if not source_split or source_split.transaction_id!=payer_transaction.id or float(source_split.amount)>=0:
            raise HTTPException(400,'Source split must be a negative split on the payer transaction')
    elif db.scalar(select(TransactionSplit.id).where(TransactionSplit.transaction_id==payer_transaction.id)):
        raise HTTPException(400,'Select a source split when the payer transaction has splits')
    recipient_transaction=None
    if values.get('recipient_transaction_id'):
        recipient_transaction=db.get(Transaction,values['recipient_transaction_id'])
        if not recipient_transaction or recipient_transaction.household_id!=h or float(recipient_transaction.amount)<=0:
            raise HTTPException(400,'Recipient source must be a positive household transaction')
        recipient_account=db.get(Account,recipient_transaction.account_id)
        if recipient_account and recipient_account.ownership=='individual' and recipient_account.owner_id and recipient_account.owner_id!=values['recipient_user_id']:
            raise HTTPException(400,'Recipient must match the owner of an individual recipient account')
    if values.get('category_id') and not db.scalar(select(Category.id).where(Category.id==values['category_id'],Category.household_id==h)):
        raise HTTPException(400,'Invalid settlement category')
    amount=round(float(values['settlement_amount']),2)
    if amount<=0: raise HTTPException(400,'Settlement amount must be greater than zero')
    source_limit=abs(float(source_split.amount if source_split else payer_transaction.amount))
    existing_query=select(HouseholdSettlement).where(HouseholdSettlement.household_id==h,HouseholdSettlement.payer_transaction_id==payer_transaction.id,HouseholdSettlement.status=='active')
    existing_query=existing_query.where(HouseholdSettlement.source_split_id==source_split.id) if source_split else existing_query.where(HouseholdSettlement.source_split_id.is_(None))
    if exclude_settlement_id: existing_query=existing_query.where(HouseholdSettlement.id!=exclude_settlement_id)
    used=round(sum(float(item.settlement_amount) for item in db.scalars(existing_query).all()),2)
    if round(used+amount,2)>round(source_limit,2):
        raise HTTPException(400,'Active settlements cannot exceed the selected payer transaction amount')
    if recipient_transaction:
        recipient_query=select(HouseholdSettlement).where(HouseholdSettlement.household_id==h,HouseholdSettlement.recipient_transaction_id==recipient_transaction.id,HouseholdSettlement.status=='active')
        if exclude_settlement_id: recipient_query=recipient_query.where(HouseholdSettlement.id!=exclude_settlement_id)
        received=round(sum(float(item.settlement_amount) for item in db.scalars(recipient_query).all()),2)
        if round(received+amount,2)>round(float(recipient_transaction.amount),2):
            raise HTTPException(400,'Active settlements cannot exceed the selected recipient transaction amount')
    links=_settlement_links_from_values(values)
    if round(sum(float(item['allocated_amount'] if isinstance(item,dict) else item.allocated_amount) for item in links),2)>amount:
        raise HTTPException(400,'Linked purchase allocations cannot exceed the settlement amount')
    seen_links=set()
    for item in links:
        original_id=item['original_transaction_id'] if isinstance(item,dict) else item.original_transaction_id
        original_split_id=item.get('original_split_id') if isinstance(item,dict) else item.original_split_id
        allocated_amount=float(item['allocated_amount'] if isinstance(item,dict) else item.allocated_amount)
        key=(original_id,original_split_id)
        if key in seen_links: raise HTTPException(400,'Each original purchase can be linked only once per settlement')
        seen_links.add(key)
        original=db.get(Transaction,original_id)
        if not original or original.household_id!=h or float(original.amount)>=0:
            raise HTTPException(400,'Linked original purchases must be negative household transactions')
        if original_split_id:
            original_split=db.get(TransactionSplit,original_split_id)
            if not original_split or original_split.transaction_id!=original.id or float(original_split.amount)>=0:
                raise HTTPException(400,'Linked original split must be a negative split on its transaction')
            if allocated_amount>abs(float(original_split.amount)):
                raise HTTPException(400,'Linked allocation cannot exceed its original split amount')
        elif allocated_amount>abs(float(original.amount)):
            raise HTTPException(400,'Linked allocation cannot exceed its original transaction amount')
    return payer_transaction,recipient_transaction,source_split
def serialize_household_settlement(settlement, h, db: Session):
    users={item.id:item.display_name for item in db.scalars(select(User).join(HouseholdMember,HouseholdMember.user_id==User.id).where(HouseholdMember.household_id==h)).all()}
    category=db.get(Category,settlement.category_id) if settlement.category_id else None
    payer_transaction=db.get(Transaction,settlement.payer_transaction_id)
    recipient_transaction=db.get(Transaction,settlement.recipient_transaction_id) if settlement.recipient_transaction_id else None
    links=[]
    for link in db.scalars(select(HouseholdSettlementPurchaseLink).where(HouseholdSettlementPurchaseLink.settlement_id==settlement.id).order_by(HouseholdSettlementPurchaseLink.created_at,HouseholdSettlementPurchaseLink.id)).all():
        original=db.get(Transaction,link.original_transaction_id)
        links.append({**serialize(link),'original_transaction_description':original.description if original else 'Deleted transaction','original_transaction_date':str(original.date) if original else None})
    return {**serialize(settlement),'payer_name':users.get(settlement.payer_user_id,'Unknown user'),'recipient_name':users.get(settlement.recipient_user_id,'Unknown user'),'category_name':category.name if category else None,'payer_transaction_description':payer_transaction.description if payer_transaction else 'Deleted transaction','payer_transaction_date':str(payer_transaction.date) if payer_transaction else None,'recipient_transaction_description':recipient_transaction.description if recipient_transaction else None,'recipient_transaction_date':str(recipient_transaction.date) if recipient_transaction else None,'purchase_links':links}
def add_household_settlement_links(settlement_id, links, db: Session):
    for item in links:
        values=item if isinstance(item,dict) else item.model_dump()
        db.add(HouseholdSettlementPurchaseLink(settlement_id=settlement_id,**values))

@app.get('/api/v1/household-settlements')
def household_settlements(status:str|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db)
    if status not in {None,'active','reversed'}: raise HTTPException(400,'Status must be active or reversed')
    query=select(HouseholdSettlement).where(HouseholdSettlement.household_id==h)
    if status: query=query.where(HouseholdSettlement.status==status)
    items=db.scalars(query.order_by(HouseholdSettlement.created_at.desc(),HouseholdSettlement.id)).all()
    return {'items':[serialize_household_settlement(item,h,db) for item in items]}
@app.get('/api/v1/transactions/{transaction_id}/household-settlement')
def transaction_household_settlement(transaction_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); transaction=db.get(Transaction,transaction_id)
    if not transaction or transaction.household_id!=h: raise HTTPException(404,'Transaction not found')
    items=db.scalars(select(HouseholdSettlement).where(HouseholdSettlement.household_id==h,or_(HouseholdSettlement.payer_transaction_id==transaction_id,HouseholdSettlement.recipient_transaction_id==transaction_id)).order_by(HouseholdSettlement.created_at.desc(),HouseholdSettlement.id)).all()
    return {'items':[serialize_household_settlement(item,h,db) for item in items]}
@app.post('/api/v1/household-settlements',status_code=201)
def create_household_settlement(body:HouseholdSettlementIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); values=body.model_dump(); links=values.pop('purchase_links')
    validate_household_settlement(h,{**values,'purchase_links':links},db)
    settlement=HouseholdSettlement(household_id=h,status='active',**values);db.add(settlement);db.flush();add_household_settlement_links(settlement.id,links,db);db.commit()
    return serialize_household_settlement(settlement,h,db)
@app.patch('/api/v1/household-settlements/{settlement_id}')
def update_household_settlement(settlement_id:UUID,body:HouseholdSettlementUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); settlement=db.get(HouseholdSettlement,settlement_id)
    if not settlement or settlement.household_id!=h: raise HTTPException(404,'Household settlement not found')
    if settlement.status!='active': raise HTTPException(409,'Reversed settlements cannot be edited')
    changes=body.model_dump(exclude_unset=True); links=changes.pop('purchase_links',None)
    fields=('payer_transaction_id','recipient_transaction_id','source_split_id','payer_user_id','recipient_user_id','settlement_amount','category_id','note','settlement_group_id')
    values={field:getattr(settlement,field) for field in fields};values.update(changes)
    current_links=[{'original_transaction_id':item.original_transaction_id,'original_split_id':item.original_split_id,'allocated_amount':float(item.allocated_amount),'note':item.note} for item in db.scalars(select(HouseholdSettlementPurchaseLink).where(HouseholdSettlementPurchaseLink.settlement_id==settlement.id)).all()]
    validate_household_settlement(h,{**values,'purchase_links':current_links if links is None else links},db,settlement.id)
    for field,value in values.items(): setattr(settlement,field,value)
    if links is not None:
        db.execute(delete(HouseholdSettlementPurchaseLink).where(HouseholdSettlementPurchaseLink.settlement_id==settlement.id));add_household_settlement_links(settlement.id,links,db)
    db.commit();return serialize_household_settlement(settlement,h,db)
@app.post('/api/v1/household-settlements/{settlement_id}/reverse')
def reverse_household_settlement(settlement_id:UUID,body:HouseholdSettlementReverseIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); settlement=db.get(HouseholdSettlement,settlement_id)
    if not settlement or settlement.household_id!=h: raise HTTPException(404,'Household settlement not found')
    if settlement.status=='reversed': return serialize_household_settlement(settlement,h,db)
    settlement.status='reversed';settlement.reversal_note=body.reversal_note;settlement.reversed_at=datetime.utcnow();db.commit()
    return serialize_household_settlement(settlement,h,db)
@app.delete('/api/v1/household-settlements/{settlement_id}',status_code=204)
def delete_household_settlement(settlement_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); settlement=db.get(HouseholdSettlement,settlement_id)
    if not settlement or settlement.household_id!=h: raise HTTPException(404,'Household settlement not found')
    if settlement.status=='active': raise HTTPException(409,'Reverse an active settlement before deleting it')
    db.delete(settlement);db.commit()

def individual_biweekly_schedule(h, view_user_id, db):
    if not view_user_id: raise HTTPException(400,'Biweekly planning is available only in an individual user view')
    schedule=db.scalar(select(PlannerPaySchedule).where(PlannerPaySchedule.household_id==h,PlannerPaySchedule.owner_id==view_user_id,PlannerPaySchedule.is_active==True))
    if not schedule or schedule.schedule_type!='biweekly' or not schedule.biweekly_anchor_start_date: raise HTTPException(400,'Selected user does not have an active biweekly pay schedule')
    return schedule

# Joint biweekly display periods need a stable household-neutral frame. This is
# intentionally a display anchor only: each member's actual payroll continues
# to use that member's own configured availability policy and anchor.
JOINT_BIWEEKLY_DISPLAY_ANCHOR=date(2000,1,3)

def joint_display_cadence(period: str):
    return 'semimonthly' if period=='paycheck' else period

def account_pay_schedule(account, schedules_by_owner):
    if account.ownership=='individual' and account.owner_id:
        schedule=schedules_by_owner.get(account.owner_id)
        if schedule and schedule.schedule_type=='biweekly' and schedule.biweekly_anchor_start_date:
            return schedule
    return None

def income_source_scope(account, users_by_id, schedule=None):
    owner_id=account.owner_id if account.ownership=='individual' else None
    return {
        'source_owner_id':str(owner_id) if owner_id else None,
        'source_owner_name':users_by_id[owner_id].display_name if owner_id in users_by_id else 'Joint household',
        'source_schedule_cadence':'biweekly' if schedule else 'semimonthly',
    }

def planner_window(period, anchor, biweekly_anchor_start=None):
    if period=='monthly':
        start=anchor.replace(day=1);return start,(start.replace(day=28)+timedelta(days=4)).replace(day=1),'Monthly view',2
    if period=='paycheck':
        if anchor.day<=15: return anchor.replace(day=1),anchor.replace(day=16),'Paycheck view',1
        start=anchor.replace(day=16);return start,(start.replace(day=28)+timedelta(days=4)).replace(day=1),'Paycheck view',1
    if period=='biweekly':
        if not biweekly_anchor_start: raise HTTPException(400,'Biweekly planning requires an anchor start date')
        start,end=biweekly_period_bounds(biweekly_anchor_start,anchor);return start,end,'Biweekly view',1
    raise HTTPException(400,'Period must be paycheck, biweekly, or monthly')
def default_paycheck_availability_start(value: date):
    """Map each posted paycheck to the following bi-monthly spending period."""
    if value.day<=15:
        return value.replace(day=16)
    return (value.replace(day=28)+timedelta(days=4)).replace(day=1)
def paycheck_availability_start(source, period, biweekly_schedule=None):
    """Resolve planner-only paycheck availability without changing the transaction date."""
    value=source.planner_effective_date or source.date
    if biweekly_schedule:
        start,_=biweekly_period_bounds(biweekly_schedule.biweekly_anchor_start_date,value)
        return adjacent_period_start('biweekly',start,1,biweekly_schedule.biweekly_anchor_start_date) if biweekly_schedule.paycheck_availability_policy=='next_period' else start
    return source.planner_effective_date or default_paycheck_availability_start(source.date)

def add_months(value: date, months: int) -> date:
    """Return the inclusive-start date shifted by whole calendar months."""
    month_index=value.month-1+months; year=value.year+month_index//12; month=month_index%12+1
    return date(year,month,min(value.day,calendar.monthrange(year,month)[1]))
def planner_effective_date(item: Transaction) -> date:
    """Use the optional planner assignment without changing transaction history."""
    return item.planner_effective_date or item.date
def normalized_description(value: str|None): return ' '.join((value or '').lower().split())
def next_income_rule_occurrence(rule, after: date|None=None):
    """Return the next planner availability date without changing forecast math."""
    cursor=max(after or date.today(),rule.effective_start_date)
    if rule.effective_end_date and cursor>rule.effective_end_date: return None
    if rule.cadence=='twice_monthly':
        days=[1] if rule.availability_day==15 else [16] if rule.availability_day==16 else [1,16]
        next_month=(cursor.replace(day=28)+timedelta(days=4)).replace(day=1)
        candidates=sorted([cursor.replace(day=day) for day in days]+[next_month.replace(day=day) for day in days])
        result=next(candidate for candidate in candidates if candidate>=cursor)
    elif rule.cadence=='monthly':
        result=cursor.replace(day=1) if cursor.day==1 else (cursor.replace(day=28)+timedelta(days=4)).replace(day=1)
    else:
        result=rule.effective_start_date
        while result<cursor: result+=timedelta(days=14)
    return result if not rule.effective_end_date or result<=rule.effective_end_date else None
def serialize_income_rule(rule, db: Session):
    """Supply the manager with display metadata and a read-only reconciliation preview."""
    row=serialize(rule); account=db.get(Account,rule.account_id); owner=db.get(User,rule.owner_id) if rule.owner_id else None
    row.update(account_name=account.name if account else 'Unknown account',owner_name=owner.display_name if owner else 'Joint household',scope='individual' if owner else 'joint',next_occurrence=str(next_income_rule_occurrence(rule)) if rule.is_active and next_income_rule_occurrence(rule) else None,match_tolerance=max(20.0,float(rule.expected_amount)*.25))
    candidates=db.scalars(select(Transaction).where(Transaction.household_id==rule.household_id,Transaction.account_id==rule.account_id,Transaction.amount>0,Transaction.is_pending==False,Transaction.is_internal_transfer==False,Transaction.is_refund==False).order_by(Transaction.date.desc())).all()
    actual=next((item for item in candidates if not rule.source_description or normalized_description(item.description)==normalized_description(rule.source_description)),None)
    row['recent_reconciliation']=None if not actual else {'actual_transaction_id':str(actual.id),'actual_amount':float(actual.amount),'expected_amount':float(rule.expected_amount),'variance':float(actual.amount)-float(rule.expected_amount),'within_tolerance':abs(float(actual.amount)-float(rule.expected_amount))<=row['match_tolerance'],'available_period_start':str(actual.planner_effective_date or default_paycheck_availability_start(actual.date)),'posted_date':str(actual.date)}
    return row
def planner_expense_rule_matches(rule, item):
    """Prefer source identity; use account/category plus a bounded amount fallback."""
    if float(item.amount)>=0 or item.is_internal_transfer or item.account_id!=rule.account_id: return False
    if rule.category_id and item.category_id!=rule.category_id: return False
    if rule.source_description and normalized_description(item.description)==normalized_description(rule.source_description): return True
    expected=float(rule.monthly_projected_amount)*max(1,int(rule.proration_months or 1))
    return not rule.source_description and abs(abs(float(item.amount))-expected)<=max(20.0,expected*.25)
def serialize_planner_expense_rule(rule, db: Session):
    row=serialize(rule); account=db.get(Account,rule.account_id); category=db.get(Category,rule.category_id) if rule.category_id else None
    row.update(account_name=account.name if account else 'Unknown account',category_name=category.name if category else None)
    return row

@app.get('/api/v1/available-cash-planner')
def available_cash_planner(period:str='paycheck',anchor_date:date|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    """Server-side available-cash inputs; savings-rate what-if is intentionally client-only."""
    h=household(user,db); validate_view_member(h,view_user_id,db)
    joint_view=view_user_id is None
    scope_pay_schedule=db.scalar(select(PlannerPaySchedule).where(PlannerPaySchedule.household_id==h,PlannerPaySchedule.owner_id==view_user_id,PlannerPaySchedule.is_active==True)) if view_user_id else None
    # The legacy paycheck view remains semi-monthly. A configured biweekly
    # schedule applies only to the new biweekly view and to calendar-month
    # availability grouping for that individual.
    biweekly_schedule=individual_biweekly_schedule(h,view_user_id,db) if period=='biweekly' and not joint_view else (scope_pay_schedule if period=='monthly' and scope_pay_schedule and scope_pay_schedule.schedule_type=='biweekly' else None)
    display_biweekly_anchor=JOINT_BIWEEKLY_DISPLAY_ANCHOR if joint_view and period=='biweekly' else (biweekly_schedule.biweekly_anchor_start_date if biweekly_schedule else None)
    anchor=anchor_date or date.today(); start,end,label,multiplier=planner_window(period,anchor,display_biweekly_anchor)
    account_q=select(Account).where(Account.household_id==h,Account.is_active==True)
    if view_user_id: account_q=account_q.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    accounts=db.scalars(account_q).all(); account_ids=[account.id for account in accounts]; accounts_by_id={account.id:account for account in accounts}
    member_ids=set(db.scalars(select(HouseholdMember.user_id).where(HouseholdMember.household_id==h)).all())
    users_by_id={item.id:item for item in db.scalars(select(User).where(User.id.in_(member_ids))).all()} if member_ids else {}
    schedules_by_owner={item.owner_id:item for item in db.scalars(select(PlannerPaySchedule).where(PlannerPaySchedule.household_id==h,PlannerPaySchedule.is_active==True,PlannerPaySchedule.schedule_type=='biweekly')).all()}
    categories={category.id:category for category in db.scalars(select(Category).where(Category.household_id==h)).all()}; category_parent_ids={category.id:category.parent_id for category in categories.values()}
    transactions_in_period=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.is_pending==False,or_(and_(Transaction.date>=start,Transaction.date<end),and_(Transaction.planner_effective_date>=start,Transaction.planner_effective_date<end)))).all() if account_ids else []
    rules=db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.is_active==True)).all()
    expense_rules=db.scalars(select(RecurringPlannerExpenseRule).where(RecurringPlannerExpenseRule.household_id==h,RecurringPlannerExpenseRule.is_active==True,RecurringPlannerExpenseRule.account_id.in_(account_ids))).all() if account_ids else []
    designated_accounts={account.id for account in accounts if account.is_savings_direct_deposit}|{rule.account_id for rule in rules if rule.account_id}; designated_categories={rule.category_id for rule in rules if rule.category_id}; designated_tags={rule.tag_id for rule in rules if rule.tag_id}
    loan_reimbursement_tags=set(db.scalars(select(Tag.id).where(Tag.household_id==h,func.lower(Tag.name)=='loan reimbursement')).all())
    allocation_query=select(PlannerIncomeAllocation).where(PlannerIncomeAllocation.household_id==h)
    if joint_view: allocation_query=allocation_query.where(PlannerIncomeAllocation.effective_period_start>=start,PlannerIncomeAllocation.effective_period_start<end)
    else: allocation_query=allocation_query.where(planner_scope_filter(PlannerIncomeAllocation,view_user_id))
    if not joint_view and period=='paycheck': allocation_query=allocation_query.where(PlannerIncomeAllocation.period_type=='paycheck',PlannerIncomeAllocation.effective_period_start==start)
    elif not joint_view and period=='biweekly': allocation_query=allocation_query.where(PlannerIncomeAllocation.period_type=='biweekly',PlannerIncomeAllocation.effective_period_start==start)
    elif not joint_view: allocation_query=allocation_query.where(PlannerIncomeAllocation.effective_period_start>=start,PlannerIncomeAllocation.effective_period_start<end)
    manual_income_allocations=db.scalars(allocation_query).all(); manual_by_source={}
    for record in manual_income_allocations: manual_by_source[record.source_transaction_id]=manual_by_source.get(record.source_transaction_id,0)+float(record.amount)
    # Semi-monthly uses a half-month lookback; biweekly uses one complete prior
    # payroll period for sources configured to fund the following period.
    income_lookback=31 if joint_view else (14 if biweekly_schedule else 16)
    income_source_ids=set(manual_by_source); income_query=select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.amount>0,Transaction.is_pending==False,or_(and_(Transaction.date>=start-timedelta(days=income_lookback),Transaction.date<end),and_(Transaction.planner_effective_date>=start-timedelta(days=income_lookback),Transaction.planner_effective_date<end),Transaction.id.in_(income_source_ids))) if account_ids else select(Transaction).where(False)
    income_candidates=db.scalars(income_query).all()
    settlement_income_transaction_ids=active_settlement_transaction_ids(income_candidates,db)
    income_candidates=[item for item in income_candidates if item.id not in settlement_income_transaction_ids]
    manual_income_allocations=[record for record in manual_income_allocations if record.source_transaction_id not in settlement_income_transaction_ids]
    manual_by_source={}
    for record in manual_income_allocations: manual_by_source[record.source_transaction_id]=manual_by_source.get(record.source_transaction_id,0)+float(record.amount)
    income_by_id={item.id:item for item in income_candidates}
    period_allocations=scope_aware_transaction_allocations(transactions_in_period,db,view_user_id)
    relevant_tags=designated_tags|loan_reimbursement_tags
    tag_pairs=db.execute(select(TransactionTag.transaction_id,TransactionTag.tag_id).where(TransactionTag.transaction_id.in_([item.id for item in transactions_in_period]),TransactionTag.tag_id.in_(relevant_tags))).all() if transactions_in_period and relevant_tags else []
    tagged={transaction_id for transaction_id,tag_id in tag_pairs if tag_id in designated_tags}
    loan_reimbursements={transaction_id for transaction_id,tag_id in tag_pairs if tag_id in loan_reimbursement_tags}
    def is_debt_payment(item,account,category_id=None):
        category_id=item.category_id if category_id is None else category_id
        category_name=(categories.get(category_id).name if category_id in categories else '').lower()
        return item.is_internal_transfer or (account.account_type!='debt' and category_name in {'debt payments','transfers'})
    paycheck=automated=refunds_total=fixed_regular=expected=household_settlement_expenses=0.0; refunds=[]; paycheck_sources=[]; automated_savings_sources=[]; expense_input_sources=[]; debt_items=[]; household_settlement_sources=[]; settlement_received_sources=[]
    # Only refunds explicitly marked Prorated are spread across the calendar
    # month. Ordinary refund credits keep their actual posting-period behavior.
    month_start=anchor.replace(day=1); month_end=(month_start.replace(day=28)+timedelta(days=4)).replace(day=1)
    month_refunds=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.is_pending==False,Transaction.is_prorated==True,or_(and_(Transaction.date>=month_start,Transaction.date<month_end),and_(Transaction.planner_effective_date>=month_start,Transaction.planner_effective_date<month_end)))).all() if account_ids else []
    prorated_refund_ids=set()
    for allocation in scope_aware_transaction_allocations(month_refunds,db,view_user_id):
        if not allocation['include_in_totals']: continue
        item=allocation['transaction']; amount=allocation['amount']
        if not (month_start<=planner_effective_date(item)<month_end): continue
        if amount<=0 or not allocation['is_refund']:
            continue
        allocation_id=str(allocation['split_id'] or item.id); prorated_refund_ids.add(allocation_id); period_amount=amount*(12/26 if period=='biweekly' else (1/2 if period=='paycheck' else 1))
        account=accounts_by_id[item.account_id]; refunds.append({'id':allocation_id,'parent_transaction_id':str(item.id),'date':str(item.date),'description':item.description,'account_name':account.name,'amount':period_amount,'original_amount':amount,'refund_included':allocation['refund_included'],'is_split':allocation['is_split'],'is_prorated':True})
        if allocation['refund_included']: refunds_total+=period_amount
    for source in income_candidates:
        account=accounts_by_id[source.account_id]
        if account.account_type!='spending' or source.is_internal_transfer or source.is_refund: continue
        allocated=manual_by_source.get(source.id)
        source_schedule=account_pay_schedule(account,schedules_by_owner) if joint_view else biweekly_schedule
        availability_date=paycheck_availability_start(source,period,source_schedule)
        effective_start=start if allocated is not None else planner_period_start(period,availability_date,display_biweekly_anchor)
        amount=allocated if allocated is not None else float(source.amount)
        if (allocated is None and effective_start!=start) or amount<=0: continue
        paycheck+=amount; paycheck_sources.append({'id':str(source.id),'date':str(source.date),'available_period_start':str(effective_start),'description':source.description,'account_name':account.name,'amount':amount,'allocation_type':'manual' if allocated is not None else ('biweekly_schedule' if period=='biweekly' and not joint_view else ('late_payroll_default' if source.date!=start else 'posted_period')),'income_status':'manual' if allocated is not None else 'actual','note':next((record.note for record in manual_income_allocations if record.source_transaction_id==source.id),None),**income_source_scope(account,users_by_id,source_schedule),'joint_display_cadence':joint_display_cadence(period) if joint_view else None})
    anticipated_paychecks=[]; reconciled_paychecks=[]
    income_rule_query=select(RecurringPlannerIncomeRule).where(RecurringPlannerIncomeRule.household_id==h,or_(RecurringPlannerIncomeRule.is_active==True,RecurringPlannerIncomeRule.effective_end_date>=start),RecurringPlannerIncomeRule.effective_start_date<end,or_(RecurringPlannerIncomeRule.effective_end_date.is_(None),RecurringPlannerIncomeRule.effective_end_date>=start))
    if not joint_view: income_rule_query=income_rule_query.where(planner_scope_filter(RecurringPlannerIncomeRule,view_user_id))
    used_income_ids=set()
    for rule in db.scalars(income_rule_query).all():
        if rule.effective_start_date>=end: continue
        if joint_view and rule.owner_id is not None:
            # A Joint display period receives one forecast share per active rule.
            # The share is annualized by the member's true cadence, then divided
            # by the selected household display cadence. Posted/manual income is
            # never normalized or prorated.
            if rule.effective_start_date>start or (rule.effective_end_date and rule.effective_end_date<start): continue
            account=accounts_by_id.get(rule.account_id)
            if not account: continue
            source_schedule=account_pay_schedule(account,schedules_by_owner)
            owner_id=rule.owner_id or (account.owner_id if account.ownership=='individual' else None)
            source_scope=income_source_scope(account,users_by_id,source_schedule)
            if owner_id:
                source_scope.update(source_owner_id=str(owner_id),source_owner_name=users_by_id[owner_id].display_name if owner_id in users_by_id else 'Unknown user')
            rule_period_type='paycheck' if rule.cadence=='twice_monthly' else rule.cadence
            source_periods=12 if rule.cadence=='twice_monthly' and rule.availability_day in {15,16} else periods_per_year(rule_period_type)
            annualized_expected=float(rule.expected_amount)*source_periods
            normalized_expected=annualized_expected/periods_per_year(period)
            source_scope.update(source_schedule_cadence='semimonthly' if rule.cadence=='twice_monthly' else rule.cadence,rule_cadence=rule.cadence,joint_display_cadence=joint_display_cadence(period))
            def joint_rule_matches(source, amount):
                if source.account_id!=rule.account_id or source.is_internal_transfer or source.is_refund: return False
                if rule.source_description: return normalized_description(source.description)==normalized_description(rule.source_description)
                return abs(float(amount)-float(rule.expected_amount))<=max(20,float(rule.expected_amount)*.25)
            manual=next((record for record in manual_income_allocations if (source:=income_by_id.get(record.source_transaction_id)) and joint_rule_matches(source,record.amount)),None)
            if manual:
                source=income_by_id[manual.source_transaction_id]; variance=float(manual.amount)-normalized_expected
                reconciled_paychecks.append({'rule_id':str(rule.id),'actual_transaction_id':str(source.id),'expected_amount':normalized_expected,'source_expected_amount':float(rule.expected_amount),'annualized_expected_amount':annualized_expected,'actual_amount':float(manual.amount),'variance':variance,'status':'manual',**source_scope})
                for row in paycheck_sources:
                    if row['id']==str(source.id): row.update(allocation_type='manual',income_status='manual',expected_amount=normalized_expected,source_expected_amount=float(rule.expected_amount),annualized_expected_amount=annualized_expected,variance=variance,**source_scope)
                continue
            actual=next((item for item in income_candidates if item.id not in used_income_ids and joint_rule_matches(item,item.amount) and planner_period_start(period,paycheck_availability_start(item,period,account_pay_schedule(accounts_by_id[item.account_id],schedules_by_owner)),display_biweekly_anchor)==start),None)
            if actual:
                used_income_ids.add(actual.id); variance=float(actual.amount)-normalized_expected
                reconciled_paychecks.append({'rule_id':str(rule.id),'actual_transaction_id':str(actual.id),'expected_amount':normalized_expected,'source_expected_amount':float(rule.expected_amount),'annualized_expected_amount':annualized_expected,'actual_amount':float(actual.amount),'variance':variance,'status':'actual',**source_scope})
                for row in paycheck_sources:
                    if row['id']==str(actual.id): row.update(allocation_type='reconciled_actual',income_status='reconciled_actual',expected_amount=normalized_expected,source_expected_amount=float(rule.expected_amount),annualized_expected_amount=annualized_expected,variance=variance,**source_scope)
                continue
            row={'id':f'normalized-anticipated-{rule.id}-{start}','description':rule.display_name,'date':None,'available_period_start':str(start),'account_name':account.name,'amount':normalized_expected,'expected_amount':normalized_expected,'source_expected_amount':float(rule.expected_amount),'annualized_expected_amount':annualized_expected,'allocation_type':'normalized_anticipated','income_status':'normalized_anticipated','status':'normalized_anticipated',**source_scope}
            paycheck+=normalized_expected; paycheck_sources.append(row); anticipated_paychecks.append({'rule_id':str(rule.id),**row})
            continue
        rule_account=accounts_by_id.get(rule.account_id)
        rule_schedule=biweekly_schedule if rule.cadence=='biweekly' else None
        rule_scope=income_source_scope(rule_account,users_by_id,rule_schedule) if rule_account else {'source_owner_id':str(rule.owner_id) if rule.owner_id else None,'source_owner_name':users_by_id[rule.owner_id].display_name if rule.owner_id in users_by_id else 'Joint household','source_schedule_cadence':'biweekly' if rule.cadence=='biweekly' else 'semimonthly'}
        rule_scope.update(rule_cadence=rule.cadence,joint_display_cadence=None)
        if rule.cadence=='twice_monthly':
            days=[1] if rule.availability_day==15 else [16] if rule.availability_day==16 else [1,16]
            occurrences=[candidate for candidate in [start.replace(day=day) for day in days] if start<=candidate<end and candidate>=rule.effective_start_date]
        elif rule.cadence=='monthly': occurrences=[start] if start.day==1 and start>=rule.effective_start_date else []
        elif rule.cadence=='biweekly':
            if not biweekly_schedule: occurrences=[]
            elif period=='biweekly': occurrences=[start] if start>=rule.effective_start_date else []
            else:
                cursor=biweekly_period_bounds(biweekly_schedule.biweekly_anchor_start_date,start)[0]
                if cursor<start: cursor=adjacent_period_start('biweekly',cursor,1,biweekly_schedule.biweekly_anchor_start_date)
                occurrences=[]
                while cursor<end:
                    if cursor>=rule.effective_start_date: occurrences.append(cursor)
                    cursor=adjacent_period_start('biweekly',cursor,1,biweekly_schedule.biweekly_anchor_start_date)
        else:
            occurrences=[]; cursor=rule.effective_start_date
            while cursor<end:
                if cursor>=start: occurrences.append(cursor)
                cursor+=timedelta(days=14)
        for occurrence in occurrences:
            if rule.effective_end_date and occurrence>rule.effective_end_date: continue
            manual=next((record for record in manual_income_allocations if (source:=income_by_id.get(record.source_transaction_id)) and source.account_id==rule.account_id and not source.is_internal_transfer and not source.is_refund and ((rule.source_description and normalized_description(source.description)==normalized_description(rule.source_description)) or (not rule.source_description and abs(float(record.amount)-float(rule.expected_amount))<=max(20,float(rule.expected_amount)*.25)))),None)
            if manual:
                source=income_by_id[manual.source_transaction_id]; variance=float(manual.amount)-float(rule.expected_amount)
                reconciled_paychecks.append({'rule_id':str(rule.id),'actual_transaction_id':str(source.id),'expected_amount':float(rule.expected_amount),'actual_amount':float(manual.amount),'variance':variance,'status':'manual',**rule_scope})
                for row in paycheck_sources:
                    if row['id']==str(source.id): row.update(allocation_type='manual',expected_amount=float(rule.expected_amount),variance=variance)
                continue
            actual=next((item for item in income_candidates if item.id not in used_income_ids and item.account_id==rule.account_id and not item.is_internal_transfer and not item.is_refund and abs(float(item.amount)-float(rule.expected_amount))<=max(20,float(rule.expected_amount)*.25) and (not rule.source_description or normalized_description(item.description)==normalized_description(rule.source_description)) and (paycheck_availability_start(item,'biweekly',biweekly_schedule) if rule.cadence=='biweekly' and biweekly_schedule else planner_period_start('paycheck',item.planner_effective_date or default_paycheck_availability_start(item.date)))==occurrence),None)
            if actual:
                used_income_ids.add(actual.id)
                variance=float(actual.amount)-float(rule.expected_amount); reconciled_paychecks.append({'rule_id':str(rule.id),'actual_transaction_id':str(actual.id),'expected_amount':float(rule.expected_amount),'actual_amount':float(actual.amount),'variance':variance,'status':'actual',**rule_scope})
                for source in paycheck_sources:
                    if source['id']==str(actual.id): source.update(allocation_type='reconciled_actual',expected_amount=float(rule.expected_amount),variance=variance)
                continue
            amount=float(rule.expected_amount); row={'id':f'anticipated-{rule.id}-{occurrence}','description':rule.display_name,'date':None,'available_period_start':str(occurrence),'account_name':rule_account.name if rule_account else 'Anticipated','amount':amount,'allocation_type':'anticipated','income_status':'anticipated','status':'anticipated',**rule_scope};paycheck+=amount;paycheck_sources.append(row);anticipated_paychecks.append({'rule_id':str(rule.id),**row})
    for allocation in period_allocations:
        item=allocation['transaction']; account=accounts_by_id[item.account_id]; amount=allocation['amount']; category_id=allocation['category_id']
        effective_date=planner_effective_date(item)
        if item.planner_effective_date and not (start<=effective_date<end): continue
        if allocation['scope_treatment']=='settlement_received':
            settlement_received_sources.append({'id':f"settlement-received-{allocation['settlement_id']}",'settlement_id':allocation['settlement_id'],'date':str(item.date),'planner_effective_date':str(effective_date),'description':item.description,'account_name':account.name,'amount':amount,'category_id':str(category_id) if category_id else None,'status':'settlement_received','include_in_totals':False})
            continue
        if not allocation['include_in_totals']: continue
        if allocation['scope_treatment']=='household_settlement_expense':
            value=abs(amount); household_settlement_expenses+=value
            household_settlement_sources.append({'id':f"settlement-{allocation['settlement_id']}",'settlement_id':allocation['settlement_id'],'date':str(item.date),'planner_effective_date':str(effective_date),'description':item.description,'account_name':account.name,'amount':value,'period_amount':value,'category_id':str(category_id) if category_id else None,'category_name':categories[category_id].name if category_id in categories else None,'payer_user_id':allocation['settlement_payer_user_id'],'recipient_user_id':allocation['settlement_recipient_user_id'],'note':allocation['settlement_note'],'status':'household_settlement','scope_treatment':'household_settlement_expense'})
            continue
        # An explicit refund classification takes precedence over the transfer
        # heuristic. A reimbursement may be received in any account role.
        if amount>0 and allocation['is_refund']:
            allocation_id=str(allocation['split_id'] or item.id)
            if allocation_id not in prorated_refund_ids:
                refunds.append({'id':allocation_id,'parent_transaction_id':str(item.id),'date':str(item.date),'description':item.description,'account_name':account.name,'amount':amount,'refund_included':allocation['refund_included'],'is_split':allocation['is_split'],'is_prorated':False})
                if allocation['refund_included']: refunds_total+=amount
            continue
        if item.is_internal_transfer: continue
        # Loan reimbursements always override a savings designation. They may still
        # be represented elsewhere by their account's normal cash-flow treatment.
        automated_target=(item.account_id in designated_accounts or category_matches_rule(category_id,designated_categories,category_parent_ids) or item.id in tagged) and item.id not in loan_reimbursements and not (allocation['tag_ids']&loan_reimbursement_tags)
        if amount>0:
            if automated_target:
                automated+=amount
                automated_savings_sources.append({'id':str(item.id),'date':str(item.date),'description':item.description,'account_name':account.name,'amount':amount})
            elif account.account_type=='spending':
                # Paycheck availability is determined above from planner
                # allocations/default payroll timing, not the posting date.
                pass
            continue
        if amount>=0 or is_debt_payment(item,account,category_id) or item.is_prorated: continue
        if not (start<=effective_date<end): continue
        value=abs(amount)
        if item.is_expected:
            expected+=value
            expense_input_sources.append({'id':str(item.id),'type':'Expected','date':str(item.date),'planner_effective_date':str(effective_date),'description':item.description,'account_name':account.name,'amount':value,'period_amount':value})
        elif account.account_type=='debt':
            # Debt purchases are an as-of value: within the active paycheck or
            # month, include only activity dated on or before the selected date.
            if effective_date<=anchor:
                debt_items.append({'id':str(item.id),'date':str(item.date),'planner_effective_date':str(effective_date),'description':item.description,'account_name':account.name,'amount':value})
        elif account.account_type=='spending':
            fixed_regular+=value
            expense_input_sources.append({'id':str(item.id),'type':'Fixed','date':str(item.date),'planner_effective_date':str(effective_date),'description':item.description,'account_name':account.name,'amount':value,'period_amount':value})
    prorated_candidates=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.is_prorated==True,Transaction.is_pending==False,or_(Transaction.date<=anchor,Transaction.planner_effective_date<=anchor)).order_by(Transaction.date.desc())).all() if account_ids else []
    active_prorated=[]
    for allocation in scope_aware_transaction_allocations(prorated_candidates,db,view_user_id):
        if not allocation['include_in_totals'] or allocation['scope_treatment']!='normal': continue
        item=allocation['transaction']
        account=accounts_by_id[item.account_id]; duration=max(1,int(item.proration_months or 12))
        # A purchase contributes from its purchase date up to, but not including,
        # the matching duration anniversary (3, 6, 12 months, or another choice).
        effective_date=planner_effective_date(item)
        if float(allocation['amount'])<0 and not is_debt_payment(item,account,allocation['category_id']) and effective_date<=anchor and anchor<add_months(effective_date,duration): active_prorated.append(allocation)
    prorated_total=sum(abs(float(item['amount'])) for item in active_prorated); period_divisor=(26 if period=='biweekly' else (24 if period=='paycheck' else 12)); prorated_expenses=sum(abs(float(item['amount']))/(int(item['transaction'].proration_months or 12)*period_divisor/12) for item in active_prorated)
    for allocation in active_prorated:
        item=allocation['transaction']; account=accounts_by_id[item.account_id]; value=abs(float(allocation['amount'])); duration=int(item.proration_months or 12); effective_date=planner_effective_date(item); expense_input_sources.append({'id':str(allocation['split_id'] or item.id),'type':'Prorated','date':str(item.date),'planner_effective_date':str(effective_date),'description':item.description,'account_name':account.name,'amount':value,'proration_months':duration,'period_amount':value/(duration*period_divisor/12)})
    anticipated_expenses=0.0; anticipated_expense_sources=[]; reconciled_anticipated_expenses=[]
    # A rule is projected only when no source or matching actual charge is already
    # providing this period's allocation. This keeps imported actuals authoritative.
    actual_candidates=[allocation for allocation in period_allocations if allocation['include_in_totals'] and allocation['scope_treatment']=='normal' and start<=planner_effective_date(allocation['transaction'])<end and planner_effective_date(allocation['transaction'])<=anchor and float(allocation['amount'])<0 and not allocation['transaction'].is_internal_transfer]
    for rule in expense_rules:
        # A rule begins forecasting only once its activation date reaches the
        # selected period. This keeps a newly configured rule out of history.
        effective_start=rule.effective_start_date or rule.created_at.date()
        if end<=effective_start: continue
        actual=next((item for item in active_prorated if planner_expense_rule_matches(rule,item['transaction'])),None)
        actual=actual or next((item for item in actual_candidates if planner_expense_rule_matches(rule,item['transaction'])),None)
        if actual:
            actual_transaction=actual['transaction']; actual_monthly=abs(float(actual['amount']))/max(1,int(actual_transaction.proration_months or 1))
            reconciled_anticipated_expenses.append({'rule_id':str(rule.id),'display_name':rule.display_name,'actual_transaction_id':str(actual_transaction.id),'actual_amount':actual_monthly,'projected_amount':float(rule.monthly_projected_amount),'variance':actual_monthly-float(rule.monthly_projected_amount),'status':'actual'})
            continue
        period_amount=float(rule.monthly_projected_amount)*(12/26 if period=='biweekly' else (1/2 if period=='paycheck' else 1))
        anticipated_expenses+=period_amount
        anticipated_expense_sources.append({'id':str(rule.id),'rule_id':str(rule.id),'display_name':rule.display_name,'account_name':accounts_by_id[rule.account_id].name,'expected_day_of_month':rule.expected_day_of_month,'monthly_amount':float(rule.monthly_projected_amount),'period_amount':period_amount,'proration_months':rule.proration_months,'status':'anticipated'})
    # Refunds are expense credits, rather than income. This keeps NMP limited to
    # paycheck and automated-savings inflows while transparently reducing costs.
    raw_nmp=paycheck+automated; nmp_paycheck=raw_nmp/multiplier; net_monthly_pay=nmp_paycheck*2
    regular_expected_prorated=fixed_regular+expected+prorated_expenses; debt_total=sum(item['amount'] for item in debt_items)
    gross_total_expenses=regular_expected_prorated+debt_total+household_settlement_expenses; combined_expenses=gross_total_expenses+anticipated_expenses; total_expenses=combined_expenses-refunds_total
    return {'period':period,'period_label':label,'period_start':str(start),'period_end':str(end-timedelta(days=1)),'joint_display_cadence':joint_display_cadence(period) if joint_view else None,'joint_display_biweekly_anchor':str(display_biweekly_anchor) if joint_view and period=='biweekly' else None,'debt_line_item_through':str(anchor),'paycheck_amount':paycheck,'paycheck_sources':paycheck_sources,'anticipated_paychecks':anticipated_paychecks,'reconciled_paychecks':reconciled_paychecks,'automated_savings_amount':automated,'automated_savings_sources':automated_savings_sources,'included_refunds':refunds_total,'refund_expense_offset':refunds_total,'nmp_paycheck':nmp_paycheck,'net_monthly_pay':net_monthly_pay,'fixed_regular_expenses':fixed_regular,'expected_expenses':expected,'prorated_expense_total':prorated_total,'prorated_expenses':prorated_expenses,'regular_expected_prorated_expenses':regular_expected_prorated,'household_settlement_expenses':household_settlement_expenses,'household_settlement_sources':household_settlement_sources,'settlement_received_sources':settlement_received_sources,'expense_input_sources':expense_input_sources,'debt_line_items':debt_items,'debt_line_item_total':debt_total,'actual_expense_total':gross_total_expenses,'anticipated_expense_total':anticipated_expenses,'combined_period_expense_total':combined_expenses,'anticipated_expense_sources':anticipated_expense_sources,'reconciled_anticipated_expenses':reconciled_anticipated_expenses,'gross_total_period_expenses':gross_total_expenses,'total_period_expenses':total_expenses,'free_spending_before_savings':net_monthly_pay-total_expenses,'refunds':refunds}

def validate_planner_expense_rule(h, values, db: Session):
    account=db.get(Account,values['account_id'])
    if not account or account.household_id!=h: raise HTTPException(400,'Invalid rule account')
    category_id=values.get('category_id')
    if category_id and not db.scalar(select(Category.id).where(Category.id==category_id,Category.household_id==h)): raise HTTPException(400,'Invalid rule category')
    owner_id=values.get('owner_id')
    if owner_id and not db.scalar(select(HouseholdMember.id).where(HouseholdMember.household_id==h,HouseholdMember.user_id==owner_id)): raise HTTPException(400,'Invalid rule owner')
    values['owner_id']=owner_id if owner_id is not None else account.owner_id
    return values

@app.get('/api/v1/planner-expense-rules')
def planner_expense_rules(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db)
    return [serialize_planner_expense_rule(rule,db) for rule in db.scalars(select(RecurringPlannerExpenseRule).where(RecurringPlannerExpenseRule.household_id==h).order_by(RecurringPlannerExpenseRule.display_name)).all()]
@app.post('/api/v1/planner-expense-rules')
def add_planner_expense_rule(body:PlannerExpenseRuleIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); values=validate_planner_expense_rule(h,body.model_dump(),db); rule=RecurringPlannerExpenseRule(household_id=h,cadence='monthly',**values);db.add(rule);db.commit();return serialize_planner_expense_rule(rule,db)
@app.post('/api/v1/planner-expense-rules/from-transaction/{transaction_id}')
def create_planner_expense_rule_from_transaction(transaction_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); transaction=db.get(Transaction,transaction_id)
    if not transaction or transaction.household_id!=h: raise HTTPException(404,'Transaction not found')
    if float(transaction.amount)>=0 or not transaction.is_expected or not transaction.is_prorated: raise HTTPException(400,'Only negative Expected + Prorated transactions can create anticipated expense rules')
    account=db.get(Account,transaction.account_id); duration=max(1,int(transaction.proration_months or 1)); monthly_amount=abs(float(transaction.amount))/duration
    rule=db.scalar(select(RecurringPlannerExpenseRule).where(RecurringPlannerExpenseRule.household_id==h,RecurringPlannerExpenseRule.source_transaction_id==transaction.id))
    values={'account_id':transaction.account_id,'category_id':transaction.category_id,'owner_id':account.owner_id,'display_name':transaction.description[:120],'source_description':transaction.description,'monthly_projected_amount':monthly_amount,'expected_day_of_month':transaction.date.day,'effective_start_date':date.today(),'cadence':'monthly','is_active':True,'proration_months':duration}
    if rule:
        for field,value in values.items(): setattr(rule,field,value)
    else:
        rule=RecurringPlannerExpenseRule(household_id=h,source_transaction_id=transaction.id,**values);db.add(rule)
    db.commit();return serialize_planner_expense_rule(rule,db)
@app.patch('/api/v1/planner-expense-rules/{rule_id}')
def update_planner_expense_rule(rule_id:UUID,body:PlannerExpenseRuleUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); rule=db.get(RecurringPlannerExpenseRule,rule_id)
    if not rule or rule.household_id!=h: raise HTTPException(404,'Anticipated expense rule not found')
    changes=body.model_dump(exclude_unset=True); validation={**{'account_id':rule.account_id,'category_id':rule.category_id,'owner_id':rule.owner_id},**changes};validate_planner_expense_rule(h,validation,db)
    for field,value in changes.items(): setattr(rule,field,value)
    if 'owner_id' not in changes: rule.owner_id=validation['owner_id']
    db.commit();return serialize_planner_expense_rule(rule,db)
@app.delete('/api/v1/planner-expense-rules/{rule_id}',status_code=204)
def delete_planner_expense_rule(rule_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    rule=db.get(RecurringPlannerExpenseRule,rule_id)
    if not rule or rule.household_id!=household(user,db): raise HTTPException(404,'Anticipated expense rule not found')
    db.delete(rule);db.commit()

def planner_period_start(period_type: str, value: date, biweekly_anchor_start: date|None=None):
    if period_type=='monthly': return value.replace(day=1)
    if period_type=='paycheck': return value.replace(day=1 if value.day<=15 else 16)
    if period_type=='biweekly':
        if not biweekly_anchor_start: raise HTTPException(400,'Biweekly planning requires an anchor start date')
        return biweekly_period_bounds(biweekly_anchor_start,value)[0]
    raise HTTPException(400,'Period type must be paycheck, biweekly, or monthly')
def next_planner_period_start(period_type: str, value: date, biweekly_anchor_start: date|None=None):
    if period_type=='monthly': return (value.replace(day=28)+timedelta(days=4)).replace(day=1)
    if period_type=='paycheck': return value.replace(day=16) if value.day==1 else (value.replace(day=28)+timedelta(days=4)).replace(day=1)
    if period_type=='biweekly':
        if not biweekly_anchor_start: raise HTTPException(400,'Biweekly planning requires an anchor start date')
        return adjacent_period_start('biweekly',value,1,biweekly_anchor_start)
    raise HTTPException(400,'Period type must be paycheck, biweekly, or monthly')
def planner_period_anchor(h, view_user_id, period_type, db):
    if period_type!='biweekly': return None
    return JOINT_BIWEEKLY_DISPLAY_ANCHOR if view_user_id is None else individual_biweekly_schedule(h,view_user_id,db).biweekly_anchor_start_date
def planner_scope_filter(model, view_user_id): return model.owner_id==view_user_id if view_user_id else model.owner_id.is_(None)
def planner_cash_history(h, period_type, anchor, view_user_id, user, db: Session, limit=12, start_date: date|None=None):
    """Derive running planner cash from source transactions plus the small ledger."""
    validate_view_member(h,view_user_id,db); biweekly_anchor=planner_period_anchor(h,view_user_id,period_type,db); target=planner_period_start(period_type,anchor,biweekly_anchor)
    display_start=planner_period_start(period_type,start_date,biweekly_anchor) if start_date else None
    if display_start and display_start>target: raise HTTPException(400,'History start date cannot be after the selected planner period')
    account_query=select(Account.id).where(Account.household_id==h,Account.is_active==True)
    if view_user_id: account_query=account_query.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    account_ids=list(db.scalars(account_query).all())
    scope_openings=db.scalars(select(PlannerStartingCarryover).where(PlannerStartingCarryover.household_id==h,PlannerStartingCarryover.period_type==period_type,planner_scope_filter(PlannerStartingCarryover,view_user_id),PlannerStartingCarryover.effective_period_start<=target).order_by(PlannerStartingCarryover.effective_period_start)).all()
    scope_adjustments=db.scalars(select(PlannerAdjustment).where(PlannerAdjustment.household_id==h,PlannerAdjustment.period_type==period_type,planner_scope_filter(PlannerAdjustment,view_user_id),PlannerAdjustment.effective_period_start<=target).order_by(PlannerAdjustment.effective_period_start,PlannerAdjustment.created_at)).all()
    candidates=[target,*[item.effective_period_start for item in scope_openings],*[item.effective_period_start for item in scope_adjustments]]
    if account_ids:
        first_transaction=db.scalar(select(func.min(Transaction.date)).where(Transaction.household_id==h,Transaction.account_id.in_(account_ids),Transaction.is_pending==False))
        if first_transaction: candidates.append(planner_period_start(period_type,first_transaction,biweekly_anchor))
    cursor=min(candidates); openings={item.effective_period_start:item for item in scope_openings}; adjustments={}
    for item in scope_adjustments: adjustments.setdefault(item.effective_period_start,[]).append(item)
    # Goal sweeps are virtual planner allocations only. They never create a
    # contribution, change an account balance, or mutate a goal's saved amount.
    # The state below is rebuilt on every request so changed transactions and
    # priorities immediately produce a fresh, auditable forecast.
    ceiling=float(db.get(Household,h).checking_account_ceiling or 0)
    goal_state=[]
    if view_user_id is None and ceiling>0:
        for goal in db.scalars(select(Goal).where(Goal.household_id==h).order_by(Goal.priority_order,Goal.created_at)).all():
            remaining=max(0,float(goal.target_amount)-float(goal.current_amount))
            if remaining>0 and not goal.is_complete:
                account=db.get(Account,goal.funding_account_id) if goal.funding_account_id else None
                goal_state.append({'id':str(goal.id),'name':goal.name,'remaining':remaining,'funding_account_id':str(goal.funding_account_id) if goal.funding_account_id else None,'funding_account_name':account.name if account else None})
    # The live period is still in progress: show its Free Spending as a planning
    # figure, but do not treat the unspent remainder as carried cash yet.
    live_period_start=planner_period_start(period_type,date.today(),biweekly_anchor)
    running=0.0; history=[]
    while cursor<=target:
        opening=openings.get(cursor)
        if opening: running=float(opening.amount)
        next_cursor=next_planner_period_start(period_type,cursor,biweekly_anchor); evaluation_anchor=anchor if cursor==target else next_cursor-timedelta(days=1)
        planner=available_cash_planner(period_type,evaluation_anchor,view_user_id,user,db)
        free=float(planner['paycheck_amount'])-float(planner['total_period_expenses'])
        free_spending_included=cursor!=live_period_start
        included_free_spending=free if free_spending_included else 0.0
        period_adjustments=adjustments.get(cursor,[]); adjustment_total=sum(float(item.amount) for item in period_adjustments)
        previous=running; running=previous+included_free_spending+adjustment_total; ending_before_goal_sweeps=running; goal_sweeps=[]
        excess=max(0,running-ceiling) if goal_state else 0
        for goal in goal_state:
            if excess<=0: break
            allocation=min(excess,goal['remaining'])
            if allocation<=0: continue
            goal['remaining']-=allocation; excess-=allocation; running-=allocation
            goal_sweeps.append({**{key:value for key,value in goal.items() if key!='remaining'},'amount':allocation,'status':'forecast'})
        history.append({'period_start':str(cursor),'period_end':planner['period_end'],'period_label':planner['period_label'],'paycheck_amount':float(planner['paycheck_amount']),'actual_expenses':float(planner['actual_expense_total']),'anticipated_expenses':float(planner['anticipated_expense_total']),'refund_credits':float(planner['refund_expense_offset']),'total_period_expenses':float(planner['total_period_expenses']),'free_spending':free,'free_spending_included':free_spending_included,'included_free_spending':included_free_spending,'manual_adjustments':adjustment_total,'adjustments':[serialize(item) for item in period_adjustments],'opening_carryover':float(opening.amount) if opening else None,'previous_carryover':previous,'ending_before_goal_sweeps':ending_before_goal_sweeps,'goal_sweep_total':sum(item['amount'] for item in goal_sweeps),'goal_sweeps':goal_sweeps,'ending_rolling_available_cash':running})
        cursor=next_cursor
    visible_history=[item for item in history if date.fromisoformat(item['period_start'])>=display_start] if display_start else history[-limit:]
    if display_start and len(visible_history)>limit: raise HTTPException(400,f'History range exceeds the {limit}-period limit; choose a later start date')
    opening_before_range=visible_history[0]['previous_carryover'] if visible_history else 0.0
    return {'period_type':period_type,'anchor_date':str(anchor),'scope_user_id':str(view_user_id) if view_user_id else None,'display_start_date':str(display_start) if display_start else (visible_history[0]['period_start'] if visible_history else None),'opening_balance_before_display_range':opening_before_range,'history':visible_history,'current':history[-1] if history else None}

@app.get('/api/v1/available-cash-planner/history')
def available_cash_planner_history(period:str='paycheck',anchor_date:date|None=None,start_date:date|None=None,limit:int=12,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    if limit<1 or limit>60: raise HTTPException(400,'History limit must be between 1 and 60')
    h=household(user,db); return planner_cash_history(h,period,anchor_date or date.today(),view_user_id,user,db,limit,start_date)
@app.get('/api/v1/planner-carryovers')
def planner_carryovers(period_type:str|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); query=select(PlannerStartingCarryover).where(PlannerStartingCarryover.household_id==h,planner_scope_filter(PlannerStartingCarryover,view_user_id))
    if period_type: query=query.where(PlannerStartingCarryover.period_type==period_type)
    return [serialize(item) for item in db.scalars(query.order_by(PlannerStartingCarryover.effective_period_start.desc())).all()]
@app.put('/api/v1/planner-carryovers')
def set_planner_carryover(body:PlannerStartingCarryoverIn,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); start=planner_period_start(body.period_type,body.effective_period_start,planner_period_anchor(h,view_user_id,body.period_type,db))
    row=db.scalar(select(PlannerStartingCarryover).where(PlannerStartingCarryover.household_id==h,PlannerStartingCarryover.period_type==body.period_type,PlannerStartingCarryover.effective_period_start==start,planner_scope_filter(PlannerStartingCarryover,view_user_id)))
    if row: row.amount,row.note=body.amount,body.note
    else: row=PlannerStartingCarryover(household_id=h,owner_id=view_user_id,period_type=body.period_type,effective_period_start=start,amount=body.amount,note=body.note);db.add(row)
    db.commit();return serialize(row)
@app.delete('/api/v1/planner-carryovers/{carryover_id}',status_code=204)
def delete_planner_carryover(carryover_id:UUID,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); row=db.get(PlannerStartingCarryover,carryover_id)
    if not row or row.household_id!=h or row.owner_id!=view_user_id: raise HTTPException(404,'Starting carryover not found')
    db.delete(row);db.commit()
@app.get('/api/v1/planner-adjustments')
def planner_adjustments(period_type:str|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); query=select(PlannerAdjustment).where(PlannerAdjustment.household_id==h,planner_scope_filter(PlannerAdjustment,view_user_id))
    if period_type: query=query.where(PlannerAdjustment.period_type==period_type)
    return [serialize(item) for item in db.scalars(query.order_by(PlannerAdjustment.effective_period_start.desc(),PlannerAdjustment.created_at.desc())).all()]
@app.post('/api/v1/planner-adjustments')
def add_planner_adjustment(body:PlannerAdjustmentIn,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); start=planner_period_start(body.period_type,body.effective_period_start,planner_period_anchor(h,view_user_id,body.period_type,db)); row=PlannerAdjustment(household_id=h,owner_id=view_user_id,period_type=body.period_type,effective_period_start=start,amount=body.amount,note=body.note);db.add(row);db.commit();return serialize(row)
@app.patch('/api/v1/planner-adjustments/{adjustment_id}')
def update_planner_adjustment(adjustment_id:UUID,body:PlannerAdjustmentUpdate,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); row=db.get(PlannerAdjustment,adjustment_id)
    if not row or row.household_id!=h or (row.owner_id!=view_user_id): raise HTTPException(404,'Planner adjustment not found')
    changes=body.model_dump(exclude_unset=True)
    if 'effective_period_start' in changes: changes['effective_period_start']=planner_period_start(row.period_type,changes['effective_period_start'],planner_period_anchor(h,view_user_id,row.period_type,db))
    for field,value in changes.items(): setattr(row,field,value)
    db.commit();return serialize(row)
@app.delete('/api/v1/planner-adjustments/{adjustment_id}',status_code=204)
def delete_planner_adjustment(adjustment_id:UUID,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); row=db.get(PlannerAdjustment,adjustment_id)
    if not row or row.household_id!=h or row.owner_id!=view_user_id: raise HTTPException(404,'Planner adjustment not found')
    db.delete(row);db.commit()
def serialize_income_allocation(row, db: Session):
    data=serialize(row); transaction=db.get(Transaction,row.source_transaction_id); account=db.get(Account,transaction.account_id) if transaction else None
    data.update(source_description=transaction.description if transaction else 'Deleted transaction',source_transaction_date=str(transaction.date) if transaction else None,source_transaction_amount=float(transaction.amount) if transaction else None,account_name=account.name if account else None)
    return data
def validate_income_allocation(h, body, view_user_id, db: Session, exclude_id=None):
    if body.period_type not in {'paycheck','biweekly','monthly'}: raise HTTPException(400,'Period type must be paycheck, biweekly, or monthly')
    transaction=db.get(Transaction,body.source_transaction_id)
    if not transaction or transaction.household_id!=h or float(transaction.amount)<=0: raise HTTPException(400,'Select a positive household transaction')
    if transaction.id in active_settlement_transaction_ids([transaction],db): raise HTTPException(400,'Household settlement credits cannot be assigned as paychecks')
    account=db.get(Account,transaction.account_id)
    if not account or account.account_type!='spending' or transaction.is_internal_transfer or transaction.is_refund: raise HTTPException(400,'Only non-transfer spending-account credits can be assigned as paychecks')
    if view_user_id and account.ownership=='individual' and account.owner_id!=view_user_id: raise HTTPException(400,'Transaction is outside the selected user view')
    allocated=float(db.scalar(select(func.coalesce(func.sum(PlannerIncomeAllocation.amount),0)).where(PlannerIncomeAllocation.source_transaction_id==transaction.id,PlannerIncomeAllocation.id!=exclude_id)) or 0)
    if allocated+float(body.amount)>float(transaction.amount)+.005: raise HTTPException(400,'Paycheck allocations cannot exceed the source transaction amount')
    return transaction
@app.get('/api/v1/planner-income-allocations')
def planner_income_allocations(period_type:str|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); query=select(PlannerIncomeAllocation).where(PlannerIncomeAllocation.household_id==h,planner_scope_filter(PlannerIncomeAllocation,view_user_id))
    if period_type: query=query.where(PlannerIncomeAllocation.period_type==period_type)
    return [serialize_income_allocation(row,db) for row in db.scalars(query.order_by(PlannerIncomeAllocation.effective_period_start.desc(),PlannerIncomeAllocation.created_at.desc())).all()]
@app.get('/api/v1/planner-income-allocations/candidates')
def planner_income_candidates(anchor_date:date|None=None,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); anchor=anchor_date or date.today(); account_q=select(Account).where(Account.household_id==h,Account.account_type=='spending',Account.is_active==True)
    if view_user_id: account_q=account_q.where(Account.ownership=='individual',Account.owner_id==view_user_id)
    accounts={item.id:item for item in db.scalars(account_q).all()}; items=db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.account_id.in_(accounts),Transaction.amount>0,Transaction.is_internal_transfer==False,Transaction.is_refund==False,Transaction.is_pending==False,Transaction.date>=anchor-timedelta(days=90),Transaction.date<=anchor+timedelta(days=31)).order_by(Transaction.date.desc())).all() if accounts else []; items=[item for item in items if item.id not in active_settlement_transaction_ids(items,db)]
    return [{'id':str(item.id),'date':str(item.date),'description':item.description,'amount':float(item.amount),'account_name':accounts[item.account_id].name,'default_paycheck_period_start':str(default_paycheck_availability_start(item.date))} for item in items]
@app.post('/api/v1/planner-income-allocations')
def add_planner_income_allocation(body:PlannerIncomeAllocationIn,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); validate_income_allocation(h,body,view_user_id,db); start=planner_period_start(body.period_type,body.effective_period_start,planner_period_anchor(h,view_user_id,body.period_type,db)); row=PlannerIncomeAllocation(household_id=h,owner_id=view_user_id,source_transaction_id=body.source_transaction_id,period_type=body.period_type,effective_period_start=start,amount=body.amount,note=body.note);db.add(row);db.commit();return serialize_income_allocation(row,db)
@app.patch('/api/v1/planner-income-allocations/{allocation_id}')
def update_planner_income_allocation(allocation_id:UUID,body:PlannerIncomeAllocationUpdate,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); row=db.get(PlannerIncomeAllocation,allocation_id)
    if not row or row.household_id!=h or row.owner_id!=view_user_id: raise HTTPException(404,'Paycheck allocation not found')
    if body.amount is not None:
        candidate=PlannerIncomeAllocationIn(source_transaction_id=row.source_transaction_id,period_type=row.period_type,effective_period_start=row.effective_period_start,amount=body.amount,note=body.note if body.note is not None else row.note);validate_income_allocation(h,candidate,view_user_id,db,row.id);row.amount=body.amount
    if body.effective_period_start: row.effective_period_start=planner_period_start(row.period_type,body.effective_period_start,planner_period_anchor(h,view_user_id,row.period_type,db))
    if 'note' in body.model_fields_set: row.note=body.note
    db.commit();return serialize_income_allocation(row,db)
@app.delete('/api/v1/planner-income-allocations/{allocation_id}',status_code=204)
def delete_planner_income_allocation(allocation_id:UUID,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); row=db.get(PlannerIncomeAllocation,allocation_id)
    if not row or row.household_id!=h or row.owner_id!=view_user_id: raise HTTPException(404,'Paycheck allocation not found')
    db.delete(row);db.commit()
def validate_income_rule(h, values, view_user_id, db):
    if values.get('cadence') not in {'twice_monthly','biweekly','monthly'}: raise HTTPException(400,'Invalid paycheck cadence')
    account=db.get(Account,values['account_id'])
    if not account or account.household_id!=h or account.account_type!='spending': raise HTTPException(400,'Select a spending account')
    if view_user_id and (account.ownership!='individual' or account.owner_id!=view_user_id): raise HTTPException(400,'Account is outside selected user view')
    if values.get('cadence')=='biweekly': individual_biweekly_schedule(h,view_user_id,db)
    return account
def matching_income_rule(h, owner_id, account_id, source_description, db):
    """Find a recurring paycheck rule by its stable payroll identity, not an imported transaction id."""
    target=normalized_description(source_description)
    if not target: return None
    rows=db.scalars(select(RecurringPlannerIncomeRule).where(RecurringPlannerIncomeRule.household_id==h,RecurringPlannerIncomeRule.owner_id==owner_id,RecurringPlannerIncomeRule.account_id==account_id).order_by(RecurringPlannerIncomeRule.created_at.desc())).all()
    return next((row for row in rows if row.is_active and (not row.effective_end_date or row.effective_end_date>=date.today()) and normalized_description(row.source_description or row.display_name)==target),None)
@app.get('/api/v1/planner-income-rules')
def planner_income_rules(view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db);validate_view_member(h,view_user_id,db);query=select(RecurringPlannerIncomeRule).where(RecurringPlannerIncomeRule.household_id==h,planner_scope_filter(RecurringPlannerIncomeRule,view_user_id),or_(RecurringPlannerIncomeRule.is_active==False,and_(RecurringPlannerIncomeRule.is_active==True,or_(RecurringPlannerIncomeRule.effective_end_date.is_(None),RecurringPlannerIncomeRule.effective_end_date>=date.today())))).order_by(RecurringPlannerIncomeRule.created_at.desc());return [serialize_income_rule(x,db) for x in db.scalars(query).all()]
@app.post('/api/v1/planner-income-rules')
def add_planner_income_rule(body:PlannerIncomeRuleIn,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db);validate_view_member(h,view_user_id,db);values=body.model_dump();values.pop('owner_id',None);validate_income_rule(h,values,view_user_id,db)
    source_identity=values.get('source_description') or values['display_name']; row=matching_income_rule(h,view_user_id,values['account_id'],source_identity,db)
    if row:
        for key,value in values.items(): setattr(row,key,value)
    else:
        row=RecurringPlannerIncomeRule(household_id=h,owner_id=view_user_id,**values);db.add(row)
    db.commit();return serialize_income_rule(row,db)
@app.patch('/api/v1/planner-income-rules/{rule_id}')
def update_planner_income_rule(rule_id:UUID,body:PlannerIncomeRuleUpdate,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db);row=db.get(RecurringPlannerIncomeRule,rule_id)
    if not row or row.household_id!=h or row.owner_id!=view_user_id: raise HTTPException(404,'Paycheck rule not found')
    changes=body.model_dump(exclude_unset=True); effective_start=changes.pop('effective_start_date',date.today())
    if effective_start<date.today(): raise HTTPException(400,'Expected paycheck changes can begin today or in a future period')
    if changes.get('is_active') is False:
        row.is_active=False;row.effective_end_date=date.today()-timedelta(days=1);db.commit();return serialize_income_rule(row,db)
    values={'account_id':row.account_id,'cadence':row.cadence,**changes,'effective_start_date':effective_start};validate_income_rule(h,values,view_user_id,db)
    if row.effective_start_date>=effective_start:
        for key,value in changes.items(): setattr(row,key,value)
        row.effective_start_date=effective_start;row.effective_end_date=None;row.is_active=True;successor=row
    else:
        row.effective_end_date=effective_start-timedelta(days=1)
        copied={key:getattr(row,key) for key in ('account_id','display_name','expected_amount','cadence','availability_day','source_description','source_transaction_id')}
        copied.update(changes); copied.update(effective_start_date=effective_start,effective_end_date=None,is_active=True)
        successor=RecurringPlannerIncomeRule(household_id=h,owner_id=view_user_id,**copied);db.add(successor)
    db.commit();return serialize_income_rule(successor,db)
@app.delete('/api/v1/planner-income-rules/{rule_id}',status_code=204)
def delete_planner_income_rule(rule_id:UUID,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db);row=db.get(RecurringPlannerIncomeRule,rule_id)
    if not row or row.household_id!=h or row.owner_id!=view_user_id: raise HTTPException(404,'Paycheck rule not found')
    if row.effective_start_date>=date.today(): db.delete(row)
    else: row.effective_end_date=date.today()-timedelta(days=1)
    db.commit()
@app.post('/api/v1/planner-income-rules/from-transaction/{transaction_id}')
def income_rule_from_transaction(transaction_id:UUID,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db);validate_view_member(h,view_user_id,db);t=db.get(Transaction,transaction_id)
    if not t or t.household_id!=h or float(t.amount)<=0 or t.is_pending or t.is_internal_transfer or t.is_refund: raise HTTPException(400,'Transaction is not an eligible paycheck credit')
    if t.id in active_settlement_transaction_ids([t],db): raise HTTPException(400,'Transaction is not an eligible paycheck credit')
    account=db.get(Account,t.account_id);loan_tag=db.scalar(select(Tag.id).where(Tag.household_id==h,func.lower(Tag.name)=='loan reimbursement'))
    if not account or account.account_type!='spending' or (loan_tag and db.scalar(select(TransactionTag.transaction_id).where(TransactionTag.transaction_id==t.id,TransactionTag.tag_id==loan_tag))): raise HTTPException(400,'Transaction is not an eligible paycheck credit')
    rule_owner=view_user_id or (account.owner_id if account.ownership=='individual' else None); values={'account_id':t.account_id,'display_name':t.description[:120],'expected_amount':float(t.amount),'cadence':'twice_monthly','availability_day':1,'effective_start_date':date.today(),'source_description':t.description};validate_income_rule(h,values,rule_owner,db)
    row=matching_income_rule(h,rule_owner,t.account_id,t.description,db)
    if row:
        for key,value in values.items():setattr(row,key,value)
        row.source_transaction_id=t.id
    else: row=RecurringPlannerIncomeRule(household_id=h,owner_id=rule_owner,source_transaction_id=t.id,**values);db.add(row)
    db.commit();return serialize_income_rule(row,db)

@app.get('/api/v1/categories')
def categories(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); ensure_groceries_category(h,db); return [serialize(x) for x in db.scalars(select(Category).where(Category.household_id==h).order_by(Category.name)).all()]
@app.get('/api/v1/classification-rules')
def classification_rules(view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db)
    query=smart_tagging_scope(select(TransactionClassificationRule).where(TransactionClassificationRule.household_id==h),TransactionClassificationRule,view_user_id)
    return [serialize_classification_rule(rule,h,db) for rule in db.scalars(query.order_by(TransactionClassificationRule.priority,TransactionClassificationRule.created_at)).all()]
@app.get('/api/v1/transactions/{transaction_id}/classification-preview')
def classification_preview(transaction_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); transaction=db.get(Transaction,transaction_id)
    if not transaction or transaction.household_id!=h: raise HTTPException(404,'Transaction not found')
    rule,merchant,account=matching_rule(transaction,db)
    if not rule: return {'transaction_id':str(transaction.id),'normalized_merchant_key':merchant.normalized_merchant_key,'merchant_display_name':merchant.display_name,'match':None}
    return {'transaction_id':str(transaction.id),'normalized_merchant_key':merchant.normalized_merchant_key,'merchant_display_name':merchant.display_name,'match':{**serialize_classification_rule(rule,h,db),'would_create_pending_review':any(getattr(rule,field) is not None for field in ('internal_transfer','refund_credit','loan_reimbursement','expected','prorated','proration_months')) and not rule.planner_automation_approved,'account_type':account.account_type}}
@app.post('/api/v1/transactions/{transaction_id}/historical-classification-suggestion')
def generate_transaction_historical_suggestion(transaction_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); transaction=db.get(Transaction,transaction_id)
    if not transaction or transaction.household_id!=h: raise HTTPException(404,'Transaction not found')
    rule,_,_=matching_rule(transaction,db)
    if rule: return {'result':'explicit_rule_exists','rule':serialize_classification_rule(rule,h,db)}
    result=generate_historical_suggestion(transaction,db)
    if isinstance(result,dict): return result
    db.commit();return serialize_classification_suggestion(result,h,db)
@app.get('/api/v1/transactions/{transaction_id}/classification-suggestions')
def transaction_classification_suggestions(transaction_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); transaction=db.get(Transaction,transaction_id)
    if not transaction or transaction.household_id!=h: raise HTTPException(404,'Transaction not found')
    return [serialize_classification_suggestion(item,h,db) for item in db.scalars(select(TransactionClassificationSuggestion).where(TransactionClassificationSuggestion.transaction_id==transaction.id).order_by(TransactionClassificationSuggestion.created_at.desc())).all()]
@app.post('/api/v1/classification-rules')
def create_classification_rule(body:TransactionClassificationRuleIn,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); values=body.model_dump()
    if view_user_id and values['owner_id'] not in {None,view_user_id}: raise HTTPException(400,'Rule scope must be Joint or the selected user')
    if values.get('normalized_merchant_key'): values['normalized_merchant_key']=normalize_merchant_key(values['normalized_merchant_key'])
    validate_smart_tagging_references(h,values,db); tag_ids=values.pop('tag_ids')
    rule=TransactionClassificationRule(household_id=h,**values);db.add(rule);db.flush()
    for tag_id in tag_ids: db.add(TransactionClassificationRuleTag(rule_id=rule.id,tag_id=tag_id))
    db.commit();return serialize_classification_rule(rule,h,db)
@app.patch('/api/v1/classification-rules/{rule_id}')
def update_classification_rule(rule_id:UUID,body:TransactionClassificationRuleUpdate,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); rule=db.get(TransactionClassificationRule,rule_id)
    if not rule or rule.household_id!=h: raise HTTPException(404,'Classification rule not found')
    if view_user_id and rule.owner_id not in {None,view_user_id}: raise HTTPException(404,'Classification rule not found')
    changes=body.model_dump(exclude_unset=True); tag_ids=changes.pop('tag_ids',None)
    values={column.name:getattr(rule,column.name) for column in rule.__table__.columns}; values.update(changes)
    if values.get('normalized_merchant_key'): values['normalized_merchant_key']=normalize_merchant_key(values['normalized_merchant_key'])
    if view_user_id and values.get('owner_id') not in {None,view_user_id}: raise HTTPException(400,'Rule scope must be Joint or the selected user')
    validate_smart_tagging_references(h,values|{'tag_ids':tag_ids if tag_ids is not None else [row.tag_id for row in db.scalars(select(TransactionClassificationRuleTag).where(TransactionClassificationRuleTag.rule_id==rule.id)).all()]},db)
    for field,value in changes.items(): setattr(rule,field,value)
    if 'normalized_merchant_key' in changes: rule.normalized_merchant_key=values['normalized_merchant_key']
    if tag_ids is not None:
        db.execute(delete(TransactionClassificationRuleTag).where(TransactionClassificationRuleTag.rule_id==rule.id))
        for tag_id in tag_ids: db.add(TransactionClassificationRuleTag(rule_id=rule.id,tag_id=tag_id))
    db.commit();return serialize_classification_rule(rule,h,db)
@app.delete('/api/v1/classification-rules/{rule_id}',status_code=204)
def delete_classification_rule(rule_id:UUID,view_user_id:UUID|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db); rule=db.get(TransactionClassificationRule,rule_id)
    if not rule or rule.household_id!=h or (view_user_id and rule.owner_id not in {None,view_user_id}): raise HTTPException(404,'Classification rule not found')
    db.delete(rule);db.commit()
@app.get('/api/v1/classification-suggestions')
def classification_suggestions(view_user_id:UUID|None=None,status:str|None=None,account_id:UUID|None=None,start_date:date|None=None,end_date:date|None=None,max_confidence:float|None=None,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); validate_view_member(h,view_user_id,db)
    if status and status not in {'pending','accepted','rejected','applied'}: raise HTTPException(400,'Invalid suggestion status')
    query=select(TransactionClassificationSuggestion).join(Transaction,Transaction.id==TransactionClassificationSuggestion.transaction_id).join(Account,Account.id==Transaction.account_id).where(TransactionClassificationSuggestion.household_id==h)
    if view_user_id: query=query.where(or_(Account.owner_id==view_user_id,TransactionClassificationSuggestion.owner_id==view_user_id))
    else: query=query.where(Account.ownership=='joint')
    if status: query=query.where(TransactionClassificationSuggestion.status==status)
    if account_id: query=query.where(Transaction.account_id==account_id)
    if start_date: query=query.where(Transaction.date>=start_date)
    if end_date: query=query.where(Transaction.date<=end_date)
    if max_confidence is not None:
        if not 0<=max_confidence<=1: raise HTTPException(400,'Confidence must be between 0 and 1')
        query=query.where(TransactionClassificationSuggestion.confidence_score<=max_confidence)
    return [serialize_classification_suggestion(item,h,db) for item in db.scalars(query.order_by(TransactionClassificationSuggestion.created_at.desc())).all()]
@app.post('/api/v1/classification-suggestions/{suggestion_id}/accept')
def accept_classification_suggestion(suggestion_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); suggestion=db.get(TransactionClassificationSuggestion,suggestion_id)
    if not suggestion or suggestion.household_id!=h: raise HTTPException(404,'Classification suggestion not found')
    if suggestion.status=='applied': return serialize_classification_suggestion(suggestion,h,db)
    if suggestion.status!='pending': raise HTTPException(400,'Only pending suggestions can be accepted')
    if suggestion.source_type=='learned': apply_suggestion_fields(suggestion,None,db)
    elif not apply_suggestion(suggestion,db): raise HTTPException(400,'Suggestion no longer has an applicable rule')
    db.commit();return serialize_classification_suggestion(suggestion,h,db)
@app.post('/api/v1/classification-suggestions/{suggestion_id}/accept-fields')
def accept_classification_suggestion_fields(suggestion_id:UUID,body:ClassificationSuggestionFieldsIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); suggestion=db.get(TransactionClassificationSuggestion,suggestion_id)
    if not suggestion or suggestion.household_id!=h: raise HTTPException(404,'Classification suggestion not found')
    if suggestion.status=='applied': return serialize_classification_suggestion(suggestion,h,db)
    if suggestion.status!='pending': raise HTTPException(400,'Only pending suggestions can be accepted')
    apply_suggestion_fields(suggestion,body.fields,db);db.commit();return serialize_classification_suggestion(suggestion,h,db)
@app.post('/api/v1/classification-suggestions/{suggestion_id}/reject')
def reject_classification_suggestion(suggestion_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); suggestion=db.get(TransactionClassificationSuggestion,suggestion_id)
    if not suggestion or suggestion.household_id!=h: raise HTTPException(404,'Classification suggestion not found')
    if suggestion.status=='rejected': return serialize_classification_suggestion(suggestion,h,db)
    if suggestion.status!='pending': raise HTTPException(400,'Only pending suggestions can be rejected')
    suggestion.status='rejected';suggestion.safe_for_auto_apply=False;db.commit();return serialize_classification_suggestion(suggestion,h,db)
@app.post('/api/v1/classification-suggestions/{suggestion_id}/reject-fields')
def reject_classification_suggestion_fields(suggestion_id:UUID,body:ClassificationSuggestionFieldsIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); suggestion=db.get(TransactionClassificationSuggestion,suggestion_id)
    if not suggestion or suggestion.household_id!=h: raise HTTPException(404,'Classification suggestion not found')
    if suggestion.status=='rejected': return serialize_classification_suggestion(suggestion,h,db)
    if suggestion.status!='pending': raise HTTPException(400,'Only pending suggestions can be changed')
    proposed=suggestion_fields(suggestion,db);fields=set(body.fields or proposed.keys())
    if not fields or not fields.issubset(proposed): raise HTTPException(400,'Select only proposed suggestion fields')
    for field in fields: record_suggestion_decision(suggestion,field,'rejected',proposed[field],db)
    decisions=db.scalars(select(TransactionClassificationSuggestionDecision).where(TransactionClassificationSuggestionDecision.suggestion_id==suggestion.id)).all()
    if {item.field_name for item in decisions if item.decision=='rejected'}>=set(proposed): suggestion.status='rejected';suggestion.safe_for_auto_apply=False
    db.commit();return serialize_classification_suggestion(suggestion,h,db)
def suggestion_rule_preview(suggestion, h, db: Session, body: AlwaysApplyClassificationIn):
    transaction=db.get(Transaction,suggestion.transaction_id); account=db.get(Account,transaction.account_id); proposed=suggestion_fields(suggestion,db); fields=set(body.fields or proposed.keys())
    if not fields or not fields.issubset(proposed): raise HTTPException(400,'Select only proposed suggestion fields')
    values={'name':f"Always apply {normalize_merchant_key(transaction.description)}"[:120],'owner_id':account.owner_id if account.ownership=='individual' else None,'account_id':account.id,'normalized_merchant_key':normalize_merchant_key(transaction.description),'direction':'credit' if float(transaction.amount)>0 else 'debit','financial_role':account.account_type,'priority':body.priority,'is_active':True,'source_type':'user_authored','planner_automation_approved':False,'tag_ids':[]}
    for field in fields:
        value=proposed[field]['value'] if isinstance(proposed[field],dict) else proposed[field]
        if field in {'category_id','owner_id','essential'}: values['classified_owner_id' if field=='owner_id' else field]=UUID(str(value)) if field in {'category_id','owner_id'} else value
        elif field=='tag_ids': values['tag_ids']=[UUID(str(item)) for item in value]
    validate_smart_tagging_references(h,values,db);return values
@app.post('/api/v1/classification-suggestions/{suggestion_id}/always-apply-preview')
def classification_suggestion_always_apply_preview(suggestion_id:UUID,body:AlwaysApplyClassificationIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); suggestion=db.get(TransactionClassificationSuggestion,suggestion_id)
    if not suggestion or suggestion.household_id!=h: raise HTTPException(404,'Classification suggestion not found')
    return suggestion_rule_preview(suggestion,h,db,body)
@app.post('/api/v1/classification-suggestions/{suggestion_id}/always-apply')
def classification_suggestion_always_apply(suggestion_id:UUID,body:AlwaysApplyClassificationIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); suggestion=db.get(TransactionClassificationSuggestion,suggestion_id)
    if not suggestion or suggestion.household_id!=h: raise HTTPException(404,'Classification suggestion not found')
    if suggestion.source_type!='learned': raise HTTPException(400,'Always apply is available for learned suggestions only')
    if suggestion.status!='applied': raise HTTPException(400,'Accept the suggestion before creating an always-apply rule')
    values=suggestion_rule_preview(suggestion,h,db,body);tag_ids=values.pop('tag_ids');rule=TransactionClassificationRule(household_id=h,**values);db.add(rule);db.flush()
    for tag_id in tag_ids: db.add(TransactionClassificationRuleTag(rule_id=rule.id,tag_id=tag_id))
    db.commit();return serialize_classification_rule(rule,h,db)
@app.post('/api/v1/categories')
def add_category(body:CategoryIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); name=body.name.strip(); parent=db.get(Category,body.parent_id) if body.parent_id else None
    if body.kind not in {'income','expense','transfer','other'}: raise HTTPException(400,'Invalid category kind')
    if body.parent_id and (not parent or parent.household_id!=h): raise HTTPException(400,'Invalid parent category')
    duplicate_filters=[Category.household_id==h,func.lower(Category.name)==name.lower(),Category.parent_id==parent.id] if parent else [Category.household_id==h,func.lower(Category.name)==name.lower(),Category.parent_id.is_(None)]
    if db.scalar(select(Category.id).where(*duplicate_filters)): raise HTTPException(409,'A category with this name already exists at this level')
    # Children inherit parent metadata at creation and parent-level savings rules dynamically.
    c=Category(household_id=h,parent_id=parent.id if parent else None,name=name,kind=parent.kind if parent else body.kind,is_essential_default=parent.is_essential_default if parent else body.is_essential_default);db.add(c);db.commit();return serialize(c)
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
    parent_ids={item.id:item.parent_id for item in db.scalars(select(Category).where(Category.household_id==h)).all()}
    if replacement.id in category_descendants(category.id,parent_ids): raise HTTPException(400,'Select a replacement outside this category branch')
    # Keep all financial records intact: only their category pointer is reassigned.
    for transaction in db.scalars(select(Transaction).where(Transaction.household_id==h,Transaction.category_id==category.id)).all(): transaction.category_id=replacement.id
    for split in db.scalars(select(TransactionSplit).where(TransactionSplit.category_id==category.id)).all(): split.category_id=replacement.id
    for rule in db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.category_id==category.id)).all(): rule.category_id=replacement.id
    for child in db.scalars(select(Category).where(Category.household_id==h,Category.parent_id==category.id)).all(): child.parent_id=replacement.id
    db.delete(category);db.commit();return {'deleted_category_id':str(category_id),'replacement_category_id':str(replacement.id)}
@app.get('/api/v1/tags')
def tags(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); ensure_loan_reimbursement_tag(h,db); return [serialize(x) for x in db.scalars(select(Tag).where(Tag.household_id==h).order_by(Tag.name)).all()]
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
        current=float(g.current_amount);target=float(g.target_amount);months=_months_remaining(g.target_date);remaining=max(0,target-current);account=db.get(Account,g.funding_account_id) if g.funding_account_id else None;row=serialize(g);row.update(saved_amount=current,progress=round(current/target*100,1) if target else 0,remaining_amount=remaining,months_remaining=months,required_monthly_contribution=round(remaining/months,2) if months else None,funding_account_name=account.name if account else None);result.append(row)
    return result
@app.get('/api/v1/goals/sweep-forecast')
def goal_sweep_forecast(user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db); result=planner_cash_history(h,'paycheck',date.today(),None,user,db,60); current=result['current'] or {}; return {'checking_account_ceiling':float(db.get(Household,h).checking_account_ceiling or 0),'period_start':current.get('period_start'),'rolling_before_goal_sweeps':current.get('ending_before_goal_sweeps',0),'virtual_goal_sweep_total':current.get('goal_sweep_total',0),'rolling_after_goal_sweeps':current.get('ending_rolling_available_cash',0),'allocations':current.get('goal_sweeps',[]),'planner_only':True}
@app.post('/api/v1/goals')
def add_goal(body:GoalIn,user=Depends(current_user),db:Session=Depends(get_db)):
    h=household(user,db)
    if body.funding_account_id and not db.scalar(select(Account.id).where(Account.id==body.funding_account_id,Account.household_id==h)): raise HTTPException(400,'Invalid goal savings account')
    last_priority=db.scalar(select(func.max(Goal.priority_order)).where(Goal.household_id==h));priority=(int(last_priority) if last_priority is not None else -1)+1;g=Goal(household_id=h,priority_order=priority,**body.model_dump());db.add(g);db.commit();return serialize(g)
@app.patch('/api/v1/goals/{goal_id}')
def update_goal(goal_id:UUID,body:GoalUpdate,user=Depends(current_user),db:Session=Depends(get_db)):
    g=db.get(Goal,goal_id)
    if not g or g.household_id!=household(user,db): raise HTTPException(404,'Goal not found')
    if body.funding_account_id and not db.scalar(select(Account.id).where(Account.id==body.funding_account_id,Account.household_id==g.household_id)): raise HTTPException(400,'Invalid goal savings account')
    g.name,g.target_amount,g.current_amount,g.target_date,g.funding_account_id=body.name,body.target_amount,body.current_amount,body.target_date,body.funding_account_id
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
        transaction=Transaction(household_id=h,account_id=account_id,date=d,description=desc,amount=amount,fingerprint=fp)
        db.add(transaction);db.flush();evaluate_new_transaction(transaction,db,source='csv');added+=1
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
@app.get('/api/v1/connections/plaid/configuration')
def plaid_configuration_status(user=Depends(current_user)):
    try:
        config=plaid_configuration.credentials()
        return {'configured':True, 'environment':config['environment']}
    except ValueError:
        return {'configured':False, 'environment':None}
@app.post('/api/v1/connections/plaid/link-token')
def plaid_link_token(user=Depends(current_user),db:Session=Depends(get_db)):
    config=plaid_request_credentials()
    import httpx
    try: response=httpx.post(f'{plaid_configuration.host(config)}/link/token/create',json={'client_id':config['client_id'],'secret':config['secret'],'client_name':'PFOS','language':'en','country_codes':['US'],'products':['transactions'],'user':{'client_user_id':str(user.id)}},timeout=30).raise_for_status().json()
    except httpx.HTTPError as exc: raise HTTPException(502,'Plaid Link could not be initialized; verify your Plaid production configuration') from exc
    return {'link_token':response['link_token']}
@app.post('/api/v1/connections/plaid/exchange')
def plaid_exchange(body:PlaidExchangeIn,user=Depends(current_user),db:Session=Depends(get_db)):
    config=plaid_request_credentials()
    import httpx
    try: raw=httpx.post(f'{plaid_configuration.host(config)}/item/public_token/exchange',json={'client_id':config['client_id'],'secret':config['secret'],'public_token':body.public_token},timeout=30).raise_for_status().json()
    except httpx.HTTPError as exc: raise HTTPException(502,'Plaid account authorization could not be saved') from exc
    h=household(user,db)
    x=DataConnection(household_id=h,provider='plaid',name=next_connection_name(h,'plaid',body.name,db),encrypted_credentials=encrypt_credentials({'access_token':raw['access_token'],'plaid_identity':plaid_configuration.identity(config)}))
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
        payload=CONNECTORS[x.provider].fetch(decrypt_credentials(x.encrypted_credentials),x.cursor); added,dupes=persist_payload(db,x,payload);x.cursor=payload.cursor;x.last_synced_at=datetime.utcnow();run.status='complete';run.imported_count=added;run.duplicate_count=dupes;x.status='active';db.commit();return {'imported':added,'duplicates':dupes,'connection':serialize_connection(x)}
    except ConnectorAuthenticationError as exc:
        db.rollback()
        if isinstance(exc,PlaidReauthorizationRequired): x.status='reauthorization_required'
        elif isinstance(exc,PlaidNewConnectionRequired): x.status='new_connection_required'
        run=ConnectionSync(connection_id=x.id,status='failed',error_message=str(exc));db.add(run);db.commit();raise HTTPException(422,str(exc))
    except Exception as exc:
        db.rollback();run=ConnectionSync(connection_id=x.id,status='failed',error_message='Plaid sync failed; check local configuration and provider status' if x.provider=='plaid' else str(exc)[:500]);db.add(run);db.commit();raise HTTPException(502,'Sync failed; review the connection credentials and provider status')
@app.post('/api/v1/connections/csv/{account_id}')
async def import_csv_normalized(account_id:UUID,file:UploadFile=File(...),user=Depends(current_user),db:Session=Depends(get_db)):
    account=db.get(Account,account_id)
    if not account or account.household_id!=household(user,db): raise HTTPException(404,'Account not found')
    # CSV is normalized through the same pipeline; a temporary in-database connection preserves provenance.
    connection=db.scalar(select(DataConnection).where(DataConnection.household_id==account.household_id,DataConnection.provider=='csv',DataConnection.name==f'CSV: {account.name}'))
    if not connection: connection=DataConnection(household_id=account.household_id,provider='csv',name=f'CSV: {account.name}');db.add(connection);db.flush()
    account.connection_id=connection.id; account.external_id=str(account.id)
    db.flush()  # The import pipeline queries this link with autoflush disabled.
    try: payload=CsvConnector().parse(await file.read(),str(account.id)); added,dupes=persist_payload(db,connection,payload);db.commit();return {'imported':added,'duplicates':dupes}
    except ValueError as exc: raise HTTPException(400,str(exc))
@app.get('/api/v1/connections/{connection_id}/syncs')
def connection_syncs(connection_id:UUID,user=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(DataConnection,connection_id)
    if not x or x.household_id!=household(user,db): raise HTTPException(404,'Connection not found')
    return [serialize(run) for run in db.scalars(select(ConnectionSync).where(ConnectionSync.connection_id==x.id).order_by(ConnectionSync.created_at.desc())).all()]

def monthly_breakdown(accounts, transactions, rules, db, manual_income=0.0, view_user_id=None):
    """Apply the savings engine to one calendar month's transactions."""
    accounts_by_id={account.id:account for account in accounts}
    designated_accounts={account.id for account in accounts if account.is_savings_direct_deposit}|{rule.account_id for rule in rules if rule.account_id}
    designated_categories={rule.category_id for rule in rules if rule.category_id}
    category_parent_ids={category.id:category.parent_id for category in db.scalars(select(Category).where(Category.household_id==accounts[0].household_id)).all()} if accounts else {}
    designated_tags={rule.tag_id for rule in rules if rule.tag_id}
    loan_reimbursement_tags=set(db.scalars(select(Tag.id).where(Tag.household_id==accounts[0].household_id,func.lower(Tag.name)=='loan reimbursement')).all()) if accounts else set()
    relevant_tags=designated_tags|loan_reimbursement_tags
    tag_pairs=db.execute(select(TransactionTag.transaction_id,TransactionTag.tag_id).where(TransactionTag.transaction_id.in_([item.id for item in transactions]),TransactionTag.tag_id.in_(relevant_tags))).all() if transactions and relevant_tags else []
    tagged_transactions={transaction_id for transaction_id,tag_id in tag_pairs if tag_id in designated_tags}
    loan_reimbursements={transaction_id for transaction_id,tag_id in tag_pairs if tag_id in loan_reimbursement_tags}
    connection_names=dict(db.execute(select(DataConnection.id,DataConnection.name).where(DataConnection.id.in_([account.connection_id for account in accounts if account.connection_id]))).all())
    sources={}
    def source_row(account):
        if account.id not in sources:
            sources[account.id]={'account_id':str(account.id),'account_name':account.name,'source_name':connection_names.get(account.connection_id,'Manual'),'account_type':account.account_type,'income':0.0,'expenses':0.0,'automated_savings':0.0,'spending_cash_flow':0.0}
        return sources[account.id]
    automated=spending_net=expenses=essential=transaction_income=0.0
    for allocation in scope_aware_transaction_allocations(transactions,db,view_user_id):
        if not allocation['include_in_totals']: continue
        item=allocation['transaction']
        if item.is_internal_transfer: continue
        account=accounts_by_id[item.account_id]; amount=allocation['amount']; category_id=allocation['category_id']
        automated_target=(item.account_id in designated_accounts or category_matches_rule(category_id,designated_categories,category_parent_ids) or item.id in tagged_transactions) and item.id not in loan_reimbursements
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
    visibility=Transaction.account_id.in_(account_ids)
    if view_user_id: visibility=or_(visibility,Transaction.id.in_(select(TransactionSplit.transaction_id).where(TransactionSplit.ownership=='individual',TransactionSplit.owner_id==view_user_id)))
    tx=db.scalars(select(Transaction).where(Transaction.household_id==h,visibility,Transaction.date>=month_start,Transaction.date<month_end,Transaction.is_pending==False)).all() if account_ids or view_user_id else []
    calculation_account_ids=set(account_ids)|{item.account_id for item in tx}
    calculation_accounts=db.scalars(select(Account).where(Account.id.in_(calculation_account_ids))).all() if calculation_account_ids else []
    rules=db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.is_active==True)).all()
    monthly=monthly_breakdown(calculation_accounts,tx,rules,db,manual_income,view_user_id)
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
        point=monthly_breakdown(accounts,[item for item in transactions_in_range if month_start<=item.date<month_end],rules,db,manual_income,view_user_id)
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
    report_allocations=scope_aware_transaction_allocations(all_transactions,db,view_user_id)
    start=dates[0]; expense_allocations=[allocation for allocation in report_allocations if allocation['include_in_totals'] and start<=allocation['transaction'].date<=date.today() and float(allocation['amount'])<0 and not allocation['transaction'].is_internal_transfer and account_by_id[allocation['transaction'].account_id].account_type in {'spending','debt'}]
    categories={category.id:category.name for category in db.scalars(select(Category).where(Category.household_id==h)).all()}
    category_totals={}
    for allocation in expense_allocations:
        category_name=categories.get(allocation['category_id'],'Uncategorized'); category_totals[category_name]=category_totals.get(category_name,0)+abs(float(allocation['amount']))
    monthly_points=[]; month_cursor=start.replace(day=1); current_month=date.today().replace(day=1)
    while month_cursor<=current_month:
        month_end=(month_cursor.replace(day=28)+timedelta(days=4)).replace(day=1)
        month_items=[allocation for allocation in expense_allocations if month_cursor<=allocation['transaction'].date<month_end]
        recurring=sum(abs(float(item['amount'])) for item in month_items if item['transaction'].is_recurring or item['transaction'].is_expected or item['transaction'].is_prorated)
        discretionary=sum(abs(float(item['amount'])) for item in month_items if not (item['transaction'].is_recurring or item['transaction'].is_expected or item['transaction'].is_prorated))
        monthly_points.append({'month':str(month_cursor),'label':month_cursor.strftime('%b %Y'),'recurring':round(recurring,2),'discretionary':round(discretionary,2),'total':round(recurring+discretionary,2)})
        month_cursor=month_end
    latest_spend=monthly_points[-1]['total'] if monthly_points else 0; previous_spend=monthly_points[-2]['total'] if len(monthly_points)>1 else 0
    month_days=((current_month.replace(day=28)+timedelta(days=4)).replace(day=1)-current_month).days; elapsed=max(1,(date.today()-current_month).days+1)
    average_spend=sum(point['total'] for point in monthly_points)/len(monthly_points) if monthly_points else 0
    current_values={account.id:(float(account.crypto_usd_value or 0) if account.account_type=='crypto' else float(account.balance)) for account in accounts}
    investment_accounts=[account for account in accounts if account.account_type in {'brokerage','crypto'}]
    investment_value=sum(current_values[account.id] for account in investment_accounts)
    investment_contributions=sum(float(item['amount']) for item in report_allocations if item['include_in_totals'] and item['transaction'].account_id in {account.id for account in investment_accounts} and float(item['amount'])>0 and not item['transaction'].is_internal_transfer)
    allocation=[{'name':account.name,'type':account.account_type,'value':round(current_values[account.id],2)} for account in investment_accounts if current_values[account.id]!=0]
    latest_month_transactions=[item for item in all_transactions if current_month<=item.date<=date.today()]
    rules=db.scalars(select(SavingsRule).where(SavingsRule.household_id==h,SavingsRule.is_active==True)).all()
    current_cash=monthly_breakdown(accounts,latest_month_transactions,rules,db,view_user_id=view_user_id)
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

from .plaid_hosted import install_routes as install_plaid_hosted_routes
install_plaid_hosted_routes(app, current_user, household, next_connection_name)

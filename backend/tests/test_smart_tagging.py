from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import accept_classification_suggestion, accept_classification_suggestion_fields, classification_preview, classification_rules, classification_suggestion_always_apply, classification_suggestion_always_apply_preview, classification_suggestions, create_classification_rule, delete_classification_rule, generate_transaction_historical_suggestion, normalize_merchant_key, reject_classification_suggestion_fields, update_classification_rule
from app.models import Account, Category, Household, HouseholdMember, MerchantIdentity, Tag, Transaction, TransactionClassificationRule, TransactionClassificationSuggestion, TransactionClassificationSuggestionDecision, TransactionTag, User
from app.schemas import AlwaysApplyClassificationIn, ClassificationSuggestionFieldsIn, TransactionClassificationRuleIn, TransactionClassificationRuleUpdate
from app.smart_tagging import evaluate_new_transaction
from app.smart_tagging_learning import generate_historical_suggestion
from app.connectors import NormalizedAccount, NormalizedTransaction, SyncPayload, persist_payload


def smart_tagging_context():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);db=sessionmaker(bind=engine)()
    admin=User(email='smart-admin@example.com',display_name='Admin',password_hash='x')
    bailey=User(email='smart-bailey@example.com',display_name='Bailey',password_hash='x')
    other=User(email='smart-other@example.com',display_name='Other',password_hash='x')
    home=Household(name='Smart household');other_home=Household(name='Other household')
    db.add_all([admin,bailey,other,home,other_home]);db.flush()
    db.add_all([HouseholdMember(household_id=home.id,user_id=admin.id),HouseholdMember(household_id=home.id,user_id=bailey.id),HouseholdMember(household_id=other_home.id,user_id=other.id)])
    category=Category(household_id=home.id,name='Groceries',kind='expense');tag=Tag(household_id=home.id,name='Essential');other_category=Category(household_id=other_home.id,name='Other',kind='expense')
    account=Account(household_id=home.id,owner_id=bailey.id,ownership='individual',name='Bailey checking',type='checking',account_type='spending')
    db.add_all([category,tag,other_category,account]);db.commit()
    return db,admin,bailey,other,home,category,tag,other_category,account


def test_normalize_merchant_key_is_private_and_conservative():
    assert normalize_merchant_key('  INFOSYS   NOVA HOL PAYROLL REF # WFCT127YDFJG ')=='infosys nova hol payroll'
    assert normalize_merchant_key('ZELLE TO MCCONNELL JAMES ON 05/31 REF # WFCT127YDFJG')=='zelle to mcconnell james'
    assert normalize_merchant_key('Circle K #2744105')=='circle k #2744105'


def test_merchant_identity_is_unique_within_each_household():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    db.add(MerchantIdentity(household_id=home.id,normalized_merchant_key='king soopers',display_name='King Soopers'))
    db.commit()
    db.add(MerchantIdentity(household_id=home.id,normalized_merchant_key='king soopers',display_name='Duplicate'))
    with pytest.raises(IntegrityError): db.commit()
    db.rollback()


def test_classification_rule_validates_household_references_and_scope():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    body=TransactionClassificationRuleIn(owner_id=bailey.id,account_id=account.id,normalized_merchant_key='  KING   SOOPERS ',direction='debit',financial_role='spending',category_id=category.id,classified_owner_id=bailey.id,tag_ids=[tag.id],essential=True,expected=False,prorated=False)
    rule=create_classification_rule(body,bailey.id,admin,db)
    assert rule['normalized_merchant_key']=='king soopers'
    assert rule['tag_ids']==[str(tag.id)]
    assert classification_rules(bailey.id,admin,db)[0]['id']==rule['id']
    with pytest.raises(HTTPException):
        create_classification_rule(TransactionClassificationRuleIn(normalized_merchant_key='Wrong household',category_id=other_category.id),None,admin,db)
    with pytest.raises(HTTPException):
        create_classification_rule(TransactionClassificationRuleIn(normalized_merchant_key='Wrong scope',owner_id=other.id),bailey.id,admin,db)


def test_classification_rules_and_suggestions_remain_household_and_view_scoped():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    joint=create_classification_rule(TransactionClassificationRuleIn(normalized_merchant_key='Costco'),None,admin,db)
    individual=create_classification_rule(TransactionClassificationRuleIn(owner_id=bailey.id,normalized_merchant_key='Target'),bailey.id,admin,db)
    assert {row['id'] for row in classification_rules(bailey.id,admin,db)}=={joint['id'],individual['id']}
    assert {row['id'] for row in classification_rules(None,admin,db)}=={joint['id']}
    transaction=Transaction(household_id=home.id,account_id=account.id,date=__import__('datetime').date.today(),description='Target',amount=-10)
    db.add(transaction);db.flush();suggestion=TransactionClassificationSuggestion(household_id=home.id,transaction_id=transaction.id,category_id=category.id,owner_id=bailey.id,confidence_score=.9,explanation='Matched local rule',status='pending',safe_for_auto_apply=False);db.add(suggestion);db.commit()
    assert len(classification_suggestions(bailey.id,None,admin,db))==1
    assert classification_suggestions(None,None,admin,db)==[]
    updated=update_classification_rule(__import__('uuid').UUID(individual['id']),TransactionClassificationRuleUpdate(is_active=False),bailey.id,admin,db)
    assert updated['is_active'] is False
    delete_classification_rule(__import__('uuid').UUID(individual['id']),bailey.id,admin,db)
    assert {row['id'] for row in classification_rules(bailey.id,admin,db)}=={joint['id']}


def test_new_imported_transaction_applies_highest_priority_safe_rule_without_rewriting_history():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    generic=create_classification_rule(TransactionClassificationRuleIn(name='Generic store',normalized_merchant_key='target',category_id=category.id,priority=50),None,admin,db)
    specific=create_classification_rule(TransactionClassificationRuleIn(name='Bailey Target',owner_id=bailey.id,account_id=account.id,normalized_merchant_key='target',category_id=category.id,tag_ids=[tag.id],essential=True,priority=50),bailey.id,admin,db)
    old=Transaction(household_id=home.id,account_id=account.id,date=__import__('datetime').date.today(),description='Target',amount=-5)
    imported=Transaction(household_id=home.id,account_id=account.id,date=__import__('datetime').date.today(),description='Target REF # ABCDE12345',amount=-10)
    db.add_all([old,imported]);db.flush(); suggestion=evaluate_new_transaction(imported,db,source='plaid');db.commit()
    assert old.category_id is None
    assert imported.category_id==category.id and imported.is_essential is True
    assert imported.classification_rule_id==__import__('uuid').UUID(specific['id'])
    assert suggestion.status=='applied'
    assert set(db.scalars(__import__('sqlalchemy').select(TransactionTag.tag_id).where(TransactionTag.transaction_id==imported.id)).all())=={tag.id}
    preview=classification_preview(imported.id,admin,db)
    assert preview['match']['id']==specific['id']
    assert generic['id']!=specific['id']


def test_connector_persistence_runs_deterministic_classification_for_new_rows():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    create_classification_rule(TransactionClassificationRuleIn(name='Local coffee',normalized_merchant_key='local coffee',category_id=category.id,tag_ids=[tag.id],priority=1),None,admin,db)
    connection=__import__('app.models',fromlist=['DataConnection']).DataConnection(household_id=home.id,provider='plaid',name='Test connection')
    db.add(connection);db.commit()
    payload=SyncPayload([NormalizedAccount('acct-1','Checking','checking',Decimal('0'))],[NormalizedTransaction('txn-1','acct-1',date.today(),'LOCAL COFFEE REF # ABCDE12345',Decimal('-4.50'))])
    added,duplicates=persist_payload(db,connection,payload);db.commit()
    transaction=db.scalar(__import__('sqlalchemy').select(Transaction).where(Transaction.connection_id==connection.id))
    assert (added,duplicates)==(1,0)
    assert transaction.category_id==category.id and transaction.classification_rule_id is not None
    assert db.scalar(__import__('sqlalchemy').select(TransactionClassificationSuggestion.status).where(TransactionClassificationSuggestion.transaction_id==transaction.id))=='applied'


def test_planner_outputs_wait_for_review_unless_explicitly_approved():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    pending_rule=create_classification_rule(TransactionClassificationRuleIn(name='Transfer review',owner_id=bailey.id,normalized_merchant_key='venmo',internal_transfer=True,expected=True,priority=1),bailey.id,admin,db)
    pending=Transaction(household_id=home.id,account_id=account.id,date=__import__('datetime').date.today(),description='Venmo',amount=-20)
    db.add(pending);db.flush();suggestion=evaluate_new_transaction(pending,db,source='csv');db.commit()
    assert suggestion.status=='pending' and pending.is_internal_transfer is False and pending.is_expected is False
    accepted=accept_classification_suggestion(suggestion.id,admin,db)
    assert accepted['status']=='applied' and pending.is_internal_transfer is True and pending.is_expected is True
    approved_rule=create_classification_rule(TransactionClassificationRuleIn(name='Approved refund',owner_id=bailey.id,normalized_merchant_key='refund vendor',refund_credit=True,prorated=True,proration_months=1,planner_automation_approved=True,priority=1),bailey.id,admin,db)
    approved=Transaction(household_id=home.id,account_id=account.id,date=__import__('datetime').date.today(),description='Refund vendor',amount=10)
    db.add(approved);db.flush();applied=evaluate_new_transaction(approved,db,source='gemini');db.commit()
    assert applied.status=='applied' and approved.is_refund is True and approved.is_prorated is True and approved.proration_months==1
    assert pending_rule['id'] and approved_rule['id']


def test_historical_learning_builds_explainable_consensus_without_planner_flags():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    for index in range(18):
        db.add(Transaction(household_id=home.id,account_id=account.id,category_id=category.id if index<17 else None,date=date.today(),description='Whole Foods REF # ABCDE12345',amount=-20,is_essential=True,is_expected=index==0))
    current=Transaction(household_id=home.id,account_id=account.id,date=date.today(),description='Whole Foods',amount=-30)
    db.add(current);db.flush();suggestion=generate_transaction_historical_suggestion(current.id,admin,db);db.commit()
    assert suggestion['source_type']=='learned' and suggestion['status']=='pending' and suggestion['category_id']==str(category.id)
    assert suggestion['proposal_data']['fields']['category_id']['count']==17
    assert '17 of 18' in suggestion['explanation']
    assert suggestion['internal_transfer'] is None and suggestion['expected'] is None


def test_historical_learning_conflict_unknown_and_field_acceptance_are_safe():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    for index in range(3): db.add(Transaction(household_id=home.id,account_id=account.id,category_id=category.id if index<2 else None,date=date.today(),description='Conflict Store',amount=-10))
    conflict=Transaction(household_id=home.id,account_id=account.id,date=date.today(),description='Conflict Store',amount=-11)
    unknown=Transaction(household_id=home.id,account_id=account.id,date=date.today(),description='Unknown Merchant',amount=-12)
    db.add_all([conflict,unknown]);db.flush()
    conflict_result=generate_transaction_historical_suggestion(conflict.id,admin,db)
    unknown_result=generate_transaction_historical_suggestion(unknown.id,admin,db)
    assert conflict_result['status']=='pending' and conflict_result['safe_for_auto_apply'] is False
    assert unknown_result['result']=='insufficient_history'
    accepted=accept_classification_suggestion_fields(__import__('uuid').UUID(conflict_result['id']),ClassificationSuggestionFieldsIn(fields=['category_id']),admin,db)
    assert accepted['status']=='applied' and conflict.category_id==category.id
    assert accept_classification_suggestion_fields(__import__('uuid').UUID(conflict_result['id']),ClassificationSuggestionFieldsIn(fields=['category_id']),admin,db)['status']=='applied'
    preview=classification_suggestion_always_apply_preview(__import__('uuid').UUID(conflict_result['id']),AlwaysApplyClassificationIn(fields=['category_id']),admin,db)
    rule=classification_suggestion_always_apply(__import__('uuid').UUID(conflict_result['id']),AlwaysApplyClassificationIn(fields=['category_id']),admin,db)
    assert preview['normalized_merchant_key']=='conflict store' and rule['source_type']=='user_authored'


def test_historical_learning_never_uses_other_household_or_owner_history():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    other_home=db.scalar(__import__('sqlalchemy').select(Household).where(Household.name=='Other household'))
    other_account=Account(household_id=other_home.id,owner_id=other.id,ownership='individual',name='Other checking',type='checking',account_type='spending')
    james_account=Account(household_id=home.id,owner_id=admin.id,ownership='individual',name='James checking',type='checking',account_type='spending')
    db.add_all([other_account,james_account]);db.flush()
    for source_household,source_account,source_category in ((other_home,other_account,other_category),(home,james_account,category)):
        for _ in range(3): db.add(Transaction(household_id=source_household.id,account_id=source_account.id,category_id=source_category.id,date=date.today(),description='Private Market',amount=-9))
    current=Transaction(household_id=home.id,account_id=account.id,date=date.today(),description='Private Market',amount=-9)
    db.add(current);db.flush()
    result=generate_transaction_historical_suggestion(current.id,admin,db)
    assert result['result']=='insufficient_history' and result['evidence_count']==0


def test_rejecting_selected_suggestion_fields_is_audited_and_idempotent():
    db,admin,bailey,other,home,category,tag,other_category,account=smart_tagging_context()
    for _ in range(3): db.add(Transaction(household_id=home.id,account_id=account.id,category_id=category.id,date=date.today(),description='Local Market',amount=-10))
    current=Transaction(household_id=home.id,account_id=account.id,date=date.today(),description='Local Market',amount=-11)
    db.add(current);db.flush();suggestion=generate_historical_suggestion(current,db);db.commit()
    result=reject_classification_suggestion_fields(suggestion.id,ClassificationSuggestionFieldsIn(fields=['category_id']),admin,db)
    assert result['status']=='pending'
    assert reject_classification_suggestion_fields(suggestion.id,ClassificationSuggestionFieldsIn(fields=['category_id']),admin,db)['status']=='pending'
    assert db.scalar(__import__('sqlalchemy').select(TransactionClassificationSuggestionDecision.decision).where(TransactionClassificationSuggestionDecision.suggestion_id==suggestion.id,TransactionClassificationSuggestionDecision.field_name=='category_id'))=='rejected'

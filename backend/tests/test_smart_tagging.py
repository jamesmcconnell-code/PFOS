from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import classification_rules, classification_suggestions, create_classification_rule, delete_classification_rule, normalize_merchant_key, update_classification_rule
from app.models import Account, Category, Household, HouseholdMember, MerchantIdentity, Tag, Transaction, TransactionClassificationRule, TransactionClassificationSuggestion, User
from app.schemas import TransactionClassificationRuleIn, TransactionClassificationRuleUpdate


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

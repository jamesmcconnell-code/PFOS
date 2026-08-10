from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import available_cash_planner, category_tracker, create_household_settlement, delete_household_settlement, household_settlements, income_rule_from_transaction, metrics, planner_cash_history, planner_income_candidates, reports, reverse_household_settlement, scope_aware_transaction_allocations, transaction_household_settlement, update_household_settlement
from app.models import Account, Category, Household, HouseholdMember, HouseholdSettlement, HouseholdSettlementPurchaseLink, Transaction, TransactionSplit, User
from app.schemas import HouseholdSettlementIn, HouseholdSettlementPurchaseLinkIn, HouseholdSettlementReverseIn, HouseholdSettlementUpdate


def settlement_context():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);db=sessionmaker(bind=engine)()
    admin=User(email='settlement-admin@example.com',display_name='Admin',password_hash='x')
    bailey=User(email='settlement-bailey@example.com',display_name='Bailey',password_hash='x')
    james=User(email='settlement-james@example.com',display_name='James',password_hash='x')
    home=Household(name='Settlement household');db.add_all([admin,bailey,james,home]);db.flush()
    db.add_all([HouseholdMember(household_id=home.id,user_id=admin.id),HouseholdMember(household_id=home.id,user_id=bailey.id),HouseholdMember(household_id=home.id,user_id=james.id)])
    groceries=Category(household_id=home.id,name='Groceries',kind='expense')
    bailey_account=Account(household_id=home.id,name='Bailey checking',type='checking',account_type='spending',ownership='individual',owner_id=bailey.id)
    james_account=Account(household_id=home.id,name='James checking',type='checking',account_type='spending',ownership='individual',owner_id=james.id)
    db.add_all([groceries,bailey_account,james_account]);db.flush()
    payer=Transaction(household_id=home.id,account_id=bailey_account.id,date=date(2026,8,1),description='Venmo to James',amount=-80)
    recipient=Transaction(household_id=home.id,account_id=james_account.id,date=date(2026,8,1),description='Venmo from Bailey',amount=80)
    grocery_one=Transaction(household_id=home.id,account_id=james_account.id,category_id=groceries.id,date=date(2026,7,30),description='Groceries one',amount=-60)
    grocery_two=Transaction(household_id=home.id,account_id=james_account.id,category_id=groceries.id,date=date(2026,7,30),description='Groceries two',amount=-20)
    db.add_all([payer,recipient,grocery_one,grocery_two]);db.commit()
    return db,admin,bailey,james,home,groceries,payer,recipient,grocery_one,grocery_two


def settlement_body(bailey, james, groceries, payer, recipient, *links):
    return HouseholdSettlementIn(payer_transaction_id=payer.id,recipient_transaction_id=recipient.id,payer_user_id=bailey.id,recipient_user_id=james.id,settlement_amount=80,category_id=groceries.id,settlement_group_id=uuid4(),purchase_links=list(links))


def test_settlement_crud_supports_multiple_purchase_links_without_changing_transactions():
    db,admin,bailey,james,home,groceries,payer,recipient,grocery_one,grocery_two=settlement_context()
    body=settlement_body(bailey,james,groceries,payer,recipient,
        HouseholdSettlementPurchaseLinkIn(original_transaction_id=grocery_one.id,allocated_amount=60),
        HouseholdSettlementPurchaseLinkIn(original_transaction_id=grocery_two.id,allocated_amount=20),
    )
    created=create_household_settlement(body,admin,db)

    assert created['status']=='active'
    assert created['payer_name']=='Bailey'
    assert created['recipient_name']=='James'
    assert len(created['purchase_links'])==2
    assert float(db.get(Transaction,payer.id).amount)==-80
    assert float(db.get(Transaction,recipient.id).amount)==80
    assert len(household_settlements(None,admin,db)['items'])==1
    assert transaction_household_settlement(payer.id,admin,db)['items'][0]['id']==created['id']

    updated=update_household_settlement(UUID(created['id']),HouseholdSettlementUpdate(note='Groceries repayment'),admin,db)
    assert updated['note']=='Groceries repayment'


def test_settlement_rejects_cross_household_and_overlapping_amounts():
    db,admin,bailey,james,home,groceries,payer,recipient,grocery_one,grocery_two=settlement_context()
    created=create_household_settlement(settlement_body(bailey,james,groceries,payer,recipient),admin,db)
    with pytest.raises(HTTPException,match='cannot exceed'):
        create_household_settlement(HouseholdSettlementIn(payer_transaction_id=payer.id,payer_user_id=bailey.id,recipient_user_id=james.id,settlement_amount=1),admin,db)

    outsider=User(email='settlement-outsider@example.com',display_name='Outsider',password_hash='x');other=Household(name='Other');db.add_all([outsider,other]);db.flush();db.add(HouseholdMember(household_id=other.id,user_id=outsider.id));db.commit()
    with pytest.raises(HTTPException,match='active household members'):
        create_household_settlement(HouseholdSettlementIn(payer_transaction_id=payer.id,payer_user_id=bailey.id,recipient_user_id=outsider.id,settlement_amount=1),admin,db)
    assert db.get(HouseholdSettlement,UUID(created['id'])).status=='active'


def test_settlement_split_and_reversal_delete_safety():
    db,admin,bailey,james,home,groceries,payer,recipient,grocery_one,grocery_two=settlement_context()
    split=TransactionSplit(transaction_id=payer.id,owner_id=bailey.id,ownership='individual',amount=-50);other_split=TransactionSplit(transaction_id=payer.id,owner_id=bailey.id,ownership='individual',amount=-30)
    db.add_all([split,other_split]);db.commit()
    with pytest.raises(HTTPException,match='Select a source split'):
        create_household_settlement(HouseholdSettlementIn(payer_transaction_id=payer.id,payer_user_id=bailey.id,recipient_user_id=james.id,settlement_amount=50),admin,db)
    created=create_household_settlement(HouseholdSettlementIn(payer_transaction_id=payer.id,source_split_id=split.id,payer_user_id=bailey.id,recipient_user_id=james.id,settlement_amount=50),admin,db)
    settlement_id=UUID(created['id'])
    with pytest.raises(HTTPException,match='Reverse an active'):
        delete_household_settlement(settlement_id,admin,db)
    reversed_row=reverse_household_settlement(settlement_id,HouseholdSettlementReverseIn(reversal_note='Incorrect match'),admin,db)
    assert reversed_row['status']=='reversed'
    assert reversed_row['reversal_note']=='Incorrect match'
    delete_household_settlement(settlement_id,admin,db)
    assert db.get(HouseholdSettlement,settlement_id) is None
    assert db.query(HouseholdSettlementPurchaseLink).count()==0


def test_multiple_settlements_can_link_to_one_original_purchase():
    db,admin,bailey,james,home,groceries,payer,recipient,grocery_one,grocery_two=settlement_context()
    first=create_household_settlement(HouseholdSettlementIn(payer_transaction_id=payer.id,recipient_transaction_id=recipient.id,payer_user_id=bailey.id,recipient_user_id=james.id,settlement_amount=60,purchase_links=[HouseholdSettlementPurchaseLinkIn(original_transaction_id=grocery_one.id,allocated_amount=60)]),admin,db)
    second_payer=Transaction(household_id=home.id,account_id=db.get(Account,payer.account_id).id,date=date(2026,8,2),description='Second Venmo',amount=-20)
    second_recipient=Transaction(household_id=home.id,account_id=db.get(Account,recipient.account_id).id,date=date(2026,8,2),description='Second receipt',amount=20)
    db.add_all([second_payer,second_recipient]);db.commit()
    second=create_household_settlement(HouseholdSettlementIn(payer_transaction_id=second_payer.id,recipient_transaction_id=second_recipient.id,payer_user_id=bailey.id,recipient_user_id=james.id,settlement_amount=20,purchase_links=[HouseholdSettlementPurchaseLinkIn(original_transaction_id=grocery_one.id,allocated_amount=20)]),admin,db)
    assert first['purchase_links'][0]['original_transaction_id']==second['purchase_links'][0]['original_transaction_id']


def test_settlement_treatment_is_payer_expense_recipient_info_and_joint_exclusion():
    db,admin,bailey,james,home,groceries,payer,recipient,grocery_one,grocery_two=settlement_context()
    today=date.today()
    for transaction in (payer,recipient,grocery_one,grocery_two): transaction.date=today
    db.commit()
    create_household_settlement(settlement_body(bailey,james,groceries,payer,recipient,
        HouseholdSettlementPurchaseLinkIn(original_transaction_id=grocery_one.id,allocated_amount=60),
        HouseholdSettlementPurchaseLinkIn(original_transaction_id=grocery_two.id,allocated_amount=20),
    ),admin,db)

    bailey_planner=available_cash_planner('monthly',today,bailey.id,admin,db)
    james_planner=available_cash_planner('monthly',today,james.id,admin,db)
    joint_planner=available_cash_planner('monthly',today,None,admin,db)

    assert bailey_planner['household_settlement_expenses']==80
    assert bailey_planner['actual_expense_total']==80
    assert bailey_planner['fixed_regular_expenses']==0
    assert bailey_planner['total_period_expenses']==80
    assert bailey_planner['free_spending_before_savings']==-80
    assert bailey_planner['household_settlement_sources'][0]['scope_treatment']=='household_settlement_expense'
    assert james_planner['settlement_received_sources'][0]['amount']==80
    assert james_planner['actual_expense_total']==80
    assert joint_planner['household_settlement_expenses']==0
    assert joint_planner['actual_expense_total']==80
    assert joint_planner['total_period_expenses']==80

    bailey_metrics=metrics(home.id,db,bailey.id)
    james_metrics=metrics(home.id,db,james.id)
    joint_metrics=metrics(home.id,db)
    assert bailey_metrics['monthly_expenses']==80
    assert james_metrics['monthly_income']==0
    assert joint_metrics['monthly_expenses']==80
    assert joint_metrics['monthly_savings']==-80
    assert planner_income_candidates(today,james.id,admin,db)==[]
    with pytest.raises(HTTPException,match='eligible paycheck'):
        income_rule_from_transaction(recipient.id,james.id,admin,db)

    joint_categories=category_tracker(today,today,None,admin,db)
    assert next(item for item in joint_categories['categories'] if item['id']==str(groceries.id))['debits']==80
    report=reports('1M',None,admin,db)
    assert report['cash_flow']['expenses']==80
    assert report['cash_flow']['categories'][0]['value']==80


def test_partial_and_split_settlements_preserve_normal_residual_allocations_and_rolling_cash():
    db,admin,bailey,james,home,groceries,payer,recipient,grocery_one,grocery_two=settlement_context()
    prior_month=(date.today().replace(day=1)-timedelta(days=1)).replace(day=1)
    payer.date=prior_month;recipient.date=prior_month;grocery_one.date=prior_month;grocery_two.date=prior_month
    payer.amount=-100;recipient.amount=80;grocery_one.amount=-80;db.commit()
    create_household_settlement(HouseholdSettlementIn(payer_transaction_id=payer.id,recipient_transaction_id=recipient.id,payer_user_id=bailey.id,recipient_user_id=james.id,settlement_amount=80,category_id=groceries.id),admin,db)

    allocations=scope_aware_transaction_allocations([payer],db,bailey.id)
    assert sorted((item['scope_treatment'],item['amount']) for item in allocations)==[('household_settlement_expense',-80.0),('normal',-20.0)]
    bailey_planner=available_cash_planner('monthly',prior_month,bailey.id,admin,db)
    assert bailey_planner['household_settlement_expenses']==80
    assert bailey_planner['fixed_regular_expenses']==20
    assert bailey_planner['total_period_expenses']==100
    history=planner_cash_history(home.id,'monthly',prior_month,bailey.id,admin,db)
    assert history['current']['free_spending']==-100
    assert history['current']['ending_rolling_available_cash']==-100

    split_payer=Transaction(household_id=home.id,account_id=payer.account_id,date=prior_month,description='Split Venmo',amount=-100)
    db.add(split_payer);db.flush()
    settlement_split=TransactionSplit(transaction_id=split_payer.id,owner_id=bailey.id,ownership='individual',amount=-60)
    normal_split=TransactionSplit(transaction_id=split_payer.id,owner_id=bailey.id,ownership='individual',amount=-40)
    db.add_all([settlement_split,normal_split]);db.commit()
    create_household_settlement(HouseholdSettlementIn(payer_transaction_id=split_payer.id,source_split_id=settlement_split.id,payer_user_id=bailey.id,recipient_user_id=james.id,settlement_amount=50,category_id=groceries.id),admin,db)
    split_allocations=scope_aware_transaction_allocations([split_payer],db,bailey.id)
    assert sorted((item['scope_treatment'],item['amount']) for item in split_allocations)==[('household_settlement_expense',-50.0),('normal',-40.0),('normal',-10.0)]

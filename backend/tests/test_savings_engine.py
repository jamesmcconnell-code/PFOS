from datetime import date, timedelta
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import available_cash_planner, delete_category, metrics, planner_cash_history, reports, update_transaction_date
from app.models import Account, AccountBalanceSnapshot, Category, Household, HouseholdMember, PlannerAdjustment, PlannerStartingCarryover, RecurringPlannerExpenseRule, SavingsRule, Tag, Transaction, TransactionTag, User
from app.schemas import CategoryDelete, TransactionDateUpdate


def test_monthly_savings_uses_designated_credits_and_spending_net_cash_flow():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    home=Household(name='Test household');db.add(home);db.flush()
    spending=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0)
    savings=Account(household_id=home.id,name='Brokerage funding',type='savings',account_type='brokerage',is_savings_direct_deposit=True,balance=0)
    db.add_all([spending,savings]);db.flush()
    today=date.today().replace(day=1)
    db.add_all([
        Transaction(household_id=home.id,account_id=savings.id,date=today,description='Automated contribution',amount=1000),
        Transaction(household_id=home.id,account_id=savings.id,date=today,description='Buy order',amount=-700),
        Transaction(household_id=home.id,account_id=spending.id,date=today,description='Paycheck',amount=1650),
        Transaction(household_id=home.id,account_id=spending.id,date=today,description='Groceries',amount=-500,is_essential=True),
        Transaction(household_id=home.id,account_id=spending.id,date=today,description='Transfer to savings',amount=-100,is_internal_transfer=True),
    ]);db.commit()
    result=metrics(home.id,db)
    assert result['automated_savings']==1000
    assert result['spending_net_cash_flow']==1150
    assert result['monthly_savings']==2150
    assert result['monthly_expenses']==500
    sources={source['account_name']:source for source in result['monthly_sources']}
    assert sources['Brokerage funding']['automated_savings']==1000
    assert sources['Checking']['income']==1650
    assert sources['Checking']['expenses']==500
    assert sources['Checking']['spending_cash_flow']==1150


def test_net_worth_uses_crypto_usd_value_not_token_quantity():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    home=Household(name='Test household');db.add(home);db.flush()
    db.add(Account(household_id=home.id,name='BTC',type='crypto',account_type='crypto',asset_symbol='BTC',balance=2,crypto_usd_value=180000))
    db.commit()
    assert metrics(home.id,db)['net_worth']==180000

def test_rolling_30_days_includes_today_and_excludes_day_31():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    home=Household(name='Test household');db.add(home);db.flush()
    spending=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0);db.add(spending);db.flush()
    db.add_all([
        Transaction(household_id=home.id,account_id=spending.id,date=date.today()-timedelta(days=29),description='Included',amount=100),
        Transaction(household_id=home.id,account_id=spending.id,date=date.today()-timedelta(days=30),description='Excluded',amount=200),
    ]);db.commit()
    result=metrics(home.id,db,period='rolling_30_days')
    assert result['monthly_income']==100
    assert result['period_start']==str(date.today()-timedelta(days=29))

def test_available_cash_planner_separates_refunds_prorated_expected_and_debt_items():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='planner@example.com',display_name='Planner',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    checking=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0)
    savings=Account(household_id=home.id,name='Savings',type='savings',account_type='income',is_savings_direct_deposit=True,balance=0)
    debt=Account(household_id=home.id,name='Card',type='credit',account_type='debt',balance=0)
    db.add_all([checking,savings,debt]);db.flush()
    db.add_all([
        Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Paycheck',amount=1000),
        Transaction(household_id=home.id,account_id=savings.id,date=date.today(),description='Savings',amount=300),
        Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Refund',amount=50,is_refund=True,is_internal_transfer=True),
        Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Rent',amount=-200),
        Transaction(household_id=home.id,account_id=debt.id,date=date.today(),description='Subscription',amount=-20,is_expected=True),
        Transaction(household_id=home.id,account_id=debt.id,date=date.today(),description='Purchase',amount=-100),
        Transaction(household_id=home.id,account_id=debt.id,date=date.today()+timedelta(days=1),description='Future purchase',amount=-25),
        Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Prorated fee',amount=-240,is_prorated=True,proration_months=12),
        Transaction(household_id=home.id,account_id=checking.id,date=date.today()-timedelta(days=120),description='Expired proration',amount=-300,is_prorated=True,proration_months=3),
    ]);db.commit()
    result=available_cash_planner('paycheck',date.today(),None,user,db)
    assert result['nmp_paycheck']==1300
    assert result['automated_savings_sources'][0]['description']=='Savings'
    assert result['regular_expected_prorated_expenses']==230
    assert {item['type'] for item in result['expense_input_sources']}=={'Fixed','Expected','Prorated'}
    assert result['expense_input_sources'][-1]['proration_months']==12
    assert result['debt_line_item_total']==100
    assert result['debt_line_item_through']==str(date.today())
    assert result['gross_total_period_expenses']==330
    assert result['refund_expense_offset']==50
    assert result['total_period_expenses']==280
    assert result['refunds'][0]['refund_included'] is True

def test_monthly_planner_returns_every_paycheck_source_and_monthly_nmp():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='monthly-planner@example.com',display_name='Monthly',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    checking=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0); savings=Account(household_id=home.id,name='Savings',type='savings',account_type='income',is_savings_direct_deposit=True,balance=0);db.add_all([checking,savings]);db.flush()
    anchor=date.today().replace(day=20);first=anchor.replace(day=2);second=anchor.replace(day=17)
    db.add_all([Transaction(household_id=home.id,account_id=checking.id,date=first,description='Paycheck one',amount=1000),Transaction(household_id=home.id,account_id=checking.id,date=second,description='Paycheck two',amount=1000),Transaction(household_id=home.id,account_id=savings.id,date=first,description='Savings one',amount=300),Transaction(household_id=home.id,account_id=savings.id,date=second,description='Savings two',amount=300)]);db.commit()
    result=available_cash_planner('monthly',anchor,None,user,db)
    assert result['paycheck_amount']==2000
    assert len(result['paycheck_sources'])==2
    assert result['automated_savings_amount']==600
    assert result['net_monthly_pay']==2600

def test_loan_reimbursement_tag_excludes_a_designated_credit_from_automated_savings():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='loan-tag@example.com',display_name='Loan tag',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    savings=Account(household_id=home.id,name='Savings',type='savings',account_type='income',is_savings_direct_deposit=True,balance=0);db.add(savings);db.flush()
    loan_tag=Tag(household_id=home.id,name='Loan reimbursement');db.add(loan_tag);db.flush()
    transaction=Transaction(household_id=home.id,account_id=savings.id,date=date.today(),description='Loan repayment',amount=500);db.add(transaction);db.flush();db.add(TransactionTag(transaction_id=transaction.id,tag_id=loan_tag.id));db.commit()
    planner=available_cash_planner('paycheck',date.today(),None,user,db)
    monthly=metrics(home.id,db)
    assert planner['automated_savings_amount']==0
    assert planner['automated_savings_sources']==[]
    assert monthly['automated_savings']==0

def test_one_month_proration_uses_half_of_a_monthly_charge_per_paycheck():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='half-proration@example.com',display_name='Half',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    checking=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0);db.add(checking);db.flush()
    db.add(Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Monthly membership',amount=-120,is_prorated=True,proration_months=1));db.commit()
    result=available_cash_planner('paycheck',date.today(),None,user,db)
    assert result['prorated_expenses']==60
    assert result['expense_input_sources'][0]['period_amount']==60

def test_subcategory_inherits_its_parents_savings_rule_at_any_depth():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='category-tree@example.com',display_name='Tree',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    account=Account(household_id=home.id,name='Checking',type='checking',account_type='income',balance=0);parent=Category(household_id=home.id,name='Fixed expense',kind='income');child=Category(household_id=home.id,parent_id=parent.id,name='Phone Bill',kind='income');db.add_all([account,parent]);db.flush();child.parent_id=parent.id;db.add(child);db.flush()
    db.add(SavingsRule(household_id=home.id,category_id=parent.id))
    transaction=Transaction(household_id=home.id,account_id=account.id,category_id=child.id,date=date.today(),description='Phone reimbursement',amount=125);db.add(transaction);db.commit()
    assert available_cash_planner('paycheck',date.today(),None,user,db)['automated_savings_amount']==125
    assert metrics(home.id,db)['automated_savings']==125

def test_anticipated_monthly_expense_projects_before_posting_and_splits_paychecks():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='anticipated@example.com',display_name='Anticipated',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    account=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0);db.add(account);db.flush()
    source=Transaction(household_id=home.id,account_id=account.id,date=date(2026,7,1),description='Phone Bill',amount=-120,is_expected=True,is_prorated=True,proration_months=1);db.add(source);db.flush()
    db.add(RecurringPlannerExpenseRule(household_id=home.id,source_transaction_id=source.id,account_id=account.id,display_name='Phone Bill',source_description='Phone Bill',monthly_projected_amount=120,expected_day_of_month=1,proration_months=1));db.commit()
    paycheck=available_cash_planner('paycheck',date(2026,8,2),None,user,db)
    monthly=available_cash_planner('monthly',date(2026,8,2),None,user,db)
    assert paycheck['actual_expense_total']==0
    assert paycheck['anticipated_expense_total']==60
    assert paycheck['total_period_expenses']==60
    assert paycheck['anticipated_expense_sources'][0]['status']=='anticipated'
    assert monthly['anticipated_expense_total']==120

def test_actual_recurring_expense_reconciles_and_replaces_projection():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='reconciled@example.com',display_name='Reconciled',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    account=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0);db.add(account);db.flush()
    source=Transaction(household_id=home.id,account_id=account.id,date=date(2026,7,1),description='Phone Bill',amount=-120,is_expected=True,is_prorated=True,proration_months=1);actual=Transaction(household_id=home.id,account_id=account.id,date=date(2026,8,2),description='Phone Bill',amount=-140,is_expected=True,is_prorated=True,proration_months=1);db.add_all([source,actual]);db.flush()
    db.add(RecurringPlannerExpenseRule(household_id=home.id,source_transaction_id=source.id,account_id=account.id,display_name='Phone Bill',source_description='Phone Bill',monthly_projected_amount=120,expected_day_of_month=1,proration_months=1));db.commit()
    result=available_cash_planner('paycheck',date(2026,8,2),None,user,db)
    assert result['anticipated_expense_total']==0
    assert result['actual_expense_total']==70
    assert result['total_period_expenses']==70
    assert result['reconciled_anticipated_expenses'][0]['variance']==20

def test_reports_scopes_data_and_creates_balance_snapshots():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='reports@example.com',display_name='Reports',password_hash='x'); home=Household(name='Test household',checking_account_ceiling=500); db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    checking=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=1200)
    card=Account(household_id=home.id,name='Card',type='credit',account_type='debt',balance=-300)
    brokerage=Account(household_id=home.id,name='Brokerage',type='investment',account_type='brokerage',balance=5000)
    db.add_all([checking,card,brokerage]);db.flush()
    db.add_all([
        Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Pay',amount=1000),
        Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Groceries',amount=-100),
        Transaction(household_id=home.id,account_id=brokerage.id,date=date.today(),description='Contribution',amount=400),
    ]);db.commit()
    result=reports('1M',None,user,db)
    assert result['net_worth']['current']==5900
    assert result['investments']['current_value']==5000
    assert result['cash_flow']['categories'][0]['name']=='Uncategorized'
    assert result['simple_mode']['spend_target']['target']==500
    assert db.scalar(select(func.count()).select_from(AccountBalanceSnapshot))==3

def test_category_delete_reassigns_transactions_without_deleting_them():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='categories@example.com',display_name='Categories',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    account=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0);old=Category(household_id=home.id,name='Old',kind='expense');new=Category(household_id=home.id,name='New',kind='expense');db.add_all([account,old,new]);db.flush()
    transaction=Transaction(household_id=home.id,account_id=account.id,category_id=old.id,date=date.today(),description='Purchase',amount=-10);db.add(transaction);db.commit()
    delete_category(old.id,CategoryDelete(replacement_category_id=new.id),user,db)
    assert db.get(Category,old.id) is None
    assert db.get(Transaction,transaction.id).category_id==new.id

def test_transaction_date_override_persists():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    user=User(email='date@example.com',display_name='Date',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    account=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0);db.add(account);db.flush();transaction=Transaction(household_id=home.id,account_id=account.id,date=date.today(),description='Purchase',amount=-10);db.add(transaction);db.commit()
    replacement=date.today()-timedelta(days=10)
    update_transaction_date(transaction.id,TransactionDateUpdate(date=replacement),user,db)
    assert db.get(Transaction,transaction.id).date==replacement

def test_rolling_cash_carries_paychecks_and_applies_signed_adjustments():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);db=sessionmaker(bind=engine)()
    user=User(email='rolling-paycheck@example.com',display_name='Rolling',password_hash='x');home=Household(name='Test household');db.add_all([user,home]);db.flush();db.add(HouseholdMember(household_id=home.id,user_id=user.id));db.flush()
    checking=Account(household_id=home.id,name='Checking',type='checking',account_type='spending',balance=0);db.add(checking);db.flush()
    db.add_all([PlannerStartingCarryover(household_id=home.id,period_type='paycheck',effective_period_start=date(2026,8,1),amount=100),Transaction(household_id=home.id,account_id=checking.id,date=date(2026,8,2),description='Pay',amount=1000),Transaction(household_id=home.id,account_id=checking.id,date=date(2026,8,3),description='Bill',amount=-300),Transaction(household_id=home.id,account_id=checking.id,date=date(2026,8,16),description='Pay',amount=1000),Transaction(household_id=home.id,account_id=checking.id,date=date(2026,8,17),description='Bill',amount=-200),PlannerAdjustment(household_id=home.id,period_type='paycheck',effective_period_start=date(2026,8,16),amount=-50,note='Cash withdrawal')]);db.commit()
    result=planner_cash_history(home.id,'paycheck',date(2026,8,20),None,user,db)
    assert result['history'][-2]['ending_rolling_available_cash']==800
    assert result['current']['free_spending']==800
    assert result['current']['manual_adjustments']==-50
    assert result['current']['ending_rolling_available_cash']==1550

def test_rolling_cash_monthly_uses_opening_anticipated_refunds_and_scope_isolation():
    engine=create_engine('sqlite://');Base.metadata.create_all(engine);db=sessionmaker(bind=engine)()
    james=User(email='rolling-james@example.com',display_name='James',password_hash='x');bailey=User(email='rolling-bailey@example.com',display_name='Bailey',password_hash='x');home=Household(name='Test household');db.add_all([james,bailey,home]);db.flush();db.add_all([HouseholdMember(household_id=home.id,user_id=james.id),HouseholdMember(household_id=home.id,user_id=bailey.id)]);db.flush()
    joint=Account(household_id=home.id,name='Joint checking',type='checking',account_type='spending',balance=0);individual=Account(household_id=home.id,owner_id=bailey.id,ownership='individual',name='Bailey checking',type='checking',account_type='spending',balance=0);db.add_all([joint,individual]);db.flush()
    source=Transaction(household_id=home.id,account_id=joint.id,date=date(2026,7,1),description='Phone',amount=-120,is_expected=True,is_prorated=True,proration_months=1)
    db.add_all([PlannerStartingCarryover(household_id=home.id,period_type='monthly',effective_period_start=date(2026,8,1),amount=100),PlannerAdjustment(household_id=home.id,owner_id=bailey.id,period_type='monthly',effective_period_start=date(2026,8,1),amount=500),Transaction(household_id=home.id,account_id=joint.id,date=date(2026,8,2),description='Pay',amount=1000),Transaction(household_id=home.id,account_id=joint.id,date=date(2026,8,3),description='Refund',amount=50,is_refund=True),source]);db.flush();db.add(RecurringPlannerExpenseRule(household_id=home.id,source_transaction_id=source.id,account_id=joint.id,display_name='Phone',source_description='Phone',monthly_projected_amount=120,expected_day_of_month=1,proration_months=1));db.commit()
    joint_result=planner_cash_history(home.id,'monthly',date(2026,8,2),None,james,db)
    assert joint_result['current']['anticipated_expenses']==120
    assert joint_result['current']['total_period_expenses']==70
    assert joint_result['current']['ending_rolling_available_cash']==1030
    bailey_result=planner_cash_history(home.id,'monthly',date(2026,8,2),bailey.id,james,db)
    assert bailey_result['current']['manual_adjustments']==500
    assert joint_result['current']['manual_adjustments']==0

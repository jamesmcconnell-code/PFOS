from datetime import date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import available_cash_planner, metrics
from app.models import Account, Household, HouseholdMember, Transaction, User


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

def test_available_cash_planner_separates_refunds_annual_expected_and_debt_items():
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
        Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Refund',amount=50,is_refund=True),
        Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Rent',amount=-200),
        Transaction(household_id=home.id,account_id=debt.id,date=date.today(),description='Subscription',amount=-20,is_expected=True),
        Transaction(household_id=home.id,account_id=debt.id,date=date.today(),description='Purchase',amount=-100),
        Transaction(household_id=home.id,account_id=checking.id,date=date.today(),description='Annual fee',amount=-240,is_annual=True),
    ]);db.commit()
    result=available_cash_planner('paycheck',date.today(),None,user,db)
    assert result['nmp_paycheck']==1300
    assert result['regular_expected_annual_expenses']==230
    assert result['debt_line_item_total']==100
    assert result['gross_total_period_expenses']==330
    assert result['refund_expense_offset']==50
    assert result['total_period_expenses']==280
    assert result['refunds'][0]['refund_included'] is True

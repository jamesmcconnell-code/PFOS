from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import metrics
from app.models import Account, Household, Transaction


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


def test_net_worth_uses_crypto_usd_value_not_token_quantity():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    db=sessionmaker(bind=engine)()
    home=Household(name='Test household');db.add(home);db.flush()
    db.add(Account(household_id=home.id,name='BTC',type='crypto',account_type='crypto',asset_symbol='BTC',balance=2,crypto_usd_value=180000))
    db.commit()
    assert metrics(home.id,db)['net_worth']==180000

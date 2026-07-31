"""Run `python -m app.seed` after migrations for a local demo household."""
from datetime import date
from .database import SessionLocal
from .models import *
from .security import hash_password
def main():
 db=SessionLocal()
 if db.query(User).filter_by(email='admin@example.com').first(): return
 u=User(email='admin@example.com',display_name='James',password_hash=hash_password('change-me-now')); h=Household(name='James & Fiancee');db.add_all([u,h]);db.flush();db.add(HouseholdMember(household_id=h.id,user_id=u.id,role='owner'))
 checking=Account(household_id=h.id,name='Joint Checking',type='checking',balance=8400); savings=Account(household_id=h.id,name='House Savings',type='savings',balance=24000);db.add_all([checking,savings]);db.flush()
 db.add_all([IncomeSource(household_id=h.id,name='James income',monthly_amount=6500),IncomeSource(household_id=h.id,name='Fiancee income',monthly_amount=5000),Goal(household_id=h.id,name='Emergency Fund',type='emergency_fund',target_amount=30000),Goal(household_id=h.id,name='House Fund',type='house_fund',target_amount=80000)])
 db.commit(); print('Seeded admin@example.com / change-me-now')
if __name__=='__main__': main()

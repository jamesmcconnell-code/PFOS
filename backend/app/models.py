import uuid
from datetime import datetime, date
from sqlalchemy import String, Boolean, DateTime, Date, Numeric, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def uid(): return uuid.uuid4()
class Audit:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class User(Audit, Base):
    __tablename__='users'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); email: Mapped[str]=mapped_column(String(320),unique=True,index=True); password_hash: Mapped[str]=mapped_column(String(255)); display_name: Mapped[str]=mapped_column(String(100)); role: Mapped[str]=mapped_column(String(20),default='USER'); theme_preference: Mapped[str]=mapped_column(String(30),default='system'); simple_mode_enabled: Mapped[bool]=mapped_column(Boolean,default=False); is_active: Mapped[bool]=mapped_column(Boolean,default=True)
class Household(Audit, Base):
    __tablename__='households'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); name: Mapped[str]=mapped_column(String(120)); currency: Mapped[str]=mapped_column(String(3),default='USD'); checking_account_ceiling: Mapped[float]=mapped_column(Numeric(14,2),default=0)
class HouseholdMember(Audit, Base):
    __tablename__='household_members'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('users.id',ondelete='CASCADE')); role: Mapped[str]=mapped_column(String(30),default='member'); __table_args__=(UniqueConstraint('household_id','user_id'),)
class Institution(Audit, Base):
    __tablename__='institutions'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); name: Mapped[str]=mapped_column(String(150));
class Account(Audit, Base):
    __tablename__='accounts'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); institution_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('institutions.id',ondelete='SET NULL'),nullable=True); connection_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('data_connections.id',ondelete='SET NULL'),nullable=True); external_id: Mapped[str|None]=mapped_column(String(255),nullable=True); owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True); ownership: Mapped[str]=mapped_column(String(20),default='joint'); account_type: Mapped[str]=mapped_column(String(20),default='spending'); asset_symbol: Mapped[str|None]=mapped_column(String(20),nullable=True); crypto_usd_value: Mapped[float|None]=mapped_column(Numeric(18,2),nullable=True); crypto_price_updated_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True); is_savings_direct_deposit: Mapped[bool]=mapped_column(Boolean,default=False); name: Mapped[str]=mapped_column(String(100)); type: Mapped[str]=mapped_column(String(30)); balance: Mapped[float]=mapped_column(Numeric(24,8),default=0); is_active: Mapped[bool]=mapped_column(Boolean,default=True)
class AccountBalanceSnapshot(Audit, Base):
    __tablename__='account_balance_snapshots'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); account_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('accounts.id',ondelete='CASCADE')); snapshot_date: Mapped[date]=mapped_column(Date); balance: Mapped[float]=mapped_column(Numeric(24,8)); usd_value: Mapped[float|None]=mapped_column(Numeric(18,2),nullable=True); source: Mapped[str]=mapped_column(String(20),default='calculated'); __table_args__=(UniqueConstraint('account_id','snapshot_date',name='uq_account_balance_snapshot_date'),)
class Category(Audit, Base):
    __tablename__='categories'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); parent_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('categories.id',ondelete='SET NULL'),nullable=True,index=True); name: Mapped[str]=mapped_column(String(100)); kind: Mapped[str]=mapped_column(String(20)); is_essential_default: Mapped[bool]=mapped_column(Boolean,default=False)
class Transaction(Audit, Base):
    __tablename__='transactions'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); account_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('accounts.id',ondelete='CASCADE')); connection_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('data_connections.id',ondelete='SET NULL'),nullable=True); external_id: Mapped[str|None]=mapped_column(String(255),nullable=True); source_category: Mapped[str|None]=mapped_column(String(100),nullable=True); is_pending: Mapped[bool]=mapped_column(Boolean,default=False); category_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('categories.id',ondelete='SET NULL'),nullable=True); owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True); date: Mapped[date]=mapped_column(Date); planner_effective_date: Mapped[date|None]=mapped_column(Date,nullable=True); description: Mapped[str]=mapped_column(String(255)); amount: Mapped[float]=mapped_column(Numeric(14,2)); notes: Mapped[str|None]=mapped_column(Text,nullable=True); is_essential: Mapped[bool]=mapped_column(Boolean,default=False); is_recurring: Mapped[bool]=mapped_column(Boolean,default=False); is_internal_transfer: Mapped[bool]=mapped_column(Boolean,default=False); is_refund: Mapped[bool]=mapped_column(Boolean,default=False); refund_included: Mapped[bool]=mapped_column(Boolean,default=True); is_expected: Mapped[bool]=mapped_column(Boolean,default=False); is_prorated: Mapped[bool]=mapped_column(Boolean,default=False); proration_months: Mapped[int]=mapped_column(default=12); classification_rule_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('transaction_classification_rules.id',ondelete='SET NULL'),nullable=True); classification_explanation: Mapped[str|None]=mapped_column(Text,nullable=True); fingerprint: Mapped[str|None]=mapped_column(String(64),nullable=True,index=True); __table_args__=(UniqueConstraint('connection_id','external_id',name='uq_transaction_connection_external'),)
class TransactionSplit(Audit, Base):
    __tablename__='transaction_splits'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); transaction_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transactions.id',ondelete='CASCADE')); member_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('household_members.id',ondelete='SET NULL'),nullable=True); owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True); ownership: Mapped[str]=mapped_column(String(20),default='joint'); category_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('categories.id',ondelete='SET NULL'),nullable=True); is_refund: Mapped[bool]=mapped_column(Boolean,default=False); refund_included: Mapped[bool]=mapped_column(Boolean,default=True); amount: Mapped[float]=mapped_column(Numeric(14,2))
class HouseholdSettlement(Audit, Base):
    """Planner/reporting treatment for a confirmed repayment between members.

    This intentionally records a treatment around imported transactions rather
    than changing their amounts, categories, transfer flag, or bank history.
    """
    __tablename__='household_settlements'
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid)
    household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE'),index=True)
    payer_transaction_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transactions.id',ondelete='CASCADE'),index=True)
    recipient_transaction_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('transactions.id',ondelete='SET NULL'),nullable=True,index=True)
    source_split_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('transaction_splits.id',ondelete='SET NULL'),nullable=True,index=True)
    payer_user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    recipient_user_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('users.id',ondelete='CASCADE'),index=True)
    settlement_amount: Mapped[float]=mapped_column(Numeric(14,2))
    category_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('categories.id',ondelete='SET NULL'),nullable=True)
    note: Mapped[str|None]=mapped_column(Text,nullable=True)
    settlement_group_id: Mapped[uuid.UUID|None]=mapped_column(nullable=True,index=True)
    status: Mapped[str]=mapped_column(String(20),default='active',index=True)
    reversal_note: Mapped[str|None]=mapped_column(Text,nullable=True)
    reversed_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
class HouseholdSettlementPurchaseLink(Audit, Base):
    __tablename__='household_settlement_purchase_links'
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid)
    settlement_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('household_settlements.id',ondelete='CASCADE'),index=True)
    original_transaction_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transactions.id',ondelete='CASCADE'),index=True)
    original_split_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('transaction_splits.id',ondelete='SET NULL'),nullable=True,index=True)
    allocated_amount: Mapped[float]=mapped_column(Numeric(14,2))
    note: Mapped[str|None]=mapped_column(Text,nullable=True)
class Tag(Audit, Base):
    __tablename__='tags'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); name: Mapped[str]=mapped_column(String(50))
class TransactionTag(Base):
    __tablename__='transaction_tags'; transaction_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transactions.id',ondelete='CASCADE'),primary_key=True); tag_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('tags.id',ondelete='CASCADE'),primary_key=True)
class TransactionSplitTag(Base):
    __tablename__='transaction_split_tags'; split_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transaction_splits.id',ondelete='CASCADE'),primary_key=True); tag_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('tags.id',ondelete='CASCADE'),primary_key=True)
class MerchantIdentity(Audit, Base):
    __tablename__='merchant_identities'
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid)
    household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE'),index=True)
    normalized_merchant_key: Mapped[str]=mapped_column(String(255))
    display_name: Mapped[str]=mapped_column(String(255))
    source_metadata: Mapped[str|None]=mapped_column(Text,nullable=True)
    __table_args__=(UniqueConstraint('household_id','normalized_merchant_key',name='uq_merchant_identity_household_key'),)
class TransactionClassificationRule(Audit, Base):
    __tablename__='transaction_classification_rules'
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid)
    household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE'),index=True)
    owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True,index=True)
    account_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('accounts.id',ondelete='CASCADE'),nullable=True,index=True)
    normalized_merchant_key: Mapped[str|None]=mapped_column(String(255),nullable=True,index=True)
    description_pattern: Mapped[str|None]=mapped_column(String(255),nullable=True)
    direction: Mapped[str]=mapped_column(String(10),default='any')
    financial_role: Mapped[str|None]=mapped_column(String(20),nullable=True)
    category_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('categories.id',ondelete='SET NULL'),nullable=True)
    classified_owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True)
    essential: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    internal_transfer: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    refund_credit: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    loan_reimbursement: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    expected: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    prorated: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    proration_months: Mapped[int|None]=mapped_column(nullable=True)
    name: Mapped[str]=mapped_column(String(120),default='Classification rule')
    priority: Mapped[int]=mapped_column(default=100,index=True)
    is_active: Mapped[bool]=mapped_column(Boolean,default=True,index=True)
    source_type: Mapped[str]=mapped_column(String(20),default='user_authored')
    planner_automation_approved: Mapped[bool]=mapped_column(Boolean,default=False)
class TransactionClassificationRuleTag(Base):
    __tablename__='transaction_classification_rule_tags'
    rule_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transaction_classification_rules.id',ondelete='CASCADE'),primary_key=True)
    tag_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('tags.id',ondelete='CASCADE'),primary_key=True)
class TransactionClassificationSuggestion(Audit, Base):
    __tablename__='transaction_classification_suggestions'
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid)
    household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE'),index=True)
    transaction_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transactions.id',ondelete='CASCADE'),index=True)
    rule_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('transaction_classification_rules.id',ondelete='SET NULL'),nullable=True,index=True)
    category_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('categories.id',ondelete='SET NULL'),nullable=True)
    owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True)
    essential: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    internal_transfer: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    refund_credit: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    loan_reimbursement: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    expected: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    prorated: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    proration_months: Mapped[int|None]=mapped_column(nullable=True)
    confidence_score: Mapped[float]=mapped_column(Numeric(5,4))
    explanation: Mapped[str]=mapped_column(Text)
    proposal_data: Mapped[str|None]=mapped_column(Text,nullable=True)
    evidence_data: Mapped[str|None]=mapped_column(Text,nullable=True)
    recurring: Mapped[bool|None]=mapped_column(Boolean,nullable=True)
    source_type: Mapped[str]=mapped_column(String(20),default='rule')
    status: Mapped[str]=mapped_column(String(20),default='pending',index=True)
    safe_for_auto_apply: Mapped[bool]=mapped_column(Boolean,default=False)
class TransactionClassificationSuggestionTag(Base):
    __tablename__='transaction_classification_suggestion_tags'
    suggestion_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transaction_classification_suggestions.id',ondelete='CASCADE'),primary_key=True)
    tag_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('tags.id',ondelete='CASCADE'),primary_key=True)
class TransactionClassificationSuggestionDecision(Audit, Base):
    __tablename__='transaction_classification_suggestion_decisions'
    id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid)
    suggestion_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transaction_classification_suggestions.id',ondelete='CASCADE'),index=True)
    field_name: Mapped[str]=mapped_column(String(40))
    decision: Mapped[str]=mapped_column(String(20))
    value_data: Mapped[str|None]=mapped_column(Text,nullable=True)
    __table_args__=(UniqueConstraint('suggestion_id','field_name',name='uq_suggestion_decision_field'),)
class SavingsRule(Audit, Base):
    __tablename__='savings_rules'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); account_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('accounts.id',ondelete='CASCADE'),nullable=True); category_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('categories.id',ondelete='CASCADE'),nullable=True); tag_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('tags.id',ondelete='CASCADE'),nullable=True); is_active: Mapped[bool]=mapped_column(Boolean,default=True)
class RecurringPlannerExpenseRule(Audit, Base):
    __tablename__='recurring_planner_expense_rules'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True); source_transaction_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('transactions.id',ondelete='SET NULL'),nullable=True); account_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('accounts.id',ondelete='CASCADE')); category_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('categories.id',ondelete='SET NULL'),nullable=True); display_name: Mapped[str]=mapped_column(String(120)); source_description: Mapped[str|None]=mapped_column(String(255),nullable=True); monthly_projected_amount: Mapped[float]=mapped_column(Numeric(14,2)); expected_day_of_month: Mapped[int]=mapped_column(default=1); effective_start_date: Mapped[date|None]=mapped_column(Date,nullable=True); cadence: Mapped[str]=mapped_column(String(20),default='monthly'); is_active: Mapped[bool]=mapped_column(Boolean,default=True); proration_months: Mapped[int]=mapped_column(default=1)
class PlannerStartingCarryover(Audit, Base):
    __tablename__='planner_starting_carryovers'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True); period_type: Mapped[str]=mapped_column(String(20)); effective_period_start: Mapped[date]=mapped_column(Date); amount: Mapped[float]=mapped_column(Numeric(14,2),default=0); note: Mapped[str|None]=mapped_column(Text,nullable=True)
class PlannerAdjustment(Audit, Base):
    __tablename__='planner_adjustments'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True); period_type: Mapped[str]=mapped_column(String(20)); effective_period_start: Mapped[date]=mapped_column(Date); amount: Mapped[float]=mapped_column(Numeric(14,2)); note: Mapped[str|None]=mapped_column(Text,nullable=True)
class PlannerPaySchedule(Audit, Base):
    __tablename__='planner_pay_schedules'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); owner_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('users.id',ondelete='CASCADE')); schedule_type: Mapped[str]=mapped_column(String(20),default='semimonthly'); biweekly_anchor_start_date: Mapped[date|None]=mapped_column(Date,nullable=True); paycheck_availability_policy: Mapped[str]=mapped_column(String(20),default='next_period'); is_active: Mapped[bool]=mapped_column(Boolean,default=True); __table_args__=(UniqueConstraint('household_id','owner_id',name='uq_planner_pay_schedule_household_owner'),)
class PlannerIncomeAllocation(Audit, Base):
    __tablename__='planner_income_allocations'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True); source_transaction_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('transactions.id',ondelete='CASCADE')); period_type: Mapped[str]=mapped_column(String(20)); effective_period_start: Mapped[date]=mapped_column(Date); amount: Mapped[float]=mapped_column(Numeric(14,2)); note: Mapped[str|None]=mapped_column(Text,nullable=True)
class RecurringPlannerIncomeRule(Audit, Base):
    __tablename__='recurring_planner_income_rules'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True); source_transaction_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('transactions.id',ondelete='SET NULL'),nullable=True); account_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('accounts.id',ondelete='CASCADE')); display_name: Mapped[str]=mapped_column(String(120)); source_description: Mapped[str|None]=mapped_column(String(255),nullable=True); expected_amount: Mapped[float]=mapped_column(Numeric(14,2)); cadence: Mapped[str]=mapped_column(String(20),default='twice_monthly'); availability_day: Mapped[int]=mapped_column(default=1); effective_start_date: Mapped[date]=mapped_column(Date,default=date.today); effective_end_date: Mapped[date|None]=mapped_column(Date,nullable=True); is_active: Mapped[bool]=mapped_column(Boolean,default=True)
class Goal(Audit, Base):
    __tablename__='goals'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); funding_account_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('accounts.id',ondelete='SET NULL'),nullable=True); name: Mapped[str]=mapped_column(String(120)); type: Mapped[str]=mapped_column(String(30)); target_amount: Mapped[float]=mapped_column(Numeric(14,2)); current_amount: Mapped[float]=mapped_column(Numeric(14,2),default=0); target_date: Mapped[date|None]=mapped_column(Date,nullable=True); priority_order: Mapped[int]=mapped_column(default=0); is_complete: Mapped[bool]=mapped_column(Boolean,default=False)
class GoalContribution(Audit, Base):
    __tablename__='goal_contributions'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); goal_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('goals.id',ondelete='CASCADE')); transaction_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('transactions.id',ondelete='SET NULL'),nullable=True); amount: Mapped[float]=mapped_column(Numeric(14,2)); contributed_on: Mapped[date]=mapped_column(Date,default=date.today)
class IncomeSource(Audit, Base):
    __tablename__='income_sources'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); owner_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'),nullable=True); name: Mapped[str]=mapped_column(String(100)); monthly_amount: Mapped[float]=mapped_column(Numeric(14,2)); is_active: Mapped[bool]=mapped_column(Boolean,default=True)
class Debt(Audit, Base):
    __tablename__='debts'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); account_id: Mapped[uuid.UUID|None]=mapped_column(ForeignKey('accounts.id',ondelete='SET NULL'),nullable=True); name: Mapped[str]=mapped_column(String(100)); balance: Mapped[float]=mapped_column(Numeric(14,2)); interest_rate: Mapped[float]=mapped_column(Numeric(5,2),default=0); minimum_payment: Mapped[float]=mapped_column(Numeric(14,2),default=0)
class ImportBatch(Audit, Base):
    __tablename__='import_batches'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); account_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('accounts.id',ondelete='CASCADE')); filename: Mapped[str]=mapped_column(String(255)); imported_count: Mapped[int]=mapped_column(default=0); duplicate_count: Mapped[int]=mapped_column(default=0)
class DataConnection(Audit, Base):
    __tablename__='data_connections'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); provider: Mapped[str]=mapped_column(String(30)); name: Mapped[str]=mapped_column(String(120)); status: Mapped[str]=mapped_column(String(20),default='active'); encrypted_credentials: Mapped[str|None]=mapped_column(Text,nullable=True); cursor: Mapped[str|None]=mapped_column(Text,nullable=True); ignored_account_ids: Mapped[str]=mapped_column(Text,default='[]'); last_synced_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
class ConnectionSync(Audit, Base):
    __tablename__='connection_syncs'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); connection_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('data_connections.id',ondelete='CASCADE')); status: Mapped[str]=mapped_column(String(20),default='running'); imported_count: Mapped[int]=mapped_column(default=0); duplicate_count: Mapped[int]=mapped_column(default=0); error_message: Mapped[str|None]=mapped_column(Text,nullable=True)
class ForecastingProfile(Audit, Base):
    __tablename__='forecasting_profiles'; id: Mapped[uuid.UUID]=mapped_column(primary_key=True,default=uid); household_id: Mapped[uuid.UUID]=mapped_column(ForeignKey('households.id',ondelete='CASCADE')); name: Mapped[str]=mapped_column(String(100)); monthly_savings_override: Mapped[float|None]=mapped_column(Numeric(14,2),nullable=True); assumptions: Mapped[str|None]=mapped_column(Text,nullable=True)

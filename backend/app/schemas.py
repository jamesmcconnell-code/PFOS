from datetime import date
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
class Register(BaseModel): email: EmailStr; password: str = Field(min_length=8); display_name: str
class Login(BaseModel): email: EmailStr; password: str
class Token(BaseModel): access_token: str; token_type: str='bearer'
class AccountIn(BaseModel): name: str; type: str='manual'; balance: float=0; institution_id: UUID|None=None; account_type: str='spending'; ownership: str='joint'; owner_id: UUID|None=None; is_savings_direct_deposit: bool=False
class AccountUpdate(BaseModel):
    name: str; balance: float; account_type: str; ownership: str='joint'; owner_id: UUID|None=None; is_savings_direct_deposit: bool=False
class UserUpdate(BaseModel): display_name: str = Field(min_length=1,max_length=100); email: EmailStr
class PasswordUpdate(BaseModel): current_password: str; new_password: str = Field(min_length=10,max_length=128)
class AdminPasswordUpdate(BaseModel): new_password: str = Field(min_length=10,max_length=128)
class ThemeUpdate(BaseModel): theme_preference: str
class SimpleModeUpdate(BaseModel): simple_mode_enabled: bool
class HouseholdUserIn(Register): pass
class TransactionIn(BaseModel): account_id: UUID; date: date; description: str; amount: float; category_id: UUID|None=None; notes: str|None=None; is_essential: bool=False; is_recurring: bool=False
class ManualTransactionIn(BaseModel):
    account_id: UUID
    date: date
    description: str=Field(min_length=1,max_length=255)
    amount: float
    category_id: UUID|None=None
    owner_id: UUID|None=None
    source_category: str|None=Field(default=None,max_length=100)
    notes: str|None=Field(default=None,max_length=2000)
    is_essential: bool=False
    is_recurring: bool=False
    is_internal_transfer: bool=False
    is_refund: bool=False
    refund_included: bool=True
    is_expected: bool=False
    is_prorated: bool=False
    proration_months: int=Field(default=12,ge=1,le=120)
    tag_ids: list[UUID]=[]
class TransactionTransferUpdate(BaseModel): is_internal_transfer: bool
class TransactionCategoryUpdate(BaseModel): category_id: UUID|None=None
class TransactionDateUpdate(BaseModel): date: date
class PlannerExpenseEffectiveDateUpdate(BaseModel): planner_effective_date: date|None=None
class TransactionTagsUpdate(BaseModel): tag_ids: list[UUID]=[]
class TransactionSplitIn(BaseModel):
    amount: float
    category_id: UUID|None=None
    ownership: str='joint'
    owner_id: UUID|None=None
    tag_ids: list[UUID]=[]
    is_refund: bool=False
    refund_included: bool=True
class TransactionSplitsUpdate(BaseModel):
    splits: list[TransactionSplitIn]=Field(min_length=2,max_length=100)
class HouseholdSettlementPurchaseLinkIn(BaseModel):
    original_transaction_id: UUID
    original_split_id: UUID|None=None
    allocated_amount: float=Field(gt=0)
    note: str|None=Field(default=None,max_length=2000)
class HouseholdSettlementIn(BaseModel):
    payer_transaction_id: UUID
    recipient_transaction_id: UUID|None=None
    source_split_id: UUID|None=None
    payer_user_id: UUID
    recipient_user_id: UUID
    settlement_amount: float=Field(gt=0)
    category_id: UUID|None=None
    note: str|None=Field(default=None,max_length=2000)
    settlement_group_id: UUID|None=None
    purchase_links: list[HouseholdSettlementPurchaseLinkIn]=Field(default_factory=list,max_length=100)
class HouseholdSettlementUpdate(BaseModel):
    payer_transaction_id: UUID|None=None
    recipient_transaction_id: UUID|None=None
    source_split_id: UUID|None=None
    payer_user_id: UUID|None=None
    recipient_user_id: UUID|None=None
    settlement_amount: float|None=Field(default=None,gt=0)
    category_id: UUID|None=None
    note: str|None=Field(default=None,max_length=2000)
    settlement_group_id: UUID|None=None
    purchase_links: list[HouseholdSettlementPurchaseLinkIn]|None=Field(default=None,max_length=100)
class HouseholdSettlementReverseIn(BaseModel):
    reversal_note: str|None=Field(default=None,max_length=2000)
class CategoryIn(BaseModel):
    name: str=Field(min_length=1,max_length=100)
    kind: str='expense'
    is_essential_default: bool=False
    parent_id: UUID|None=None
class CategoryRename(BaseModel): name: str=Field(min_length=1,max_length=100)
class CategoryDelete(BaseModel): replacement_category_id: UUID
class TransactionPlannerFlagsUpdate(BaseModel):
    is_essential: bool|None=None
    is_refund: bool|None=None
    refund_included: bool|None=None
    is_expected: bool|None=None
    is_prorated: bool|None=None
    proration_months: int|None=Field(default=None,ge=1,le=120)
class TransactionClassificationRuleIn(BaseModel):
    name: str=Field(default='Classification rule',min_length=1,max_length=120)
    owner_id: UUID|None=None
    account_id: UUID|None=None
    normalized_merchant_key: str|None=Field(default=None,min_length=1,max_length=255)
    description_pattern: str|None=Field(default=None,min_length=1,max_length=255)
    direction: str='any'
    financial_role: str|None=None
    category_id: UUID|None=None
    classified_owner_id: UUID|None=None
    tag_ids: list[UUID]=Field(default_factory=list,max_length=50)
    essential: bool|None=None
    internal_transfer: bool|None=None
    refund_credit: bool|None=None
    loan_reimbursement: bool|None=None
    expected: bool|None=None
    prorated: bool|None=None
    proration_months: int|None=Field(default=None,ge=1,le=120)
    priority: int=Field(default=100,ge=0,le=100000)
    is_active: bool=True
    source_type: str='user_authored'
    planner_automation_approved: bool=False
class TransactionClassificationRuleUpdate(BaseModel):
    name: str|None=Field(default=None,min_length=1,max_length=120)
    owner_id: UUID|None=None
    account_id: UUID|None=None
    normalized_merchant_key: str|None=Field(default=None,min_length=1,max_length=255)
    description_pattern: str|None=Field(default=None,min_length=1,max_length=255)
    direction: str|None=None
    financial_role: str|None=None
    category_id: UUID|None=None
    classified_owner_id: UUID|None=None
    tag_ids: list[UUID]|None=Field(default=None,max_length=50)
    essential: bool|None=None
    internal_transfer: bool|None=None
    refund_credit: bool|None=None
    loan_reimbursement: bool|None=None
    expected: bool|None=None
    prorated: bool|None=None
    proration_months: int|None=Field(default=None,ge=1,le=120)
    priority: int|None=Field(default=None,ge=0,le=100000)
    is_active: bool|None=None
    source_type: str|None=None
    planner_automation_approved: bool|None=None
class SavingsRuleIn(BaseModel): target_type: str; target_id: UUID
class PlannerExpenseRuleIn(BaseModel):
    account_id: UUID
    display_name: str=Field(min_length=1,max_length=120)
    monthly_projected_amount: float=Field(gt=0)
    expected_day_of_month: int=Field(ge=1,le=31)
    effective_start_date: date=Field(default_factory=date.today)
    category_id: UUID|None=None
    owner_id: UUID|None=None
    proration_months: int=Field(default=1,ge=1,le=120)
    is_active: bool=True
class PlannerExpenseRuleUpdate(BaseModel):
    display_name: str|None=Field(default=None,min_length=1,max_length=120)
    monthly_projected_amount: float|None=Field(default=None,gt=0)
    expected_day_of_month: int|None=Field(default=None,ge=1,le=31)
    effective_start_date: date|None=None
    category_id: UUID|None=None
    owner_id: UUID|None=None
    proration_months: int|None=Field(default=None,ge=1,le=120)
    is_active: bool|None=None
class PlannerStartingCarryoverIn(BaseModel):
    period_type: str
    effective_period_start: date
    amount: float
    note: str|None=Field(default=None,max_length=500)
class PlannerAdjustmentIn(BaseModel):
    period_type: str
    effective_period_start: date
    amount: float
    note: str|None=Field(default=None,max_length=500)
class PlannerAdjustmentUpdate(BaseModel):
    effective_period_start: date|None=None
    amount: float|None=None
    note: str|None=Field(default=None,max_length=500)
class PlannerPayScheduleIn(BaseModel):
    schedule_type: str='semimonthly'
    biweekly_anchor_start_date: date|None=None
    paycheck_availability_policy: str='next_period'
    is_active: bool=True
class PlannerIncomeAllocationIn(BaseModel):
    source_transaction_id: UUID
    period_type: str
    effective_period_start: date
    amount: float=Field(gt=0)
    note: str|None=Field(default=None,max_length=500)
class PlannerIncomeAllocationUpdate(BaseModel):
    effective_period_start: date|None=None
    amount: float|None=Field(default=None,gt=0)
    note: str|None=Field(default=None,max_length=500)
class PlannerIncomeRuleIn(BaseModel):
    account_id: UUID; display_name: str=Field(min_length=1,max_length=120); expected_amount: float=Field(gt=0); cadence: str='twice_monthly'; availability_day: int=Field(default=1,ge=1,le=31); effective_start_date: date=Field(default_factory=date.today); source_description: str|None=None; owner_id: UUID|None=None; is_active: bool=True
class PlannerIncomeRuleUpdate(BaseModel):
    display_name: str|None=None; expected_amount: float|None=Field(default=None,gt=0); cadence: str|None=None; availability_day: int|None=Field(default=None,ge=1,le=31); effective_start_date: date|None=None; source_description: str|None=None; is_active: bool|None=None
class GoalIn(BaseModel): name: str; type: str = 'custom'; target_amount: float=Field(gt=0); current_amount: float=Field(default=0,ge=0); target_date: date; funding_account_id: UUID|None=None
class GoalUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: float = Field(gt=0)
    current_amount: float = Field(ge=0)
    target_date: date
    funding_account_id: UUID|None=None
class GoalPriorityUpdate(BaseModel): goal_ids: list[UUID]
class FinancialSettingsUpdate(BaseModel): checking_account_ceiling: float=Field(ge=0)
class IncomeIn(BaseModel): name: str; monthly_amount: float; owner_id: UUID|None=None
class ConnectionIn(BaseModel):
    provider: str
    name: str
    credentials: dict[str, str] = {}
class PlaidExchangeIn(BaseModel):
    public_token: str
    name: str

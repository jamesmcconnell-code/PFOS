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
class TransactionTransferUpdate(BaseModel): is_internal_transfer: bool
class TransactionCategoryUpdate(BaseModel): category_id: UUID|None=None
class TransactionDateUpdate(BaseModel): date: date
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
class SavingsRuleIn(BaseModel): target_type: str; target_id: UUID
class PlannerExpenseRuleIn(BaseModel):
    account_id: UUID
    display_name: str=Field(min_length=1,max_length=120)
    monthly_projected_amount: float=Field(gt=0)
    expected_day_of_month: int=Field(ge=1,le=31)
    category_id: UUID|None=None
    owner_id: UUID|None=None
    proration_months: int=Field(default=1,ge=1,le=120)
    is_active: bool=True
class PlannerExpenseRuleUpdate(BaseModel):
    display_name: str|None=Field(default=None,min_length=1,max_length=120)
    monthly_projected_amount: float|None=Field(default=None,gt=0)
    expected_day_of_month: int|None=Field(default=None,ge=1,le=31)
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

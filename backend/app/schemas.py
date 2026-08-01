from datetime import date
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
class Register(BaseModel): email: EmailStr; password: str = Field(min_length=8); display_name: str
class Login(BaseModel): email: EmailStr; password: str
class Token(BaseModel): access_token: str; token_type: str='bearer'
class AccountIn(BaseModel): name: str; type: str='manual'; balance: float=0; institution_id: UUID|None=None; account_type: str='spending'; ownership: str='joint'; owner_id: UUID|None=None; is_savings_direct_deposit: bool=False
class AccountUpdate(BaseModel):
    name: str; balance: float; account_type: str; ownership: str='joint'; owner_id: UUID|None=None; is_savings_direct_deposit: bool=False
class UserUpdate(BaseModel): display_name: str = Field(min_length=1,max_length=100); email: EmailStr; password: str|None = Field(default=None,min_length=8)
class HouseholdUserIn(Register): pass
class TransactionIn(BaseModel): account_id: UUID; date: date; description: str; amount: float; category_id: UUID|None=None; notes: str|None=None; is_essential: bool=False; is_recurring: bool=False
class TransactionTransferUpdate(BaseModel): is_internal_transfer: bool
class TransactionCategoryUpdate(BaseModel): category_id: UUID|None=None
class TransactionTagsUpdate(BaseModel): tag_ids: list[UUID]=[]
class TransactionPlannerFlagsUpdate(BaseModel):
    is_refund: bool|None=None
    refund_included: bool|None=None
    is_expected: bool|None=None
    is_annual: bool|None=None
class SavingsRuleIn(BaseModel): target_type: str; target_id: UUID
class GoalIn(BaseModel): name: str; type: str = 'custom'; target_amount: float=Field(gt=0); current_amount: float=Field(default=0,ge=0); target_date: date
class GoalUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: float = Field(gt=0)
    current_amount: float = Field(ge=0)
    target_date: date
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

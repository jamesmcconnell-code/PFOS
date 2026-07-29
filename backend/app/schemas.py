from datetime import date
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field
class Register(BaseModel): email: EmailStr; password: str = Field(min_length=8); display_name: str
class Login(BaseModel): email: EmailStr; password: str
class Token(BaseModel): access_token: str; token_type: str='bearer'
class AccountIn(BaseModel): name: str; type: str; balance: float=0; institution_id: UUID|None=None
class TransactionIn(BaseModel): account_id: UUID; date: date; description: str; amount: float; category_id: UUID|None=None; notes: str|None=None; is_essential: bool=False; is_recurring: bool=False
class GoalIn(BaseModel): name: str; type: str = 'custom'; target_amount: float; target_date: date|None=None
class GoalUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: float = Field(gt=0)
class IncomeIn(BaseModel): name: str; monthly_amount: float; owner_id: UUID|None=None
class ConnectionIn(BaseModel):
    provider: str
    name: str
    credentials: dict[str, str] = {}
class PlaidExchangeIn(BaseModel):
    public_token: str
    name: str

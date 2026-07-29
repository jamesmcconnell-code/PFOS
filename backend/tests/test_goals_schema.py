import pytest
from pydantic import ValidationError
from app.schemas import GoalIn, GoalUpdate

def test_goal_defaults_to_custom_type_for_simple_ui_create():
    goal=GoalIn(name='Kitchen renovation',target_amount=12000)
    assert goal.type=='custom'

def test_goal_update_requires_positive_target():
    with pytest.raises(ValidationError): GoalUpdate(name='Emergency Fund',target_amount=0)

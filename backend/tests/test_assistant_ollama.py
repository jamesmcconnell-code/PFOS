"""Privacy and authorization checks for the optional local PFOS assistant."""
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import main
from app.config import settings
from app.database import create_database_engine, get_db
from app.models import Account, Category, Goal, HouseholdMember, Transaction
from app.ollama_assistant import OllamaUnavailable, get_ollama_status


@pytest.fixture
def assistant_context(tmp_path, monkeypatch):
    database_path = tmp_path / 'assistant.db'
    url = f'sqlite:///{database_path}'
    monkeypatch.setattr(settings, 'database_url', url)
    config = Config()
    config.set_main_option('script_location', str(Path(__file__).resolve().parents[1] / 'alembic'))
    command.upgrade(config, 'head')
    engine = create_database_engine(url)

    def database_session():
        with Session(engine, autoflush=False) as db:
            yield db

    app = main.app
    app.dependency_overrides[get_db] = database_session
    monkeypatch.setattr(settings, 'ollama_enabled', True)
    monkeypatch.setattr(settings, 'ollama_model', 'qwen2.5:7b')
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def register(client, email):
    response = client.post('/api/v1/auth/register', json={
        'email': email,
        'password': 'Assistant-test-123',
        'display_name': 'Assistant Test',
    })
    assert response.status_code == 200, response.text
    return {'Authorization': f"Bearer {response.json()['access_token']}"}


def add_financial_fixtures(engine, user_id):
    with Session(engine) as db:
        household_id = db.scalar(select(HouseholdMember.household_id).where(HouseholdMember.user_id == UUID(user_id)))
        category = Category(household_id=household_id, name='Shopping', kind='expense')
        account = Account(household_id=household_id, name='Checking', type='checking', balance=5000)
        goal = Goal(household_id=household_id, name='Home purchase', type='custom', target_amount=20000,
                    current_amount=1000, target_date=date.today() + timedelta(days=365), priority_order=0)
        db.add_all([category, account, goal])
        db.flush()
        db.add(Transaction(
            household_id=household_id, account_id=account.id, category_id=category.id,
            date=date.today() - timedelta(days=10), description='Synthetic grocery store purchase', amount=-120,
        ))
        db.commit()
        return category.id, goal.id


def test_chat_requires_auth_and_rejects_malformed_or_oversized_history(assistant_context):
    client, _engine = assistant_context
    assert client.post('/api/v1/assistant/chat', json={'messages': [{'role': 'user', 'content': 'help'}]}).status_code in (401, 403)
    headers = register(client, 'assistant-validation@example.com')

    malformed = client.post('/api/v1/assistant/chat', headers=headers, json={
        'messages': [{'role': 'user', 'content': 'question'}, {'role': 'user', 'content': 'repeated role'}],
    })
    assert malformed.status_code == 422

    oversized = client.post('/api/v1/assistant/chat', headers=headers, json={
        'messages': [{'role': 'user', 'content': 'x' * 2000}, {'role': 'assistant', 'content': 'y' * 2000}] * 3
        + [{'role': 'user', 'content': 'z' * 2000}],
    })
    assert oversized.status_code == 422


def test_assistant_tools_reuse_pf_os_results_and_enforce_household_scope(assistant_context, monkeypatch):
    client, engine = assistant_context
    owner_headers = register(client, 'assistant-owner@example.com')
    owner_id = client.get('/api/v1/auth/me', headers=owner_headers).json()['id']
    category_id, goal_id = add_financial_fixtures(engine, owner_id)

    baseline_summary = client.get(
        f'/api/v1/assistant/spending-summary?category_id={category_id}&history_months=6',
        headers=owner_headers,
    )
    assert baseline_summary.status_code == 200, baseline_summary.text
    scenario_request = {
        'category_id': str(category_id), 'goal_id': str(goal_id),
        'monthly_reduction': 100, 'duration_months': 12, 'history_months': 6,
    }
    baseline_scenario = client.post('/api/v1/assistant/scenario', headers=owner_headers, json=scenario_request)
    assert baseline_scenario.status_code == 200, baseline_scenario.text

    calls = []
    def fake_local_turn(_model, messages, _tools):
        calls.append(messages[-1])
        if len(calls) == 1:
            return {'role': 'assistant', 'content': '', 'tool_calls': [{
                'function': {'name': 'run_goal_scenario', 'arguments': {
                    'category_name': 'Shopping', 'goal_name': 'Home purchase',
                    'monthly_reduction': 100, 'duration_months': 12, 'history_months': 6,
                }},
            }]}
        return {'role': 'assistant', 'content': 'PFOS calculated the requested scenario.', 'tool_calls': []}

    monkeypatch.setattr(main, 'chat_turn_with_ollama', fake_local_turn)
    request = {'messages': [{'role': 'user', 'content': 'What if I reduce Shopping by $100 for 12 months for Home purchase?'}]}
    response = client.post('/api/v1/assistant/chat', headers=owner_headers, json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['financial_result']['type'] == 'goal_scenario'
    assert {key: value for key, value in body['financial_result'].items() if key != 'type'} == baseline_scenario.json()

    summary_calls = []
    def fake_summary_turn(_model, messages, _tools):
        summary_calls.append(messages[-1])
        if len(summary_calls) == 1:
            return {'role': 'assistant', 'content': '', 'tool_calls': [{
                'function': {'name': 'get_spending_summary', 'arguments': {'category_name': 'Shopping', 'history_months': 6}},
            }]}
        return {'role': 'assistant', 'content': 'PFOS summarized the requested category.', 'tool_calls': []}

    monkeypatch.setattr(main, 'chat_turn_with_ollama', fake_summary_turn)
    summary_response = client.post('/api/v1/assistant/chat', headers=owner_headers, json={
        'messages': [{'role': 'user', 'content': 'How much did I spend in Shopping?'}],
    })
    assert summary_response.status_code == 200, summary_response.text
    summary_result = summary_response.json()['financial_result']
    assert summary_result['type'] == 'spending_summary'
    assert {key: value for key, value in summary_result.items() if key != 'type'} == baseline_summary.json()

    # A different authenticated household cannot resolve the first user's labels or see their results.
    other_headers = register(client, 'assistant-other@example.com')
    other_calls = []
    def fake_other_turn(_model, messages, _tools):
        other_calls.append(messages[-1])
        if len(other_calls) == 1:
            return {'role': 'assistant', 'content': '', 'tool_calls': [{
                'function': {'name': 'get_spending_summary', 'arguments': {'category_name': 'Shopping'}},
            }]}
        return {'role': 'assistant', 'content': 'I could not find that category in this household.', 'tool_calls': []}

    monkeypatch.setattr(main, 'chat_turn_with_ollama', fake_other_turn)
    isolated = client.post('/api/v1/assistant/chat', headers=other_headers, json={
        'messages': [{'role': 'user', 'content': 'Summarize Shopping spending.'}],
    })
    assert isolated.status_code == 200, isolated.text
    tool_result = other_calls[1]
    assert tool_result['role'] == 'tool'
    assert 'category_not_found' in tool_result['content']
    assert 'total_spending' not in tool_result['content']


def test_model_tool_arguments_are_validated_and_unknown_tools_are_rejected(assistant_context, monkeypatch):
    client, engine = assistant_context
    headers = register(client, 'assistant-tools@example.com')
    owner_id = client.get('/api/v1/auth/me', headers=headers).json()['id']
    add_financial_fixtures(engine, owner_id)
    tool_messages = []
    tool_turns = 0

    def invalid_amount_turn(_model, messages, _tools):
        nonlocal tool_turns
        tool_turns += 1
        if tool_turns == 1:
            return {'role': 'assistant', 'content': '', 'tool_calls': [{
                'function': {'name': 'run_goal_scenario', 'arguments': {
                    'category_name': 'Shopping', 'goal_name': 'Home purchase',
                    'monthly_reduction': 100001, 'duration_months': 12,
                }},
            }]}
        tool_messages.append(messages[-1])
        return {'role': 'assistant', 'content': 'Please choose a valid reduction amount.', 'tool_calls': []}

    monkeypatch.setattr(main, 'chat_turn_with_ollama', invalid_amount_turn)
    response = client.post('/api/v1/assistant/chat', headers=headers, json={
        'messages': [{'role': 'user', 'content': 'Run a scenario.'}],
    })
    assert response.status_code == 200, response.text
    assert tool_messages[0]['role'] == 'tool'
    assert 'monthly_reduction_out_of_range' in tool_messages[0]['content']

    def unknown_tool(*_args):
        return {'role': 'assistant', 'content': '', 'tool_calls': [{
            'function': {'name': 'delete_transactions', 'arguments': {}},
        }]}

    monkeypatch.setattr(main, 'chat_turn_with_ollama', unknown_tool)
    rejected = client.post('/api/v1/assistant/chat', headers=headers, json={
        'messages': [{'role': 'user', 'content': 'Please change my data.'}],
    })
    assert rejected.status_code == 503
    assert rejected.json()['detail'] == 'ollama_unavailable'


def test_model_unavailable_returns_error_without_cloud_fallback(assistant_context, monkeypatch):
    client, _engine = assistant_context
    headers = register(client, 'assistant-offline@example.com')
    calls = []

    def unavailable(*_args):
        calls.append('local')
        raise OllamaUnavailable('model_unavailable')

    monkeypatch.setattr(main, 'chat_turn_with_ollama', unavailable)
    response = client.post('/api/v1/assistant/chat', headers=headers, json={
        'messages': [{'role': 'user', 'content': 'Explain my spending.'}],
    })
    assert response.status_code == 503
    assert response.json()['detail'] == 'ollama_model_unavailable'
    assert calls == ['local']


def test_ollama_status_is_disabled_or_unconfigured_without_network_access():
    assert get_ollama_status(False, 'qwen2.5:7b')['reason'] == 'disabled'
    assert get_ollama_status(True, None)['reason'] == 'model_not_configured'

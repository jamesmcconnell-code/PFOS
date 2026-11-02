"""Small, local PFOS help excerpts used to ground optional assistant answers."""

import re
from typing import Any


HELP_TOPICS = (
    {
        "title": "Understanding Free Spending",
        "content": "Free spending is paycheck income minus the expenses included in the selected Available Cash period. It describes the period plan, not a bank-account balance. Check the period dates and expense inputs when the number does not match your expectation.",
        "keywords": ("free spending", "available cash", "left over", "leftover", "safe to spend", "period cash", "planner amount"),
    },
    {
        "title": "Understanding Rolling Available Cash",
        "content": "Rolling available cash carries completed-period free spending forward, adds or subtracts manual adjustments, and accounts for planner-only goal sweeps above the checking ceiling. Free spending in the open period remains pending until that period closes. This is a planner estimate, not a bank balance.",
        "keywords": ("rolling cash", "rolling available cash", "carryover", "carry over", "running history", "adjustment", "goal sweep"),
    },
    {
        "title": "Using Savings What If",
        "content": "The Savings What If control changes the estimated automated-savings amount for the Available Cash view. PFOS uses imported automated savings as a 30% baseline and recalculates the hypothetical savings amount. It does not edit saved savings rules.",
        "keywords": ("savings what if", "savings rate", "automated savings", "savings slider", "change savings", "savings rules"),
    },
    {
        "title": "Reviewing Transactions",
        "content": "Transactions lets users search and filter imported or manually entered activity, review dates, accounts, categories, tags, and details, and make supported corrections. Imported transaction history is retained for reports and planning.",
        "keywords": ("transactions", "transaction", "search transaction", "filter transaction", "edit transaction", "categorize"),
    },
    {
        "title": "Reviewing Category Spending",
        "content": "Category Tracker summarizes categorized activity over a date range and lets users open the transactions behind a category total. Totals can include split allocations. Check the selected dates and category assignment when investigating a total.",
        "keywords": ("category tracker", "category spending", "spending category", "category total", "shopping", "groceries", "dining", "travel"),
    },
    {
        "title": "Creating and Reviewing Goals",
        "content": "Goals track a name, target amount, current amount, target date, and optionally a funding account. PFOS forecasting estimates progress from the current savings pace and goal priority. A forecast is an estimate and does not change accounts or transactions.",
        "keywords": ("goal", "goals", "savings goal", "target amount", "goal date", "house goal", "home goal", "goal priority"),
    },
    {
        "title": "Managing Accounts",
        "content": "Accounts shows accounts available in the household view, their types, balances, and connection details. Account roles and savings settings affect how PFOS groups balances and calculates planner or report values.",
        "keywords": ("account", "accounts", "balance", "savings account", "account type"),
    },
    {
        "title": "Connecting a Financial Institution",
        "content": "Connected Sources manages data connections. Follow the in-app flow for the institution, review selected accounts, and complete any reconnection request shown by PFOS. PFOS does not need a bank password in chat; never enter credentials there.",
        "keywords": ("plaid", "connect bank", "connect account", "institution", "connection", "reconnect"),
    },
    {
        "title": "Switching the Household View",
        "content": "Where supported, the Financial View selector switches between the joint household view and a household member's individual view. The active view changes which financial activity is included on supported planning and reporting screens.",
        "keywords": ("household", "joint view", "individual view", "member view", "switch view", "financial view"),
    },
)


def relevant_help_excerpts(messages: list[dict[str, Any]], limit: int = 3) -> list[str]:
    """Select a few server-owned excerpts using recent conversational context."""
    recent_text = " ".join(str(message.get("content", "")) for message in messages[-6:]).lower()
    normalized = re.sub(r"[^a-z0-9\s]", " ", recent_text)
    words = {word for word in normalized.split() if len(word) > 2}
    ranked: list[tuple[int, dict[str, str]]] = []

    for topic in HELP_TOPICS:
        score = 0
        for keyword in topic["keywords"]:
            if keyword in normalized:
                score += 4 if " " in keyword else 2
            elif any(part in words for part in keyword.split() if len(part) > 2):
                score += 1
        if score:
            ranked.append((score, topic))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [f"{topic['title']}: {topic['content']}" for _, topic in ranked[:limit]]

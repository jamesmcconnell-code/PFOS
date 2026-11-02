from datetime import date


def add_months(value: date, months: int) -> date:
    """Add calendar months while keeping the day in range for the destination month."""
    absolute_month = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute_month, 12)
    month = month_index + 1
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    day = min(value.day, (next_month - date.resolution).day)
    return date(year, month, day)


def project_goal_months(
    goals,
    goal_id,
    monthly_savings: float,
    one_time_sweep: float,
    extra_monthly_savings: float = 0.0,
    extra_months: int = 0,
    max_months: int = 1200,
):
    """Project goal progress in priority order using monthly contributions, without returns.

    Scenario savings are explicitly directed to the chosen goal. Existing cash-flow
    savings continue to follow the household's goal priority order.
    """
    remaining = {
        goal.id: max(0.0, float(goal.target_amount) - float(goal.current_amount))
        for goal in goals
    }
    if goal_id not in remaining:
        return None, 0.0
    if remaining[goal_id] <= 0.005:
        return 0, 0.0

    sweep_remaining = max(0.0, one_time_sweep)
    for goal in goals:
        applied = min(remaining[goal.id], sweep_remaining)
        remaining[goal.id] -= applied
        sweep_remaining -= applied
        if sweep_remaining <= 0.005:
            break
    if remaining[goal_id] <= 0.005:
        return 0, 0.0

    base_monthly = max(0.0, monthly_savings)
    extra_monthly = max(0.0, extra_monthly_savings)
    extra_applied = 0.0
    for month in range(1, max_months + 1):
        available = base_monthly
        for goal in goals:
            if available <= 0.005:
                break
            applied = min(remaining[goal.id], available)
            remaining[goal.id] -= applied
            available -= applied

        if month <= extra_months and remaining[goal_id] > 0.005:
            applied = min(remaining[goal_id], extra_monthly)
            remaining[goal_id] -= applied
            extra_applied += applied

        if remaining[goal_id] <= 0.005:
            return month, round(extra_applied, 2)

    return None, round(extra_applied, 2)

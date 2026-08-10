"""Pure payroll schedule helpers; calculation integration follows in a later step."""
from datetime import date, timedelta

def semimonthly_period_bounds(value: date) -> tuple[date,date]:
    """Return inclusive start and exclusive end for the half-month containing value."""
    if value.day<=15: return value.replace(day=1),value.replace(day=16)
    start=value.replace(day=16)
    return start,(start.replace(day=28)+timedelta(days=4)).replace(day=1)

def biweekly_period_bounds(anchor_start: date, value: date) -> tuple[date,date]:
    """Return inclusive start and exclusive end of the 14-day period containing value."""
    offset=(value-anchor_start).days//14; start=anchor_start+timedelta(days=offset*14)
    return start,start+timedelta(days=14)

def period_bounds(period_type: str, value: date, biweekly_anchor_start: date|None=None) -> tuple[date,date]:
    if period_type in {'paycheck','semimonthly'}: return semimonthly_period_bounds(value)
    if period_type=='biweekly':
        if not biweekly_anchor_start: raise ValueError('Biweekly schedule requires an anchor start date')
        return biweekly_period_bounds(biweekly_anchor_start,value)
    if period_type=='monthly':
        start=value.replace(day=1)
        return start,(start.replace(day=28)+timedelta(days=4)).replace(day=1)
    raise ValueError('Unsupported planner period type')

def adjacent_period_start(period_type: str, start: date, direction: int, biweekly_anchor_start: date|None=None) -> date:
    if direction not in {-1,1}: raise ValueError('Direction must be -1 or 1')
    if period_type in {'paycheck','semimonthly'}:
        if direction==1: return start.replace(day=16) if start.day==1 else (start.replace(day=28)+timedelta(days=4)).replace(day=1)
        return (start-timedelta(days=1)).replace(day=16) if start.day==1 else start.replace(day=1)
    if period_type=='biweekly':
        if not biweekly_anchor_start: raise ValueError('Biweekly schedule requires an anchor start date')
        return start+timedelta(days=14*direction)
    if period_type=='monthly':
        if direction==1: return (start.replace(day=28)+timedelta(days=4)).replace(day=1)
        return (start-timedelta(days=1)).replace(day=1)
    raise ValueError('Unsupported planner period type')

def periods_per_year(period_type: str) -> int:
    if period_type in {'paycheck','semimonthly'}: return 24
    if period_type=='biweekly': return 26
    if period_type=='monthly': return 12
    raise ValueError('Unsupported planner period type')

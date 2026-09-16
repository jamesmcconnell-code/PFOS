import {describe, expect, it} from 'vitest';
import {plannerSummary} from './planner-summary';

describe('command center planner summary', () => {
  it('uses allocated income and net planner expenses, including anticipated costs, debt, settlements and refund credits', () => {
    const data = {paycheck_amount: 3000, automated_savings_amount: 600, total_period_expenses: 1700,
      paycheck_sources: [{id:'pay', amount:2500}, {id:'anticipated-pay',amount:500}],
      automated_savings_sources: [{id:'savings',amount:600}],
      expense_input_sources: [{id:'rent',amount:1000,period_amount:1000}, {id:'annual',amount:1200,period_amount:100}],
      debt_line_items: [{id:'purchase',amount:300}], household_settlement_sources: [{id:'settlement',amount:100}],
      anticipated_expense_sources: [{id:'expected',period_amount:250}],
      refunds: [{id:'included',amount:50,refund_included:true},{id:'excluded',amount:900,refund_included:false}]};
    const result=plannerSummary(data);
    expect(result.income).toBe(3000);
    expect(result.expenses).toBe(1700);
    expect(result.spendingCashFlow).toBe(1300);
    expect(result.automatedSavings).toBe(600);
    expect(result.savings).toBe(1900);
    expect(result.savingsRate).toBe(52.8);
    for (const [metric,total] of Object.entries({income:3000,expenses:1700,automated_savings:600,spending_cash_flow:1300}))
      expect(result.sources.reduce((sum,row)=>sum+row[metric],0)).toBe(total);
    expect(new Set(result.sources.map(row=>row.account_id)).size).toBe(result.sources.length);
  });
  it('never falls back to legacy dashboard figures or treats refunds as income', () => {
    const result=plannerSummary({paycheck_amount:0,automated_savings_amount:0,total_period_expenses:-25,
      monthly_income:9999,monthly_savings:9999,refunds:[{id:'refund',amount:25,refund_included:true}]});
    expect(result.income).toBe(0);
    expect(result.spendingCashFlow).toBe(25);
    expect(result.savingsRate).toBe(0);
    expect(result.sources[0].income).toBe(0);
    expect(result.sources[0].expenses).toBe(-25);
  });
});

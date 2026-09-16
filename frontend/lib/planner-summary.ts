/** Shared presentation calculations for Available Cash and its dashboard summary. */
export function plannerSummary(data: any) {
  const income = Number(data?.paycheck_amount || 0);
  const expenses = Number(data?.total_period_expenses || 0);
  const automatedSavings = Number(data?.automated_savings_amount || 0);
  const spendingCashFlow = income - expenses;
  const savings = spendingCashFlow + automatedSavings;
  const totalIncome = income + automatedSavings;
  const sources: any[] = [];
  function add(items: any[], kind: string, metric: string, amount: (item: any) => number) {
    for (const [index, item] of (items || []).entries()) {
      const value = amount(item);
      if (!value) continue;
      sources.push({account_id: `${kind}:${item.id || item.rule_id || index}:${index}`,
        account_name: item.account_name || 'Planner allocation',
        source_name: `${item.description || item.display_name || kind}${item.type ? ` · ${item.type}` : ''}`,
        income: 0, expenses: 0, automated_savings: 0, spending_cash_flow: 0,
        [metric]: value, ...(metric === 'income' ? {spending_cash_flow: value} :
          metric === 'expenses' ? {spending_cash_flow: -value} : {})});
    }
  }
  add(data?.paycheck_sources, 'Income', 'income', item => Number(item.amount));
  add(data?.automated_savings_sources, 'Automated savings', 'automated_savings', item => Number(item.amount));
  for (const key of ['expense_input_sources', 'debt_line_items', 'household_settlement_sources', 'anticipated_expense_sources']) {
    add(data?.[key], key, 'expenses', item => Number(item.period_amount ?? item.amount));
  }
  add(data?.refunds?.filter((item: any) => item.refund_included), 'Refund', 'expenses', item => -Number(item.amount));
  return {income, expenses, automatedSavings, spendingCashFlow, savings,
    savingsRate: totalIncome ? Math.round(savings / totalIncome * 1000) / 10 : 0, sources};
}

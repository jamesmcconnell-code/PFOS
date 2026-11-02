export type AssistantHelpTopic = {
  id: string;
  title: string;
  content: string;
  href: string;
  keywords: string[];
};

// Maintained, local PFOS product guidance. Questions are matched in the browser;
// this content and the user's help question are not sent to an AI provider.
export const assistantHelpTopics: AssistantHelpTopic[] = [
  {
    id: 'free-spending',
    title: 'Understanding Free Spending',
    content: 'Free spending is paycheck income minus the expenses included in the selected Available Cash period. It describes the period plan; it is not a bank-account balance. Check the period dates and the expense inputs when the number does not match your expectation.',
    href: '/available-cash',
    keywords: ['free spending', 'available cash', 'left over', 'leftover', 'safe to spend', 'period cash', 'planner amount'],
  },
  {
    id: 'rolling-cash',
    title: 'Understanding Rolling Available Cash',
    content: 'Rolling available cash carries completed-period free spending forward, adds or subtracts manual adjustments, and accounts for planner-only goal sweeps above the checking ceiling. Free spending in the currently open period remains pending until that period closes. This is a planner estimate, not a bank balance.',
    href: '/available-cash',
    keywords: ['rolling cash', 'rolling available cash', 'carryover', 'carry over', 'running history', 'adjustment', 'goal sweep'],
  },
  {
    id: 'savings-what-if',
    title: 'Using Savings What If',
    content: 'The Savings What If control changes the estimated automated-savings amount for the Available Cash view. PFOS uses imported automated savings as a 30% baseline and recalculates the hypothetical savings amount. Free Spending remains paycheck amount minus period expenses; the what-if control does not edit your saved savings rules.',
    href: '/available-cash',
    keywords: ['savings what if', 'savings rate', 'automated savings', 'savings slider', 'change savings', 'savings rules'],
  },
  {
    id: 'transactions',
    title: 'Reviewing Transactions',
    content: 'Use Transactions to search and filter imported or manually entered activity. You can review dates, accounts, categories, tags, and transaction details, and make supported corrections from the transaction list. PFOS retains imported transaction history for reports and planning.',
    href: '/transactions',
    keywords: ['transactions', 'transaction', 'search transaction', 'filter transaction', 'edit transaction', 'categorize', 'category'],
  },
  {
    id: 'categories',
    title: 'Reviewing Category Spending',
    content: 'Category Tracker summarizes categorized activity over a date range and lets you open the transactions behind a category total. Category totals can include split allocations. Check the selected dates and category assignment when investigating a total.',
    href: '/category-tracker',
    keywords: ['category tracker', 'category spending', 'spending category', 'category total', 'shopping', 'groceries', 'spend by category'],
  },
  {
    id: 'goals',
    title: 'Creating and Reviewing Goals',
    content: 'Goals track a name, target amount, current amount, target date, and optionally a funding account. PFOS forecasting estimates progress from the current savings pace and goal priority. A forecast is a planning estimate and does not make changes to accounts or transactions.',
    href: '/goals',
    keywords: ['goal', 'goals', 'savings goal', 'target amount', 'goal date', 'house goal', 'home goal', 'goal priority'],
  },
  {
    id: 'accounts',
    title: 'Managing Accounts',
    content: 'Accounts shows the accounts available in your household view, their types, balances, and connection details. Account roles and savings settings affect how PFOS groups balances and calculates planner or report values.',
    href: '/accounts',
    keywords: ['account', 'accounts', 'balance', 'savings account', 'account type'],
  },
  {
    id: 'plaid',
    title: 'Connecting a Financial Institution',
    content: 'Open Connected Sources to manage data connections. Follow the in-app flow for the institution, review the accounts selected for sharing, and complete any reconnection request shown by PFOS. PFOS does not need your bank password in chat; never enter credentials here.',
    href: '/connections',
    keywords: ['plaid', 'connect bank', 'connect account', 'institution', 'connection', 'bank connection', 'reconnect'],
  },
  {
    id: 'household-view',
    title: 'Switching the Household View',
    content: 'Where supported, use the Financial View selector in the navigation to switch between the joint household view and a household member’s individual view. The active view changes which financial activity is included on supported planning and reporting screens.',
    href: '/dashboard',
    keywords: ['household', 'joint view', 'individual view', 'member view', 'switch view', 'financial view'],
  },
];

export function findAssistantHelp(question: string, pathname = ''): AssistantHelpTopic | undefined {
  const normalized = question.toLowerCase().replace(/[^a-z0-9\s]/g, ' ');
  const words = new Set(normalized.split(/\s+/).filter((word) => word.length > 2));
  if (!words.size) return undefined;

  const pageHint = pathname.replace(/^\//, '').split('/')[0];
  let best: { topic: AssistantHelpTopic; score: number } | undefined;
  for (const topic of assistantHelpTopics) {
    let score = 0;
    for (const keyword of topic.keywords) {
      const normalizedKeyword = keyword.toLowerCase();
      if (normalized.includes(normalizedKeyword)) score += normalizedKeyword.includes(' ') ? 4 : 2;
      else if (normalizedKeyword.split(/\s+/).some((part) => part.length > 2 && words.has(part))) score += 1;
    }
    if (pageHint && topic.href === `/${pageHint}` && score > 0) score += 0.25;
    if (!best || score > best.score) best = { topic, score };
  }
  return best && best.score >= 2 ? best.topic : undefined;
}

export function suggestedAssistantTopics(pathname: string): AssistantHelpTopic[] {
  const pageHint = pathname.replace(/^\//, '').split('/')[0];
  const pageTopics = assistantHelpTopics.filter((topic) => topic.href === `/${pageHint}`);
  const fallback = assistantHelpTopics.filter((topic) => ['free-spending', 'transactions', 'goals'].includes(topic.id));
  return (pageTopics.length ? pageTopics : fallback).slice(0, 3);
}

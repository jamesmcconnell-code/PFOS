# PFOS 0.1.6

File → Backup and Migration Guide explains backup contents, restoring onto another
Mac, destination Plaid settings, and recovery copies. Successful restores open the
guide with sign-in and bank-connection next steps; signed-in users can see current
credential and reauthorization needs. Settings → Plaid also links to the guide.

Backup/restore dialogs clarify that the archive includes financial data and token
decryption keys, excludes installation Plaid developer settings, and replaces rather
than merges destination data. The backup format and database schema are unchanged.

See [backup guidance](DESKTOP-BACKUPS.md). Live Plaid validation, signing/notarization,
and clean-Mac release testing remain outstanding. This Intel build is unsigned.

# PFOS 0.1.5

Plaid settings now review credential replacement and removal before applying them.
Removing installation credentials disables Plaid and invalidates pending Link sessions
while preserving imported accounts, transactions, and encrypted bank tokens. Invalid
replacement credentials leave the existing keys unchanged.

Connected Sources → Manage now offers Reauthorize bank for matching Plaid credentials.
Hosted Link update mode repairs authorization without replacing accounts, transaction
history, bank tokens, or the sync cursor. Sources tied to another Plaid identity display
an explanation and a separate-connection option with an overlap warning.

The existing database schema is unchanged. The Intel installer remains unsigned and
unnotarized. Automated tests use synthetic credentials; live reauthorization still
requires validation with your own Plaid account. See [Plaid setup](DESKTOP-PLAID.md).

# PFOS 0.1.4

Desktop bank linking now opens Plaid Hosted Link in the default browser. Returning
through `pfos://plaid-complete` brings PFOS to Connected Sources; PFOS verifies the
session with Plaid before exchanging and saving its bank token locally. Pending
sessions survive app restarts, with Resume, Check connection, and Cancel controls.
Repeated checks do not create duplicate sources. No shared Plaid keys are supplied.

Add `pfos://plaid-complete` to allowed Hosted Link completion redirect URIs in your
own Plaid dashboard. See [Plaid setup and testing](DESKTOP-PLAID.md). Step 5's desktop
flow is implemented and tested with synthetic/mocked responses; live Sandbox OAuth
and real-bank authorization still require validation with your own Plaid account.

This release adds a local database migration for encrypted pending Link sessions.
The desktop creates a pre-upgrade backup using its existing migration process.
The Intel macOS installer remains unsigned and unnotarized.

# PFOS 0.1.3

Settings → Plaid supports per-installation Client ID, secret, environment, connection
validation, and saving with macOS Keychain protection. The local API uses only that
installation’s credentials and disables Plaid when they are absent. Shared developer
credentials are never supplied by the desktop app. See [Plaid setup](DESKTOP-PLAID.md).

This implements steps 1–4. Desktop bank authorization/OAuth work remains for step 5;
credential validation is not an end-to-end bank connection test.

# PFOS 0.1.2

Settings → Visual preferences now includes **Blur financial numbers**. It immediately
blurs monetary values, percentages, crypto quantities, chart values, and numeric input
contents while retaining labels and dates. Amounts in native dropdown choices are
replaced with dots because those controls cannot blur only part of their text.

The preference is saved on this device and applied before page content is displayed.
It remains enabled across navigation and restarts, and applies to both standard and
Simple Mode. Turning it off reveals values again. This is a visual privacy feature;
calculations, stored data, accessibility text, and exported files are unchanged.

# PFOS 0.1.1

The Financial command center's This month card now reads Available Cash's monthly
planner results for the selected household/user, instead of the older posted-
transaction dashboard totals. It includes planner income timing, anticipated expenses,
proration, debt purchases, settlements, and included refund credits.

- Income matches the planner's paycheck total.
- Expenses match Total Period Expenses, including refund offsets.
- Automated savings uses actual automated savings, not the what-if slider.
- Spending cash flow matches Free Spending: paycheck total minus period expenses.
- Monthly savings equals Free Spending plus actual automated savings.
- Savings rate divides those savings by paycheck total plus automated savings.
- Source lists come from the planner's contributing items.

The old Last 30 days selector is replaced by the calendar-month planner summary.
View monthly planner opens Available Cash with the same month and selected user.
The card refreshes on focus, user changes, and every 30 seconds; failed refreshes
show an error rather than retaining stale planner figures.

Rebuild the desktop interface and install the 0.1.1 DMG to update an installed copy.
No database migration is required for this change.

# Per-installation Plaid: desktop setup

In the macOS app, sign in as a household administrator and open **Settings → Plaid**.
In your own Plaid dashboard, add `pfos://plaid-complete` to the allowed Hosted Link
completion redirect URIs. Enter your own Plaid Client ID, secret, and Sandbox or
Production environment in PFOS.
**Test connection** checks whether those credentials can create a Hosted Link for
Transactions without saving them. **Validate and save** validates, protects the credentials
with macOS Keychain, and immediately updates the local API. No bank is linked by
this test; Production requires access granted by Plaid.

The secret field clears after saving. Leave it blank to reuse the saved secret only
when the Client ID and environment match. A new client or environment needs its own
secret. Credentials are never returned to the interface or saved in browser storage.

Electron safeStorage encrypts the credentials using macOS Keychain protection. The
ciphertext lives in `~/Library/Application Support/PFOS/plaid-credentials.json`,
outside the household backup directory, with owner-only file permissions. No Plaid
credentials are included in the installer. Missing or unreadable credentials disable
Plaid; the desktop never falls back to environment or hosted-server credentials.
Manual entry, imported data, and local planning remain available.

Electron passes decrypted credentials to its private Python process over stdin at
startup. Subsequent changes use a management-authenticated local endpoint unavailable
to the renderer. Link-token creation, token exchange, and transaction sync use the
same installation configuration. Newly linked connections record their Plaid client
and environment; desktop sync refuses tokens with a missing or different identity.
Existing connections may therefore need relinking. Server deployments retain their
existing environment configuration.

## Connecting a bank (step 5 implementation)

1. Open **Connected Sources → Connect a bank with Plaid**. PFOS opens the short-lived
   Plaid Hosted Link in your default browser. Bank OAuth stays in that browser.
2. Complete authorization. Accept the browser's prompt to open PFOS when shown, or
   return to PFOS manually. Keep PFOS open while linking.
3. PFOS checks the session directly with Plaid and saves the resulting bank access
   token encrypted in the local database. A callback alone never creates a connection.
4. Select **Sync** beside the connected bank to load balances and transactions.

PFOS registers its `pfos` URL scheme when the installed app is launched normally.
The completion URI is a notification only, with no public token or account data in
its URL. PFOS accepts only the fixed completion route. Browser launch URLs are
restricted to HTTPS Hosted Link URLs on `secure.plaid.com`.

**Resume in browser** reopens an existing pending session. **Check connection**
retrieves a result manually. PFOS polls while Connected Sources is visible and the
browser link is current, and checks again on return. **Cancel linking** stops PFOS
from completing that session; also close the browser tab to stop bank authorization.
Cancellation is not bank-side consent revocation.

Pending sessions are encrypted in local SQLite, associated with the initiating
PFOS user and Plaid credentials, and survive navigation and app restarts. The browser
link lasts 30 minutes; PFOS can recover completed results for up to six hours from
session creation. After that, start again. Changing credentials invalidates pending
sessions. Completed/cancelled sessions discard their Link tokens and browser URLs.
No public webhook, hosted PFOS server, or embedded bank-login window is required.

The database upgrade adds `plaid_link_sessions`; the existing desktop migration
mechanism creates a pre-upgrade backup. Application updates retain the local profile
and its protected credentials.

## Verification and remaining work

Automated tests cover the UI/browser handoff, completion routing, encrypted pending
sessions, user isolation, cancellation, expiration, retries, credential changes,
idempotent result processing, token exchange, and initial balance sync. Tests use
synthetic credentials and mocked Plaid responses. Actual Sandbox OAuth and Production
bank authorization have **not** been performed against a live Plaid account.

For a live Sandbox check, use your own Sandbox credentials, select **Platypus OAuth
Bank** in Hosted Link, finish its sample OAuth flow, return to PFOS, and sync. Also
check cancellation and closing/reopening PFOS during a pending session. Production
requires the products and institution/OAuth access enabled for that person's Plaid
account; validate those separately before distributing the app as bank-ready.

Step 7 is implemented: see [backup and migration guidance](DESKTOP-BACKUPS.md), also
available through File → Backup and Migration Guide in the app. The current installer is still unsigned and
unnotarized; signing and clean-Mac verification remain release work.

Implementation references: [Hosted Link](https://plaid.com/docs/link/hosted-link/),
[Link API](https://plaid.com/docs/api/link/), and
[OAuth testing](https://plaid.com/docs/link/oauth/#testing-oauth).

Validation includes mocked Plaid responses and synthetic credentials; no real bank
accounts or developer credentials are used by automated tests.


## Replacing, removing, and reauthorizing (step 6)

In **Settings → Plaid**, enter replacement credentials, select **Review replacement**,
read the impact, then choose **Validate and replace**. Failed validation keeps the
previous saved credentials. Rotating the secret for the same Client ID/environment
preserves existing bank tokens. Changing the Client ID or environment disables sync
for sources associated with the old identity. Pending Link sessions are invalidated
when credentials change. Backup/restore waits until the credential operation finishes.

**Remove Plaid credentials → Confirm removal** deletes this profile's encrypted
Plaid Client ID/secret file and clears them from the local API. This also works when
the stored credentials cannot be unlocked. It preserves accounts, transactions,
connection history, and encrypted bank tokens. It does not revoke consent at Plaid
or at a bank. Removing PFOS credentials is separate from the existing **Unlink and
delete data** action. An active Plaid request may finish before removal takes effect;
a paginated sync cannot issue another request with the removed credentials.

In **Connected Sources → Manage**, **Reauthorize bank** uses Hosted Link update mode
for an existing token belonging to the current Client ID/environment. PFOS checks
Plaid's session success and the Item's health before marking the source active.
The token, local account IDs, history, and sync cursor are retained; there is no
public-token exchange for update mode. A bank login-required error during sync
shows a reauthorization notice and disables the normal Sync button until repaired.

When a source belongs to another or unknown Plaid identity, or its token is invalid,
restore the original credentials or choose **Connect as separate source**. PFOS
preserves the old source and history. A separate source may import overlapping
accounts/transactions; review it before syncing. This release does not automatically
merge account IDs or transaction histories across different Plaid accounts.

Verification covers replacement rejection, removal, session invalidation, cross-client
isolation, update-mode success/failure, unchanged financial records, and sync pagination.
The macOS UI test uses real Keychain encryption with synthetic keys and mocked Plaid
responses. Live Sandbox/Production reauthorization still requires validation with your
own account.

Reference: [Plaid update mode](https://plaid.com/docs/link/update-mode/).

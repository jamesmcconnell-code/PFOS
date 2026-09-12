# PFOS desktop: window, bundled backend, and permanent storage (steps 2–4)

Electron now starts a self-contained Python API automatically, waits for it to become
ready, and connects the PFOS interface to its local port. Quitting PFOS shuts down
the API. Users do not need a Python installation to run the built backend.

The frontend still runs through Next.js during development. A signed, downloadable
installer containing the complete application remains a later step.

## Run the desktop app

With frontend/desktop dependencies installed and the backend bundle built:

```sh
npm run dev --prefix desktop
```

This starts Next.js on `http://localhost:3000`, then Electron and its bundled API.
There is **no separate API command**. The API selects an unused loopback port rather
than occupying port 8000 or attaching to another PFOS server.

If your frontend is already running on port 3000, use:

```sh
npm start --prefix desktop
```

That command starts Electron and its API only; it does not stop the separately
running frontend. `npm run dev` refuses an occupied frontend port.

Use **Command-Q** to quit PFOS or **Control-C** to stop the development launcher.
Both stop the owned API; the development launcher also stops its frontend. On
macOS, closing the window leaves the application and API running. Clicking the
Dock icon reopens the window.

A new local installation starts with an empty household database. Choose **New here?
Create an account** on the sign-in screen. Existing server data and server login
sessions are not automatically imported into this local installation.

To select another frontend origin:

```sh
PFOS_DESKTOP_URL=http://127.0.0.1:3000 npm start --prefix desktop
```

Only loopback HTTP origins are accepted. The bundled API automatically sets its CORS
origin to this value. Keep the same frontend origin to retain its browser login storage.

## Build the backend (developers / release machines)

Build on the target operating system and architecture with Python 3.12. Python is
needed **to build**, not to execute the resulting runtime. From the repository root
on macOS:

```sh
npm ci --prefix frontend
npm ci --prefix desktop
python3.12 -m venv desktop/.build/venv
desktop/.build/venv/bin/python -m pip install -r backend/requirements-desktop.txt
PFOS_BUILD_PYTHON="$PWD/desktop/.build/venv/bin/python" npm run build:backend --prefix desktop
```

`PFOS_BUILD_PYTHON` selects the build interpreter. The build fails with a clear message
if it is not Python 3.12. PyInstaller is pinned in `requirements-desktop.txt`.

The result is a **directory bundle**:

```text
desktop/resources/backend/
  build-info.json
  pfos-api/
    pfos-api             # pfos-api.exe on Windows
    _internal/           # Python runtime, libraries, migrations, CA certificates
```

Keep the executable and `_internal/` together. The macOS x86_64 bundle built during
this step is approximately 47 MB. It was copied to another directory and tested
without PATH, PYTHONPATH, system Python, Docker, or access to the source tree through
its working directory.

`backend.spec` explicitly includes application imports and migration source files.
It does not collect repository `.env` files, databases, or other household data.
Build output and installation secrets are ignored by Git.

For future installer packaging, copy the entire `desktop/resources/backend/`
directory to `<Electron resources>/backend/` outside the ASAR archive. The desktop
launcher already resolves that packaged path when `app.isPackaged` is true.
Code signing and installer production are not part of this step.

## Runtime ownership and storage

On macOS the desktop profile uses `~/Library/Application Support/PFOS/`. The bundled
API owns its `data/` subdirectory:

- `pfos.db`: SQLite household data, initialized using the existing migrations.
- `runtime.json`: stable, independently generated login and connector-encryption
  secrets, created with owner-only file permissions.
- `.backend.lock`: an OS lock that prevents two backends opening this folder at once.

The profile path is fixed independently of the application name, installation path,
and version. Replacing the app bundle keeps the database, secrets, financial settings,
and browser preferences in this profile. The existing step-3 location is retained.
Use **File → Show Data Folder…** to open the database directory in Finder.

Secrets are published atomically with owner-only permissions. A completed first launch
is recorded only after database initialization succeeds. An interrupted setup can retry
with the same secrets. Once initialized, a missing or empty database stops startup
instead of silently creating an empty household. Invalid secrets and unsupported storage
formats also stop startup without replacing the affected files. Existing step-3 profiles
are adopted with their original secrets after database validation.

Keep the database and its secrets together. Browser login and preferences are stored
elsewhere within the same Electron profile and require the same frontend origin across
launches. Deleting the profile removes local data; replacing the application bundle does
not. First-launch screens, backup/restore, and transfer of existing data remain later
steps. If an existing database has lost its secrets, startup refuses to generate keys.

Fresh databases are migrated automatically. An existing database at the current
revision is reopened. An older or unversioned database is refused with an explanation;
automatic upgrades of existing data will be added with the backup workflow. Server
`DATABASE_URL`, provider keys, `.env`, and Python search paths are not inherited by
the launched backend.

The local desktop browser session is separate from the earlier server-connected
shell session so old server tokens cannot be mistaken for local login credentials.

The API binds only to `127.0.0.1`. Each launch uses a new random capability delivered
through a private stdin pipe. Electron attaches it only to requests from the PFOS
window's trusted local frame, and only to that API. The renderer receives the public
API URL via a small read-only preload bridge, never the capability or filesystem access.
User authentication is still required for financial endpoints.

The launcher verifies a protected health endpoint before creating the app window.
It reports missing bundles, startup failures, timeouts, and unexpected API exits.
Normal quit closes the pipe and waits for graceful shutdown, with a bounded process
termination fallback. If the parent is killed, the API detects pipe closure and exits.

## Desktop window

- Resizable native window, full screen, zoom, copy/paste, native menus, and a PFOS icon.
- File shortcuts: Dashboard (**Command-1**), Accounts (**Command-2**), Transactions
  (**Command-3**), and CSV Import (**Command-I**).
- Reload (**Command-R**) and a retry screen when the frontend cannot be loaded.
- One PFOS instance per profile; reopening focuses or recreates the window.
- Renderer sandboxing, context isolation, and disabled Node.js access.
- Top-level navigation stays on the local frontend origin. HTTPS popup links open
  in the system browser; other popup protocols are blocked.
- Camera, microphone, notification, and similar permission requests are denied.
  Standard file inputs still support CSV selection.

`assets/icon.svg` is the editable icon source and `assets/icon.png` is used by Electron.
The launch scripts clear an inherited `ELECTRON_RUN_AS_NODE` flag from editor terminals.

## Verification

```sh
# Policy / supervisor unit tests
npm test --prefix desktop

# Real relocated backend: imports, persistence, shutdown, failure handling
npm run test:backend --prefix desktop

# Two complete Electron processes sharing a temporary profile
npm run test:storage --prefix desktop

# Electron window behavior with an isolated HTTP fixture
npm run test:smoke --prefix desktop

# With the real frontend already running: full bundled API and UI checks
PFOS_SMOKE_URL=http://localhost:3000 npm run test:bundled --prefix desktop
PFOS_SMOKE_URL=http://localhost:3000 npm run test:lifecycle --prefix desktop

# Existing financial regressions against migrated SQLite files
cd backend
python -m pytest -q --migrated-sqlite
```

The frozen-backend tests exercise relocation, first-run migration, authentication,
CSV deduplication, financial totals, restart persistence, exclusive ownership,
startup timeout, parent-process death, and unexpected exit reporting. They remove an
old runtime bundle, install a replacement in another resources directory, and verify
financial totals, settings, and secrets are retained. They also verify that a missing
initialized database is refused and can be reopened after its original file is restored.
This tests replacement at the current schema revision; installer upgrades and automatic
schema upgrades are not yet implemented.

The storage test quits Electron completely and starts a second process against the
same temporary profile and frontend origin. The saved login authenticates successfully
without signing in again, and a browser preference survives.

The bundled Electron test creates a temporary household, imports synthetic transactions,
and verifies the actual accounts, import, and dashboard pages. It also checks that
an unrelated window cannot use the private API. The lifecycle test exercises the
real application startup and confirms the API is stopped before quit completes.
These tests use temporary databases/profiles and no real credentials or financial data.
Electron tests require a graphical desktop environment and permission to bind local ports.

The source backend suite has 84 passing tests on Python 3.12. The frontend production
build also passes. Windows/ARM builds, remote bank OAuth, full installer execution,
Keychain-based secret storage, signing, and notarization have not been verified here.

Implementation references: [PyInstaller directory bundles](https://pyinstaller.org/en/stable/spec-files.html),
[Electron web requests](https://www.electronjs.org/docs/latest/api/web-request), and
[Electron security guidance](https://www.electronjs.org/docs/latest/tutorial/security).

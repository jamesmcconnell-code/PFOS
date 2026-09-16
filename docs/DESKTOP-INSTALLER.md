# PFOS macOS installer (step 8)

The current desktop build is **PFOS 0.1.6 for Intel Macs (x64)**.
Electron requires macOS 13 or newer for this build. Apple Silicon native builds and
Windows installers have not been built or tested.

Build output:

- `desktop/dist/PFOS-0.1.6-mac-x64.dmg`: drag-to-Applications installer, approximately 150 MB.
- `desktop/dist/PFOS-0.1.6-mac-x64.zip`: ZIP containing the same application, approximately 152 MB.
- `desktop/dist/mac/PFOS.app`: unpacked application.
- `desktop/dist/SHA256SUMS.txt`: SHA-256 checksums for the DMG and ZIP.

Open the DMG, drag **PFOS** onto **Applications**, eject the disk image, and open
PFOS from Applications. The app includes Electron, the built interface, Python,
and the local API. Users do not need npm, Python, Next.js, or Docker installed.
Existing local data remains under `~/Library/Application Support/PFOS/`; application
replacement does not remove that folder. Quit an existing PFOS instance before
replacing the application. The bundled interface needs loopback port 37841 available.

This is an **unsigned, unnotarized local test build**. A downloaded copy may be blocked
by macOS security checks. It has not been published or submitted to Apple. A public
release still needs an Apple Developer signing identity, signing of the embedded
Python runtime and Electron application, notarization, and verification on a clean Mac.
The current packaging configuration explicitly disables signing; do not treat a
successful local launch as proof of public distribution readiness.

## Rebuild

From the repository root, with dependencies installed and Python 3.12 build tools set up:

```sh
PFOS_BUILD_PYTHON=/absolute/path/to/python3.12 npm run build:backend --prefix desktop
npm run build:frontend --prefix desktop
npm run package:mac --prefix desktop
npm run test:packaged --prefix desktop
```

`package:mac` packages existing bundles and never publishes. Rebuild the backend and
interface after source changes. The pinned electron-builder 26.15.3 tool uses the
pinned Electron 44.3.0 installation. The configuration rejects incompatible backend
platform/architecture metadata and missing bundles. Only an explicit list of desktop
runtime files enters the ASAR archive; backend and interface bundles are copied into
application resources outside ASAR. Source tests, development dependencies, household
databases, backup archives, and repository `.env` files are not packaged.

For a relocated application test:

```sh
PFOS_PACKAGED_EXECUTABLE='/path/to/PFOS.app/Contents/MacOS/PFOS' npm run test:packaged --prefix desktop
```

The test launches the real packaged executable from a temporary working directory
with PATH empty and an isolated `--user-data-dir`. It creates a synthetic household,
verifies the accounts screen, quits, reopens, and verifies login/data persistence and
shutdown of both local servers. Chromium debugging is enabled only by this test's
launch arguments. Normal application launches do not enable it.

The generated DMG is also verified, mounted read-only, and its app copied to a
temporary installation location for the same test. Real household data and the user's
Applications folder are not modified during verification.

Packaging references: [electron-builder macOS targets](https://www.electron.build/v26/docs/mac/)
and [application contents](https://www.electron.build/v26/docs/contents/).

See [release notes](RELEASE-NOTES.md) for the planner-driven command center and financial privacy toggle.

See [per-installation Plaid setup](DESKTOP-PLAID.md) for local credentials and browser bank authorization and live-testing requirements.

See [backup and migration guidance](DESKTOP-BACKUPS.md) before moving a household to another Mac.

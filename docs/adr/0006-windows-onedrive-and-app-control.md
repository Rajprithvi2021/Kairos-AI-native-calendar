# ADR-0006: Building on Windows with OneDrive and Application Control

- **Status:** Accepted
- **Date:** 2026-11-25
- **Related:** [04 §10 Environment notes](../04-technical-architecture.md#10-environment-notes-windows-onedrive) · [ADR-0002](0002-python-ai-services-typescript-ui.md)

## Context

The prototype was built on Windows 11 Home, in a OneDrive-synced Desktop folder. Four problems came up:
- **Smart App Control / WDAC blocked unsigned native files.** SQLAlchemy 2.1's Cython accelerators (`*_cy.pyd`) failed to load with "An Application Control policy has blocked this file". So did the `.exe` launchers that uv generates for console scripts in the virtual environment.
- **OneDrive would sync regenerable files.** About 1 GB of `node_modules`, `.venv` and `.next`, plus a live SQLite database, would be uploaded and kept in sync.
- **Turbopack, the default bundler in Next.js 16, refuses files outside the project root,** and the dependency folders had to live outside it.
- **Security settings are off limits.** Changing them would weaken the user's protection and needs admin rights.

## Decision

1. **A pure-Python fallback for SQLAlchemy.** [_compat.py](../../services/api/app/_compat.py) is installed from `app/__init__.py` before any third-party import. On Windows it probes every SQLAlchemy `*_cy.pyd` with `ctypes.WinDLL`. If any is blocked, or `KAIROS_PURE_SQLALCHEMY=1` is set, it inserts a meta-path finder that loads the identical pure-Python `*_cy.py` twin of every accelerator, never mixing the two variants.
2. **No `.exe` launchers.** The scripts run every tool as `uv run --no-sync python -m <module>` ([run-api.ps1](../../scripts/run-api.ps1), [test.ps1](../../scripts/test.ps1)).
3. **Heavy folders live outside OneDrive.** Inside OneDrive, `.venv`, `.data` (SQLite), `node_modules` and `.next` live in `%LOCALAPPDATA%\kairos-ai-calendar` and are linked into the repo with NTFS junctions ([common.ps1](../../scripts/common.ps1), [setup.ps1](../../scripts/setup.ps1), [web-npm.ps1](../../scripts/web-npm.ps1)). `.next` sits beside `node_modules`, because compiled server chunks resolve packages from their real path.
4. **webpack instead of Turbopack.** Next.js runs with `--webpack` for both `dev` and `build`.
5. **No security exceptions.** Nothing is disabled or excluded.

## Consequences

**Positive**
- It works on a locked-down consumer PC without weakening its security.
- Behaviour is identical elsewhere. The shim does nothing off Windows, and bash twins of the scripts cover macOS and Linux; CI and Docker use plain Linux images.
- OneDrive stays small, and the database never syncs mid-write.

**Negative**
- SQLAlchemy runs its pure-Python code paths. That is slower, but negligible at prototype scale.
- npm packages must be added through `scripts\web-npm.ps1`, which syncs `package.json` and the lockfile to and from the cache folder.
- webpack builds are slower than Turbopack.
- An import-time shim is unusual. It has to follow SQLAlchemy's module layout (the `engine`, `sql` and `util` folders) across upgrades.

## Alternatives considered

| Option | Why not |
|---|---|
| Turn off Smart App Control, or add exclusions | Weakens the user's security and needs admin rights; off the table |
| Move the repository out of OneDrive | The user chose the Desktop location |
| Run everything in Docker | The Docker daemon wasn't running. [docker-compose.yml](../../infra/docker-compose.yml) remains an option (untested here) |
| Force a pure-Python SQLAlchemy install | Fragile across `uv sync` runs, because resolvers prefer the platform wheel; the shim keeps the normal lockfile |

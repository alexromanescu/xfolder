# Repository Guidelines

## Project Structure & Module Organization
Backend code resides in `backend/app`, with routers under `app/api`, similarity engines under `app/services`, and schemas under `app/models`. Tests mirror this tree inside `backend/tests`, so add new fixtures beside the logic they exercise. The React + Vite UI lives in `frontend/src`, organized by feature folders with shared widgets in `src/components` and hooks in `src/hooks`. Reference docs stay in `docs/`, and automation assets live at the root.

## Build, Test, and Development Commands
Use `make install-backend` and `make install-frontend` to install Python and npm dependencies. `make dev-backend` and `make dev-frontend` start the FastAPI server on `http://localhost:8080` and the Vite dev server on `http://localhost:5173` with API proxying. Run `make test-backend` for pytest, `npm run build` from `frontend/` for bundles, and `docker build -t xfolder:latest .` when validating container parity.

## Coding Style & Naming Conventions
Python follows Black (4 spaces, double quotes) with type-hinted functions, snake_case helpers, and PascalCase classes. Prefer dependency injection (FastAPI providers or constructors) over module-level singletons, and keep SQL/IO helpers in dedicated service modules. React code should remain functional, hook-based, and typed: files and components use PascalCase, handlers use camelCase, and shared types live next to the component that exports them. Both stacks should centralize `XFS_*` environment reads in their config helpers.

## Testing Guidelines
Backend tests belong in `backend/tests/test_*.py`; extend the synthetic directory fixtures to cover new duplicate or permission scenarios and include regression cases with every bug fix. Frontend specs can sit beside components or under `frontend/src/__tests__`, using Vitest + React Testing Library with MSW or stubbed fetch helpers for API calls. Before submitting work, run `make test-backend` and `npm run build`, targeting ≥80% coverage on new backend modules and documenting any exclusions.

## Commit & Pull Request Guidelines
Commits follow the Conventional Commit pattern already in history (`feat:`, `fix:`, `docs:`) with imperative subjects under 72 characters and descriptive bodies for behavior changes. Pull requests should summarize intent, list API/schema or config changes, link issues, and attach screenshots or curl transcripts when UI or endpoints shift. Always note new environment variables, confirm local test/build status, and tag reviewers responsible for backend, frontend, or deployment code.

## Security & Configuration Tips
Work from synthetic data only; never commit real scan outputs or customer file paths. Store secrets in ignored `.env` files and reference configurable `XFS_*` variables instead of inlined constants so operators can adjust ports, paths, and thresholds safely.

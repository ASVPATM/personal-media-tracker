# Contributing

Thank you for improving Personal Media Tracker.

1. Use Python 3.11 or newer and install with `uv sync --extra dev`.
2. Preserve the tested domain invariants: personal/provider ratings remain separate;
   viewing counts/events stay honest; unresolved identities are never guessed; imports
   preview before commit; deletion remains recoverable.
3. Run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`.
4. Add regression tests for behavior changes. Provider tests must use fakes or mock
   transports and must not require network access.
5. Use only synthetic data in fixtures and screenshots. Never commit `.env`, tokens,
   databases, caches, logs, personal exports, or watch history.

Frontend work remains build-free vanilla HTML/CSS/JavaScript. A Node toolchain is not
required to run the application. Keep route handlers small and put domain rules in
services rather than duplicating them in the UI.

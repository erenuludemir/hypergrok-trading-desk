# Blockchain-Trade-Bot integration boundary

This additive directory is the standalone source for the user-owned private ChatGPT Blockchain-Trade-Bot v0.1.1 skills-only plugin. It is **not** an extension of HyperGrok's live order connector, and changing these files does **not** install or start a trading process.

- The existing HyperGrok 7-role authorization and human-ticket approval remain intact.
- The independent 6-stage paper sequence is Scout → Filter → Analyst → Risk → Executor → Logger.
- No wallet secrets, no account sign-in, no real order send, no automatic live promotion.
- Tested with Python 3.13 (11 tests) on 2026-11-15; public Binance network checks must be verified separately on each deployment.
- Source provenance and different project licenses are described in `skills/blockchain-trade-bot/references/SOURCE_CROSSWALK.md`.
- Do not merge this integration into `main` until repository checks and maintainer review pass. Existing repository files are unchanged.

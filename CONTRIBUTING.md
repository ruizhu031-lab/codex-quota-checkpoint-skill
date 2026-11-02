# Contributing

Bug reports, documentation improvements, and focused fixes are welcome.

Before submitting a change:

1. Explain the concrete behavior and intended result. For quota policy changes, distinguish user-selected thresholds from an empirical estimate or an official limit.
2. Preserve explicit-only activation, the user's full project scope and acceptance criteria, and stop-before-new-work behavior.
3. Add a meaningful synthetic test for changes to quota arithmetic, cadence, or checkpoint behavior. Keep tests independent of live account access.
4. Run `python -B -X utf8 -m unittest discover -s quota-checkpoint/tests -v` from the repository root.
5. Update English and Chinese user documentation when behavior changes.

Tests use temporary fixture directories, do not touch production services, and do not query real usage. One Git test creates an isolated fixture commit and is skipped when Git is unavailable.

Do not include tokens, cookies, account IDs, raw live usage payloads, private project files, or personal handoff records in issues or pull requests. Use fictional observations and remove identifying paths from error messages. Clearly label untested behavior instead of claiming the helpers provide hard runtime enforcement.

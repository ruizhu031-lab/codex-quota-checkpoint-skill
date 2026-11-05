# Contributing

Bug reports, documentation improvements, and focused fixes are welcome.

Before submitting a change:

1. Explain the concrete behavior and intended result. For quota policy changes, distinguish user-selected thresholds from an empirical estimate or an official limit.
2. Preserve explicit-only activation, the user's full project scope/model/reasoning/acceptance criteria, and the sticky finish-current-unit-then-pause behavior. A reset or compaction must never cancel a pending stop.
3. Add meaningful synthetic tests for quota arithmetic, journal integrity, state transitions and scoped hooks. Preserve immutable original records and older checkpoints; recovery summaries cannot replace detail. Keep tests independent of live account access.
4. Run `python -B -X utf8 -m unittest discover -s quota-checkpoint/tests -v` from the repository root.
5. Update English and Chinese user documentation when behavior changes.

Tests use temporary fixture directories, do not touch production services, and do not query real usage. One Git test creates an isolated fixture commit and is skipped when Git is unavailable.

Do not include tokens, cookies, account IDs, raw live usage payloads, private project files, or personal handoff records in issues or pull requests. Use fictional observations and remove identifying paths from error messages. Clearly label untested behavior instead of claiming the helpers provide hard runtime enforcement.

Hooks must preserve existing project configuration, bind only to an explicitly activated real session, respect host trust, and avoid model/network calls. Never modify a trust database or use a trust-bypass flag. Test hook payloads in disposable projects and distinguish these tests from actual host event delivery. A missing session ID must degrade to documented basic record/recovery support without inventing a binding.

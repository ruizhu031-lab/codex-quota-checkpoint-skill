# Codex Quota Checkpoint Skill

**Manual-start Codex quota monitoring, durable project checkpoints, and evidence-based pause/resume.**

[简体中文](README.zh-CN.md) · [Skill instructions](quota-checkpoint/SKILL.md) · [Quota policy](quota-checkpoint/references/quota-policy.md) · [Checkpoint format](quota-checkpoint/references/checkpoint.md)

[![Tests](https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill/actions/workflows/tests.yml/badge.svg)](https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill/actions/workflows/tests.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`quota-checkpoint` is an explicitly invoked agent skill for long-running Codex projects. Start monitoring when you want it, save the real project state when you stop, and resume against the original requirements and verification evidence.

It addresses Codex usage limits / rate limits, quota-aware pausing, context preservation, handoffs, and project continuity. It keeps the original project scope, model settings, depth, and acceptance criteria as requirements of the workflow.

**This is a skill plus local Python helpers, not a background daemon, a billing client, or a hard quota enforcement service.** Live usage data must come from a tool already available in your Codex host, or from a fresh user-provided reading. The Python helpers do not retrieve account limits or credentials.

## What it does

| Capability | Behavior |
| --- | --- |
| Explicit activation | `allow_implicit_invocation: false`; project size, elapsed time, and expensive models do not start monitoring. |
| Low-frequency checks | Check after 15 active work minutes above 50% remaining; check more often only as quota decreases. |
| Quota-aware pause | Above 10%, keep the full task; within 5%–10%, budget for the next complete unit and saving; at 5% or below, save and pause. |
| Stop and save | A direct stop command prioritizes saving immediately at the next controllable boundary, whether monitoring was enabled or not. |
| Durable handoff | Versioned state, human-readable handoff, file fingerprints, and Git context when available. |
| Evidence-based resume | Reconcile current files, changed requirements, model settings, pending verification, and external side effects before continuing. |
| Preserve quality requirements | Never reduce deliverables, technical depth, reasoning effort, or required validation just because the project or an individual step is large. |
| Local helpers | Standard-library Python; no API key, credential extraction, purchases, reset redemption, or account switching. |

## Install

Requirements:

- A Codex surface that supports filesystem skills and explicit invocation.
- Python 3.10+ to run the optional helpers; Git is optional for capturing repository context.
- A supported, read-only usage tool for live monitoring. Availability varies by host. Stop/save/resume can still be used without live quota access.

### Ask Codex to install from GitHub

In a Codex environment with `$skill-installer`, use:

```text
Use $skill-installer to install the quota-checkpoint skill from:
https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill/tree/main/quota-checkpoint
```

### Manual installation

Clone or download this repository, then copy **only the `quota-checkpoint` directory**, including `agents/openai.yaml`, into a skill location supported by your host. The directory containing `SKILL.md` must remain named `quota-checkpoint`.

Current Codex documentation lists `~/.agents/skills` for personal filesystem skills and `.agents/skills` for repository-scoped skills. Some bundled installers or desktop versions use `$CODEX_HOME/skills` / `~/.codex/skills`; use the location your host actually discovers, and avoid installing duplicate copies.

macOS / Linux example:

```bash
git clone https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill.git
destination="$HOME/.agents/skills/quota-checkpoint"
if [ -e "$destination" ]; then
  echo "Destination already exists; review it before updating."
  exit 1
fi
mkdir -p "$HOME/.agents/skills"
cp -R codex-quota-checkpoint-skill/quota-checkpoint "$destination"
```

Windows PowerShell example:

```powershell
git clone https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill.git
$skillDestination = Join-Path $env:USERPROFILE '.agents\skills\quota-checkpoint'
if (Test-Path -LiteralPath $skillDestination) {
    throw 'Destination already exists; review it before updating.'
}
New-Item -ItemType Directory -Path (Split-Path -Parent $skillDestination) -Force | Out-Null
Copy-Item -LiteralPath '.\codex-quota-checkpoint-skill\quota-checkpoint' -Destination $skillDestination -Recurse
```

If the skill does not appear, start a fresh session or restart Codex. Installation does not enable monitoring: explicit invocation is still required. See the [official skill documentation](https://learn.chatgpt.com/docs/build-skills) for host-specific discovery and invocation.

## Use it

### Start monitoring a project

```text
Use $quota-checkpoint to start monitoring quota for this project.
Preserve all original deliverables, model settings, reasoning effort, and acceptance criteria.
```

The agent reads one initial usage snapshot, records your authorization for this project, and then follows the cadence below. It does not create a scheduled automation or a system service.

### Stop and save, without enabling monitoring

```text
Use $quota-checkpoint to stop work and save the current project state.
Do not query quota or enable monitoring.
```

After the skill has been explicitly loaded in the current project conversation, direct commands such as `Stop work and save progress` or `Continue the previous project` can use its workflow. In a fresh conversation, include `$quota-checkpoint` again: a generic phrase alone cannot guarantee that the host loads a skill with implicit invocation disabled.

### Resume

```text
Use $quota-checkpoint to resume the project from <checkpoint-directory>.
Reconcile current files and continue the complete original plan and validation requirements.
```

Resuming does not grant new monitoring permission. Monitoring resumes only if it was explicitly enabled for this project and has not been disabled. Missing authorization state defaults to off. Quota reset times are prompts to recheck, not evidence of recovery.

### Disable monitoring and keep working

```text
Disable quota monitoring for this project, but continue the project work.
```

### Discuss or edit the skill

```text
Review the quota-checkpoint skill. Do not execute its monitoring, stop, or resume workflow.
```

Examples, quotations, negated commands, and requests to review the skill are not operational commands.

## Monitoring cadence and pause rules

The lowest remaining percentage across **confirmed applicable quota windows** determines the next check:

| Remaining quota | Next check after active work |
| --- | --- |
| More than 50% | 15 minutes |
| More than 25%, up to 50% | 10 minutes |
| More than 10%, up to 25% | 5 minutes |
| More than 5%, up to 10% | 3 minutes |
| 5% or less | Save and pause |

Active work excludes waiting for the user, being paused, and pure external build/download waits. Checks happen at the next executable work boundary. A high-consumption model does not automatically change the cadence to once per minute. Explicit requests for an immediate reading, actual limit errors, or a deliberate model/speed/concurrency change can justify an extra check.

The 5%–10% band is a **remaining-quota decision range**, not an additional reserve on top of a much higher pause threshold:

- **Above 10%:** continue the complete original task. A large predicted unit can trigger an early save, but cannot justify reduced scope or an arbitrary early quota pause.
- **Above 5%, up to 10%:** estimate the next complete unit, saving cost, and any necessary recovery overhead. Continue only if the budget fits while preserving the 5% floor. Otherwise save and pause.
- **At or below 5%:** save and pause; do not start another unit.
- **Backend denies usage or data is unavailable:** preserve state and report the specific limitation instead of inventing availability.

Consumption estimates are heuristics, not OpenAI-issued guarantees. Account-level readings can include other conversations. High-consumption mode changes estimation margins, not the model itself or the monitoring interval. Integer readings that temporarily do not change are not treated as free work.

## What gets saved

The workflow records requirements and acceptance criteria, completed work, pending work, decisions and evidence, rejected approaches, source materials, verification results, the exact next action, model configuration, running jobs, and external side effects.

Typical local structure:

```text
project/
└── .codex-progress/
    └── task-id/
        ├── control.json           # Agent-maintained authorization and timing state
        ├── LATEST                 # Latest published checkpoint version
        └── <version>/
            ├── state.json
            ├── HANDOFF.md
            └── manifest.json      # SHA-256 file fingerprints and Git context
```

`checkpoint.py` publishes checkpoint versions before atomically replacing `LATEST`. The agent maintains `control.json` separately according to the [documented schema](quota-checkpoint/references/checkpoint.md); the helper does not implement a background controller. Failed publication preserves the previous `LATEST` where possible. Verification reports changed or missing artifacts without overwriting user edits.

**A checkpoint is a handoff record and a set of file fingerprints, not a backup of project contents or process memory.** Keep the actual project files. If moving to another machine or checkout, transfer both the working files and the progress directory. The workflow does not automatically commit, push, or upload your project.

## Local helper commands

Run these only with the intended project and input files:

```text
python <skill-dir>/scripts/assess.py <fresh-observation.json> --previous <previous-decision.json>
python <skill-dir>/scripts/assess.py <fresh-observation.json> --heavy --unit-minutes 20
python <skill-dir>/scripts/checkpoint.py save <state.json> --root <project-root> --task <task-id>
python <skill-dir>/scripts/checkpoint.py verify --root <project-root> --task <task-id>
```

`--unit-minutes` is a cost estimate, not a deadline or a request to truncate a complete unit. `assess.py` reads a previously obtained usage observation; it cannot log in or fetch limits. Its normal `continue`, `pause`, and `unknown` decisions all exit with code 0: **read the JSON `action`, not just the process exit code**. Invalid inputs return a nonzero exit code.

Input schemas and estimation rules: [quota policy](quota-checkpoint/references/quota-policy.md). State schema, artifact verification, and authorization state: [checkpoint reference](quota-checkpoint/references/checkpoint.md).

## Privacy, compatibility, and limits

- No credential files, cookies, API keys, or private billing endpoints are read by the helpers. No credits are bought and no reset coupons are redeemed.
- Progress remains in your project unless you separately publish it. Before committing any repository, review `.codex-progress`, raw quota observations, and handoff text for sensitive content. The helper does not automatically change your project's `.gitignore`.
- Live usage tools are host-specific. No API is silently installed when one is missing; you can still explicitly stop/save/resume without monitoring.
- This standalone filesystem skill is not an official OpenAI product, a universal ChatGPT plugin, or a service that enforces account limits.
- A skill cannot reliably interrupt an in-progress reasoning request or an external tool without host support. It cannot guarantee a save before an unexpected hard limit or outage.
- The workflow preserves quality requirements; it cannot guarantee mathematically identical model output, hidden reasoning state, or perfect cross-session quality equivalence.
- Model task coordination is limited to jobs the current project owns and the host can control. Other chats are not stopped automatically.

## Validation and contributing

Run the standard-library test suite from the repository root:

```bash
python -B -X utf8 -m unittest discover -s quota-checkpoint/tests -v
```

The 51 test methods cover percentage handling, multiple limits, missing/stale data, service denials, cadence boundaries, model changes, rounding behavior, scope preservation flags, checkpoint integrity, user edits, missing files, path containment, moved projects, and failed writes/publication. Tests use synthetic observations and disposable files; they do not read live account limits. One Git-specific test is skipped if Git is unavailable.

These are deterministic helper tests, not end-to-end proof of natural-language routing, real quota exhaustion, exact scheduling, or equal-quality continuation. CI runs the suite on Linux and Windows. See [CONTRIBUTING.md](CONTRIBUTING.md) before changing defaults or reporting a bug.

## License and references

[MIT License](LICENSE), copyright 2026 ruizhu031-lab. Independent project; not affiliated with OpenAI.

- [Official Codex skill discovery, installation, and invocation policy](https://learn.chatgpt.com/docs/build-skills)
- [Official Codex App Server rate-limit protocol](https://learn.chatgpt.com/docs/app-server)
- [Official Codex usage and pricing guidance](https://learn.chatgpt.com/docs/pricing)

Search terms: Codex skill, Codex skills, agent skills, quota monitoring, usage limits, rate limits, checkpoint, pause resume, durable handoff, context preservation, long-running AI projects; Codex 技能、额度监测、用量限制、断点保存、暂停继续、项目续接。

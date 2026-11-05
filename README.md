# Codex Quota Checkpoint Skill

**Explicit-start Codex quota monitoring, full technical work records, and pause/resume with recovery after context compaction.**

[简体中文](README.zh-CN.md) · [Skill instructions](quota-checkpoint/SKILL.md) · [Quota policy](quota-checkpoint/references/quota-policy.md) · [Recovery workflow](quota-checkpoint/references/recovery.md)

[![Tests](https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill/actions/workflows/tests.yml/badge.svg)](https://github.com/ruizhu031-lab/codex-quota-checkpoint-skill/actions/workflows/tests.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

`quota-checkpoint` helps long-running Codex projects preserve their original requirements, engineering details, decisions, validation evidence, and exact unfinished work across usage limits and context compaction. You explicitly invoke it; monitoring and detailed records then start for that project.

The skill keeps the original deliverables, model/reasoning settings, technical depth, and acceptance criteria. A large project or a large individual step is never a reason to reduce scope or substitute a draft for the requested result.

This package contains agent instructions and standard-library Python helpers. The agent schedules checks at work boundaries using a read-only usage tool available in its host. Helpers do not fetch account usage, access credentials, start a background service, or call a model. Optional local compaction hooks run only for an explicitly bound project session.

## What it does

| Capability | Behavior |
| --- | --- |
| Explicit activation | `allow_implicit_invocation: false`; size, elapsed time, expensive models, and old records never start it. |
| Monitoring on invocation | A plain `$quota-checkpoint` invocation starts monitoring and detailed technical documentation. |
| Low-frequency checks | 20 / 15 / 5 / 3 active minutes according to the remaining-quota table below. |
| Finish, then pause | At 5%–10% or on a normal stop request, budget only the already-started unit plus verification, documentation, summary and saving. |
| Full technical history | Immutable journal entries produce a complete `TECHNICAL_LOG.md`; new summaries never replace the detailed originals. |
| Recovery after compaction | A scoped AGENTS index and optional trusted lifecycle hooks direct Codex back to the original records. |
| Verified handoff | Versioned state, control snapshots, file hashes, source references, actual verification results, and Git context. |
| User-controlled resumption | After pausing, there is no quota polling or automatic restart. An explicit continue request and recovery review are required. |

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

## Usage

### Activate

```text
$quota-checkpoint
```

In a project chat, this means: start quota monitoring, create or continue the detailed technical log, and prepare scoped recovery protection. A review/edit request that merely mentions the skill is not activation. Installation alone does not activate it.

The agent records the project and task identity, your authorization, and the actual host session ID when available; it reads one initial quota snapshot. It maintains a full-scope current unit with its original completion criteria. No fixed short time limit is imposed on that unit.

### Stop, or stop immediately

```text
Stop work and save progress.
```

This immediately starts the stopping procedure: preserve the breakpoint and latch the stop request, then assess whether quota can cover the **remaining work in the existing unit, its required verification, the technical-record update, final summary and saving**, while keeping the 5% floor in every applicable window.

If sufficient, finish only that unit and pause. If insufficient, unknown, or no unit is already underway, save and pause now. A quota reset cannot cancel a latched stop. If the estimate worsens while finishing, save the unfinished work and pause.

For an immediate save without further project advancement:

```text
Do not continue the current unit. Save and pause immediately without querying quota.
```

After the skill is loaded, natural-language stop/continue commands work in the same project chat. In a fresh chat, explicitly include `$quota-checkpoint` and identify the task/checkpoint directory.

### Continue

```text
Use $quota-checkpoint to continue this project from <checkpoint-directory>.
Read the original requirements, relevant full technical records and evidence before proceeding.
```

The agent reconciles original requirements, decisions, the exact current unit, pending work, verification, current files, user edits, running jobs and external effects. It records factual recovery notes before continuing. Existing model/reasoning settings and acceptance criteria remain in force.

If monitoring was enabled and not disabled, it takes a fresh reading before work. A predicted reset time is not proof that quota recovered. A compaction event or reopening a paused chat is not a user continue instruction.

### Disable monitoring, or discuss the skill

```text
Disable quota monitoring, but keep working and maintaining the technical records.
```

```text
Review or modify quota-checkpoint. Do not activate it for this conversation.
```

Disabling monitoring does not cancel an already-issued stop request. Quoted examples, negated commands and skill maintenance never register hooks or start monitoring.

## Cadence and quota decisions

Use the lowest remaining percentage among **confirmed applicable windows**:

| Remaining quota | Next check after active work |
| --- | --- |
| More than 50% | 20 minutes |
| More than 20%, up to 50% | 15 minutes |
| More than 10%, up to 20% | 5 minutes |
| More than 5%, up to 10% | 3 minutes, only while finishing the current unit |
| 5% or less | Save and pause |

Exactly 50% uses 15 minutes; exactly 20% uses 5 minutes; exactly 10% enters the finishing decision; exactly 5% saves and pauses. Active work excludes user waiting, pauses, and pure external build/download waits. Checks occur at the next controllable boundary, not during an uninterruptible tool or inference call.

Above 10%, without a stop request, a large estimate can prompt an early checkpoint but never reduced scope or an arbitrary higher pause threshold. In the decision band, or after a normal stop request at any percentage, every applicable window must cover the complete remaining unit and saving costs plus the 5% floor. Equality is insufficient. Missing unit identity or missing estimates means save now.

The 3-minute interval ends when the project is formally paused. There is no background polling, reset redemption, credit purchase, account switching or automatic resumption.

Estimates are conservative heuristics, not official promises of a number of remaining tasks. Shared-account consumption may include other chats. Heavy mode changes estimation margins, not the selected model or monitoring cadence. Actual limit errors, explicit immediate-check requests and deliberate model/speed/concurrency changes can justify an extra reading.

## Full technical records

From activation onward, the agent records the original goal and current user requirements, all deliverables and acceptance criteria, work steps, decisions and rationale, rejected approaches, exact files/interfaces/parameters, commands and results, failures and fixes, references, verification evidence, unfinished work, the next action and external effects.

Important results are appended promptly; if meaningful progress has not yet been recorded, it is written at a controllable boundary after about 5 active minutes at most. Full checkpoints are updated at meaningful milestones, before pausing, and around 15 active minutes. Saving does not query quota.

```text
project/
  AGENTS.md                         # Bounded recovery index; existing rules preserved
  .codex/hooks.json                  # Optional scoped hooks; host trust required
  .codex-progress/task-id/
    TECHNICAL_LOG.md                 # Complete readable history, not a rolling summary
    journal/<sha256>.json            # Immutable original entries and predecessor hashes
    JOURNAL_HEAD
    control.json                    # Authorization, session, unit, phase, pending stop
    LATEST
    <checkpoint-version>/
      state.json
      HANDOFF.md
      manifest.json
      control.json                  # When available
    evidence/                       # Relevant output/source evidence, created as needed
```

Corrections append new entries; they do not rewrite history. Retrying the same event ID and identical text is idempotent. Reusing it with different text is rejected. If the Markdown view is damaged, it can be rebuilt from the verified original chain, with all details intact. A corrupt chain is reported instead of reconstructed from guesses.

Long outputs are stored as local evidence and referenced; the agent reads relevant originals when needed instead of repeatedly loading or rewriting the whole history. The helpers do not capture every tool result automatically: the agent must continuously record substantive engineering facts. They do not store hidden reasoning, credentials, cookies or full environment dumps.

A checkpoint contains records and fingerprints; it is **not a backup of the source files or process memory**. Keep the real project files and transfer the entire progress directory when moving a project.

## Context-compaction recovery

The detailed document is a disk artifact. Conversation compaction must not shorten it or replace it with a summary. Recovery uses three layers:

1. Persistent original journal entries and the full technical document.
2. A short, bounded recovery index added to project AGENTS guidance, preserving existing content.
3. Optional project `PreCompact` and `SessionStart` hooks for `compact`/`resume`, bound to a real, explicitly activated session.

Before compaction, the hook verifies saved records and marks recovery review as required. After compaction, it supplies document locations and static recovery instructions before the next model request. It does not fabricate unwritten details, query quota, call another model, or resume a paused project. Stored journal text is not promoted into developer instructions.

New or changed hooks must be reviewed and trusted through **Settings > Hooks** or **`/hooks`**; a session reload may be needed. Setup reports `configured_requires_host_trust` and never edits the host trust store or bypasses approval. If the host lacks hook support or a real session ID, records and the index remain available and the limitation is reported. An `AGENTS.override.md` can shadow the normal index; existing inline hooks require deliberate merging rather than duplicate installation. See the [full recovery workflow](quota-checkpoint/references/recovery.md) and [official Hooks documentation](https://learn.chatgpt.com/docs/hooks).

After compaction, work must first reconcile complete requirements, key decisions, the existing unit, pending work, verification evidence, current files and side effects. Missing facts are recovered from originals or explicitly reported before dependent work. A finishing task still finishes only its bound unit and then pauses; a paused task waits for explicit continuation.

**This protects saved details and establishes a recovery procedure. It cannot pin an entire document permanently in model context, recover information never written to disk, guarantee a hook runs on every host, or prove identical model comprehension/output after compaction.** The full project scope and quality criteria remain mandatory.

## Local helpers and compatibility

Detailed input schemas and commands: [quota calculation](quota-checkpoint/references/quota-policy.md), [checkpoints](quota-checkpoint/references/checkpoint.md), [workflow, journal and hooks](quota-checkpoint/references/recovery.md).

```text
python <skill-dir>/scripts/assess.py <observation.json> --control <task-dir>/control.json --unit-minutes 8 --save-minutes 2
python <skill-dir>/scripts/checkpoint.py append <event.md> --event-id <unique-id> --root <project> --task <task-id>
python <skill-dir>/scripts/checkpoint.py save <state.json> --root <project> --task <task-id>
python <skill-dir>/scripts/checkpoint.py verify --root <project> --task <task-id>
python <skill-dir>/scripts/workflow.py recover --root <project> --task <task-id>
```

`--unit-minutes` estimates the full remaining work and necessary verification, not a deadline. `--save-minutes` includes documentation and summary work. Neither estimate is fabricated when missing. `assess.py` schema version 2 returns `continue`, `finish_then_pause`, `pause` or `unknown`. Normal decisions all exit 0: **inspect JSON `action`**. The workflow maps unknown availability to a saved pause.

The workflow persists the current unit and pending stop, refuses a different unit during stopping, and requires factual recovery notes against a fingerprint before explicit resume. Fingerprints catch changed evidence; they cannot prove that an agent understood every fact. Legacy checkpoints remain readable; explicit migration preserves old versions and labels missing history rather than inventing it.

Hook setup is a separate project operation during explicit activation, not an installation side effect. It backs up and preserves existing guidance and unrelated hooks. Runtime config contains machine-specific Python/script paths: regenerate it after moving the skill or changing machines. No helper automatically uploads project records or commits/pushes changes.

## Privacy, cost and limits

- Records, evidence, raw quota observations and hook state stay local unless you publish them. Review them before committing; the skill does not silently alter project `.gitignore` files.
- Live usage tools are host-specific; no private endpoint or credential extraction is used when a tool is missing. A hard stop can always save accessible work without querying quota.
- Incremental documentation and recovery reads consume some model budget. Local hashing, rendering and hook checks do not make extra model calls. No fixed overhead percentage is promised.
- Long uninterruptible calls, abrupt quota denial, process failure, permissions, disk errors or hook timeouts can prevent timely saving or checking. Failed saves and unverified host integration must be reported honestly.
- Other projects/chats are not stopped. Task coordination covers only owned jobs the host can actually control.
- This independent filesystem skill is not an official OpenAI service or hard account-limit enforcement mechanism.

## Tests and contributing

```bash
python -B -X utf8 -m unittest discover -s quota-checkpoint/tests -v
```

The suite uses synthetic quota data and disposable project directories. It tests thresholds, all-window budgets, stop persistence, full-size units, documentation cost, append-only history, failed writes, checksums, legacy migration, user edits, scoped hooks, preserving existing config and reconstructing task details in a fresh process without a chat summary. CI covers Linux/Windows and Python 3.10/3.13. A Git-specific test is skipped if Git is unavailable.

These are deterministic and simulated lifecycle tests, not proof of actual host compaction delivery, natural-language compliance, quota-exhaustion survival or equal model quality. Actual hook trust and event delivery must be verified in the intended host. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License and references

[MIT License](LICENSE), copyright 2026 ruizhu031-lab. Independent project; not affiliated with OpenAI.

- [Official skill discovery and invocation policy](https://learn.chatgpt.com/docs/build-skills)
- [Official rate-limit protocol](https://learn.chatgpt.com/docs/app-server)
- [Official usage guidance](https://learn.chatgpt.com/docs/pricing)
- [Official Hooks](https://learn.chatgpt.com/docs/hooks)
- [Official AGENTS guidance](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Codex agent loop and compaction](https://openai.com/index/unrolling-the-codex-agent-loop/)

Search terms: Codex skill, agent skills, quota monitoring, rate limits, usage limits, checkpoint, pause resume, technical work log, context compaction, context recovery, context preservation, long-running projects; Codex 技能、额度监测、断点续接、技术记录、上下文压缩恢复。

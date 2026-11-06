#!/usr/bin/env python3
"""Publish and verify local, versioned handoffs without changing project files."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid


LIST_FIELDS = ("requirements", "decisions", "completed", "in_progress", "verification",
               "open_questions", "processes", "references", "artifacts")
TEXT_FIELDS = ("objective", "next_step", "model_context", "quota_summary")
VERSION = re.compile(r"\d{8}T\d{12}Z-[0-9a-f]{8}")


def inside(root, path):
    original = Path(path)
    path = original.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path escapes the selected project root")
    if original.is_relative_to(root / ".codex-progress") and original != path:
        raise ValueError("Progress paths must not alias other files or tasks")
    return path


def task_directory(root, task):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", task):
        raise ValueError("Task ID must be 1-64 lowercase letters, digits, or hyphens")
    path = root / ".codex-progress" / task
    resolved = inside(root, path)
    if resolved != path:
        raise ValueError("Task directory must not be a symlink or junction alias")
    return resolved


def validate(state):
    if not isinstance(state, dict):
        raise ValueError("Checkpoint state must be a JSON object")
    allowed = set(LIST_FIELDS + TEXT_FIELDS + ("status",))
    if set(state) - allowed:
        raise ValueError("Unsupported state fields: " + ", ".join(sorted(set(state) - allowed)))
    if state.get("status") not in {"active", "finishing", "paused_user", "paused_quota", "paused_unknown", "completed"}:
        raise ValueError("Invalid checkpoint status")
    for key in TEXT_FIELDS:
        if not isinstance(state.get(key), str) or not state[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    for key in LIST_FIELDS:
        value = state.get(key)
        if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
            raise ValueError(f"{key} must be a list of nonempty strings (or an empty list)")
    if not state["verification"]:
        raise ValueError("verification must state observed results or explicitly state not verified")


def fingerprint(path):
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("Artifact changed while hashing: " + str(path))
    return {"sha256": digest.hexdigest(), "bytes": after.st_size}


def artifact_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or path.drive or not relative.strip() or path == Path("."):
        raise ValueError("Artifacts must have relative file paths inside the project")
    return inside(root, root / path)


def git_snapshot(root):
    prefix = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-c",
              "core.untrackedCache=false", "-C", str(root)]

    def run(args):
        result = subprocess.run(prefix + args, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=20, check=False)
        if result.returncode:
            raise ValueError(result.stderr.strip() or "Git read failed")
        return result.stdout.strip()

    try:
        return {"available": True, "topLevel": run(["rev-parse", "--show-toplevel"]),
                "head": run(["rev-parse", "HEAD"]), "branch": run(["branch", "--show-current"]),
                "status": run(["status", "--short", "--untracked-files=normal", "--", ".",
                               ":(exclude).codex-progress"])}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc)}


def write_synced(path, data):
    with path.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def atomic_write(path, data):
    descriptor, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        write_synced(temporary, data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def task_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".writer-lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError("Task writer is busy; inspect a stale lock before removing it") from exc
    try:
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def journal_entries(root, task, head=None):
    root = Path(root).resolve(strict=True)
    directory = task_directory(root, task)
    if head is None:
        head = inside(root, directory / "JOURNAL_HEAD").read_text(encoding="utf-8").strip()
    cursor, entries, seen = head, [], set()
    while cursor:
        if not isinstance(cursor, str) or not re.fullmatch(r"[0-9a-f]{64}", cursor) or cursor in seen:
            raise ValueError("Invalid journal chain")
        seen.add(cursor)
        data = inside(root, directory / "journal" / (cursor + ".json")).read_bytes()
        if hashlib.sha256(data).hexdigest() != cursor:
            raise ValueError("Journal entry fingerprint mismatch")
        entry = json.loads(data)
        if (not isinstance(entry, dict) or entry.get("schemaVersion") != 1
                or entry.get("task") != task
                or not isinstance(entry.get("id"), str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", entry["id"])
                or not isinstance(entry.get("text"), str) or not entry["text"].strip()
                or not isinstance(entry.get("createdAt"), str)
                or type(entry.get("sequence")) is not int
                or not isinstance(entry.get("previous"), str)):
            raise ValueError("Invalid journal entry")
        entries.append(entry)
        cursor = entry["previous"]
    entries.reverse()
    if not entries or [entry["sequence"] for entry in entries] != list(range(1, len(entries) + 1)):
        raise ValueError("Incomplete journal sequence")
    if len({entry["id"] for entry in entries}) != len(entries):
        raise ValueError("Duplicate journal event ID")
    return head, entries


def render_journal(task, entries):
    parts = [f"# 技术工作记录 / Technical work log\n\nTask: {task}\n\n",
             "完整历史由不可变条目生成；更正应追加记录，不能用摘要替换原文。\n\n"]
    for entry in entries:
        parts.append(f"## {entry['sequence']}. {entry['id']} — {entry['createdAt']}\n\n")
        parts.append(entry["text"])
        parts.append("\n\n")
    return "".join(parts).encode("utf-8")


def latest_journal_head(root, task):
    directory = task_directory(root, task)
    pointer = inside(root, directory / "LATEST")
    if not pointer.exists():
        return None
    version = pointer.read_text(encoding="utf-8").strip()
    if not VERSION.fullmatch(version):
        raise ValueError("LATEST is not a valid local checkpoint version name")
    manifest = json.loads(inside(root, directory / version / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or manifest.get("task") != task:
        raise ValueError("Checkpoint manifest schema or task ID is invalid")
    if "journal" not in manifest:
        return None  # Legacy checkpoints may predate the detailed journal.
    journal = manifest["journal"]
    if not isinstance(journal, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(journal.get("head", ""))):
        raise ValueError("Saved journal anchor is invalid")
    return journal["head"]


def verify_journal(root, task, head=None, check_view=True, required_ancestor=None):
    root = Path(root).resolve(strict=True)
    head, entries = journal_entries(root, task, head)
    if (required_ancestor is not None and head != required_ancestor
            and not any(entry["previous"] == required_ancestor for entry in entries)):
        raise ValueError("Journal rolled back or diverged from the saved checkpoint; restore the missing original chain")
    data = render_journal(task, entries)
    path = inside(root, task_directory(root, task) / "TECHNICAL_LOG.md")
    if check_view and (not path.is_file() or path.read_bytes() != data):
        raise ValueError("Technical log differs from immutable entries; rebuild the view, do not overwrite history")
    return {"head": head, "entryCount": len(entries), "textSha256": hashlib.sha256(data).hexdigest(),
            "technicalLog": str(path)}


def append_journal(root, task, event_id, text):
    root = Path(root).resolve(strict=True)
    with task_lock(task_directory(root, task)):
        return _append_journal(root, task, event_id, text)


def _append_journal(root, task, event_id, text):
    """Append while the caller holds the task writer lock."""
    directory = task_directory(root, task)
    if not isinstance(event_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", event_id):
        raise ValueError("Event ID must contain 1-96 lowercase letters, digits, or hyphens")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Journal entry must contain actual engineering facts")
    pointer = inside(root, directory / "JOURNAL_HEAD")
    journal = inside(root, directory / "journal")
    anchor = latest_journal_head(root, task)
    if not pointer.exists() and (anchor is not None
            or inside(root, directory / "TECHNICAL_LOG.md").exists()
            or (journal.exists() and any(journal.iterdir()))):
        raise ValueError("Existing technical records have no JOURNAL_HEAD; preserve them and recover the original history before appending")
    head, entries = journal_entries(root, task) if pointer.exists() else ("", [])
    if head:
        verify_journal(root, task, required_ancestor=anchor)
    for old in entries:
        if old["id"] == event_id:
            if old["text"] != text:
                raise ValueError("An existing event cannot be rewritten; append a correction with a new ID")
            atomic_write(inside(root, directory / "TECHNICAL_LOG.md"), render_journal(task, entries))
            return {"saved": True, "duplicate": True, **verify_journal(root, task)}
    entry = {"schemaVersion": 1, "task": task, "id": event_id, "sequence": len(entries) + 1,
             "createdAt": datetime.now(timezone.utc).isoformat(), "previous": head, "text": text}
    data = json_bytes(entry)
    digest = hashlib.sha256(data).hexdigest()
    journal.mkdir(exist_ok=True)
    file = inside(root, journal / (digest + ".json"))
    if file.exists() and file.read_bytes() != data:
        raise ValueError("Existing immutable journal entry is corrupted")
    if not file.exists():
        atomic_write(file, data)
    # The immutable entry is durable before publishing the head. A failed view
    # update can be repaired from this chain without losing any original text.
    atomic_write(pointer, (digest + "\n").encode("ascii"))
    atomic_write(inside(root, directory / "TECHNICAL_LOG.md"), render_journal(task, entries + [entry]))
    return {"saved": True, "duplicate": False, **verify_journal(root, task)}


def rebuild_journal(root, task):
    root = Path(root).resolve(strict=True)
    directory = task_directory(root, task)
    with task_lock(directory):
        verify_journal(root, task, check_view=False, required_ancestor=latest_journal_head(root, task))
        _, entries = journal_entries(root, task)
        path = inside(root, directory / "TECHNICAL_LOG.md")
        data = render_journal(task, entries)
        backup = None
        if path.exists() and path.read_bytes() != data:
            backup = inside(root, directory / ("TECHNICAL_LOG.before-rebuild-" + uuid.uuid4().hex + ".md"))
            atomic_write(backup, path.read_bytes())
        atomic_write(path, data)
        return {**verify_journal(root, task), "preserved_view_backup": str(backup) if backup else None}


def render_handoff(state, root, task, created):
    labels = {"objective": "目标与完成条件", "requirements": "要求与验收标准", "decisions": "决策与依据",
              "completed": "已完成", "in_progress": "未完成现场", "next_step": "下一步具体动作",
              "verification": "验证证据", "open_questions": "未决问题", "model_context": "模型与推理设置",
              "processes": "运行任务与外部副作用", "references": "原始资料与重读范围",
              "artifacts": "必须核对的实际文件", "quota_summary": "额度与暂停原因"}
    lines = ["# 项目交接", "", f"任务：{task}", f"状态：{state['status']}",
             f"保存时间（UTC）：{created}", f"项目根目录：{root}", ""]
    for key, title in labels.items():
        lines.extend(["## " + title, ""])
        value = state[key]
        lines.extend(["- " + item for item in value] if isinstance(value, list) else [value])
        if isinstance(value, list) and not value:
            lines.append("无已记录项")
        lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


def save_checkpoint(root, task, state):
    root = Path(root).resolve(strict=True)
    with task_lock(task_directory(root, task)):
        return _save_checkpoint(root, task, state)


def _save_checkpoint(root, task, state):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Project root must be a directory")
    validate(state)
    state = dict(state)
    files = {}
    for relative in state["artifacts"]:
        path = artifact_path(root, relative)
        if not path.is_file():
            raise ValueError("Artifact is missing or is not a file: " + relative)
        canonical = path.relative_to(root).as_posix()
        files[canonical] = fingerprint(path)
    state["artifacts"] = list(files)
    git = git_snapshot(root)
    created = datetime.now(timezone.utc)
    created_text = created.isoformat()
    version = created.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    state_data = json_bytes(state)
    handoff_data = render_handoff(state, root, task, created_text)
    manifest = {"schemaVersion": 1, "task": task, "projectRoot": str(root), "createdAt": created_text,
                "git": git, "files": files,
                "stateSha256": hashlib.sha256(state_data).hexdigest(),
                "handoffSha256": hashlib.sha256(handoff_data).hexdigest()}
    directory = task_directory(root, task)
    directory.mkdir(parents=True, exist_ok=True)
    anchor = latest_journal_head(root, task)
    if inside(root, directory / "JOURNAL_HEAD").exists() or anchor is not None:
        manifest["journal"] = verify_journal(root, task, required_ancestor=anchor)
    control_file = inside(root, directory / "control.json")
    control_data = control_file.read_bytes() if control_file.exists() else None
    if control_data is not None:
        manifest["controlSha256"] = hashlib.sha256(control_data).hexdigest()
    pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=directory))
    write_synced(pending / "state.json", state_data)
    write_synced(pending / "HANDOFF.md", handoff_data)
    if control_data is not None:
        write_synced(pending / "control.json", control_data)
    write_synced(pending / "manifest.json", json_bytes(manifest))
    published = directory / version
    os.replace(pending, published)
    descriptor, pointer_name = tempfile.mkstemp(prefix=".latest-", dir=directory)
    os.close(descriptor)
    pointer = Path(pointer_name)
    write_synced(pointer, (version + "\n").encode("utf-8"))
    os.replace(pointer, directory / "LATEST")
    return {"saved": True, "taskDirectory": str(directory), "versionDirectory": str(published),
            "handoff": str(published / "HANDOFF.md"), "artifactCount": len(files)}


def verify_checkpoint(root, task):
    root = Path(root).resolve(strict=True)
    directory = task_directory(root, task)
    version = inside(root, directory / "LATEST").read_text(encoding="utf-8").strip()
    if not VERSION.fullmatch(version):
        raise ValueError("LATEST is not a valid local checkpoint version name")
    published = inside(root, directory / version)
    manifest = json.loads(inside(root, published / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or manifest.get("task") != task:
        raise ValueError("Checkpoint manifest schema or task ID is invalid")
    records = manifest.get("files")
    if not isinstance(records, dict):
        raise ValueError("Checkpoint file manifest is invalid")
    integrity = True
    for name, key in (("state.json", "stateSha256"), ("HANDOFF.md", "handoffSha256")):
        file = inside(root, published / name)
        if not file.is_file() or fingerprint(file)["sha256"] != manifest.get(key):
            integrity = False
    if integrity:
        state = json.loads((published / "state.json").read_text(encoding="utf-8"))
        validate(state)
        if state["artifacts"] != list(records):
            integrity = False
    if "controlSha256" in manifest:
        control = inside(root, published / "control.json")
        if not control.is_file() or fingerprint(control)["sha256"] != manifest["controlSha256"]:
            integrity = False
    journal_status = {"available": False}
    if "journal" in manifest:
        try:
            old = verify_journal(root, task, manifest["journal"]["head"], check_view=False)
            current = verify_journal(root, task, required_ancestor=old["head"])
            if old["textSha256"] != manifest["journal"]["textSha256"]:
                raise ValueError("Saved journal fingerprint differs")
            journal_status = {"available": True, "intact": True,
                              "advanced": old["head"] != current["head"], **current}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            integrity = False
            journal_status = {"available": True, "intact": False, "error": str(exc)}
    changed, missing, unchanged = [], [], []
    for relative, recorded in records.items():
        if not isinstance(recorded, dict) or not isinstance(recorded.get("sha256"), str):
            raise ValueError("Invalid artifact fingerprint in manifest")
        path = artifact_path(root, relative)
        if not path.is_file():
            missing.append(relative)
        elif fingerprint(path) != recorded:
            changed.append(relative)
        else:
            unchanged.append(relative)
    current_git = git_snapshot(root)
    prior_git = manifest.get("git", {})
    return {"integrity_ok": integrity, "versionDirectory": str(published), "journal": journal_status,
            "changed": changed, "missing": missing, "unchanged": unchanged,
            "rootMoved": manifest.get("projectRoot") != str(root),
            "gitChanged": prior_git != current_git, "savedGit": prior_git, "currentGit": current_git}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("save")
    save.add_argument("state", type=Path)
    save.add_argument("--root", required=True, type=Path)
    save.add_argument("--task", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--root", required=True, type=Path)
    verify.add_argument("--task", required=True)
    append = commands.add_parser("append", help="Append an immutable technical-log event")
    append.add_argument("entry", type=Path)
    append.add_argument("--event-id", required=True)
    append.add_argument("--root", required=True, type=Path)
    append.add_argument("--task", required=True)
    rebuild = commands.add_parser("rebuild-log", help="Rebuild the full Markdown view from intact original entries")
    rebuild.add_argument("--root", required=True, type=Path)
    rebuild.add_argument("--task", required=True)
    args = parser.parse_args()
    try:
        if args.command == "save":
            state = json.loads(args.state.read_text(encoding="utf-8-sig"))
            result = save_checkpoint(args.root, args.task, state)
        elif args.command == "verify":
            result = verify_checkpoint(args.root, args.task)
        elif args.command == "append":
            result = append_journal(args.root, args.task, args.event_id, args.entry.read_text(encoding="utf-8-sig"))
        else:
            result = rebuild_journal(args.root, args.task)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 3 if args.command == "verify" and not result["integrity_ok"] else 0


if __name__ == "__main__":
    sys.exit(main())

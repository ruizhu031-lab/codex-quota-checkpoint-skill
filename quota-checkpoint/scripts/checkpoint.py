#!/usr/bin/env python3
"""Publish and verify local, versioned handoffs without changing project files."""

import argparse
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
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Path escapes the selected project root")
    return path


def task_directory(root, task):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", task):
        raise ValueError("Task ID must be 1-64 lowercase letters, digits, or hyphens")
    return inside(root, root / ".codex-progress" / task)


def validate(state):
    if not isinstance(state, dict):
        raise ValueError("Checkpoint state must be a JSON object")
    allowed = set(LIST_FIELDS + TEXT_FIELDS + ("status",))
    if set(state) - allowed:
        raise ValueError("Unsupported state fields: " + ", ".join(sorted(set(state) - allowed)))
    if state.get("status") not in {"active", "paused_quota", "completed"}:
        raise ValueError("status must be active, paused_quota, or completed")
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
    pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=directory))
    write_synced(pending / "state.json", state_data)
    write_synced(pending / "HANDOFF.md", handoff_data)
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
    return {"integrity_ok": integrity, "versionDirectory": str(published),
            "changed": changed, "missing": missing, "unchanged": unchanged,
            "rootMoved": manifest.get("projectRoot") != str(root),
            "gitChanged": prior_git != current_git, "savedGit": prior_git, "currentGit": current_git}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("save")
    save.add_argument("state", type=Path)
    save.add_argument("--root", required=True, type=Path)
    save.add_argument("--task", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--root", required=True, type=Path)
    verify.add_argument("--task", required=True)
    args = parser.parse_args()
    try:
        if args.command == "save":
            state = json.loads(args.state.read_text(encoding="utf-8-sig"))
            result = save_checkpoint(args.root, args.task, state)
        else:
            result = verify_checkpoint(args.root, args.task)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if args.command == "save" or result["integrity_ok"] else 3


if __name__ == "__main__":
    sys.exit(main())

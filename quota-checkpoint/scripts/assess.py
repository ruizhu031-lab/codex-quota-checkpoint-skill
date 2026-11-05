#!/usr/bin/env python3
"""Budget a complete existing unit from an already-fetched Codex usage observation.

No network, credentials, billing operations, or background polling.
All normal decisions exit 0; inspect the JSON action field.
"""

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def cadence_minutes(remaining):
    if remaining > 50:
        return 20
    if remaining > 20:
        return 15
    if remaining > 10:
        return 5
    return 3


def unwrap(value):
    for _ in range(5):
        if not isinstance(value, dict) or value.get("isError"):
            raise ValueError("Usage response is unavailable or reports an error")
        if "rateLimits" in value or "rateLimitsByLimitId" in value:
            return value
        if isinstance(value.get("structuredContent"), dict):
            value = value["structuredContent"]
        elif isinstance(value.get("result"), dict):
            value = value["result"]
        else:
            parsed = None
            content = value.get("content", [])
            if not isinstance(content, list):
                raise ValueError("Usage content wrapper is invalid")
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    try:
                        candidate = json.loads(item.get("text", ""))
                    except (TypeError, ValueError):
                        continue
                    if isinstance(candidate, dict) and any(
                        key in candidate for key in ("rateLimits", "rateLimitsByLimitId", "result")
                    ):
                        parsed = candidate
                        break
            if parsed is None:
                raise ValueError("No account rate-limit payload found")
            value = parsed
    raise ValueError("Usage wrapper nesting is unsupported")


def assess(observation, previous=None, *, unit_minutes=None, save_minutes=None,
           current_unit_id=None, stop_requested=False, pause_pending=False,
           hard_stop=False, phase="working", heavy=False,
           resuming=False, limit_ids=None, pause_floor=5, decision_at=10, now=None):
    if unit_minutes is not None and (not number(unit_minutes) or unit_minutes <= 0):
        raise ValueError("unit_minutes must be a finite positive estimate; it is not a time limit")
    if save_minutes is not None and (not number(save_minutes) or save_minutes <= 0):
        raise ValueError("save_minutes must cover documentation, summary and durable saving")
    if current_unit_id is not None and (not isinstance(current_unit_id, str) or not current_unit_id.strip()):
        raise ValueError("current_unit_id must identify the already-started unit")
    if phase not in {"working", "finishing", "paused", "completed"}:
        raise ValueError("Invalid workflow phase")
    if not number(pause_floor) or not number(decision_at) or not 0 <= pause_floor < decision_at <= 100:
        raise ValueError("Thresholds must satisfy 0 <= pause_floor < decision_at <= 100")
    now = time.time() if now is None else now
    pending = bool(stop_requested or pause_pending or phase == "finishing")
    output = {"schemaVersion": 2, "action": "unknown", "reasons": [], "warnings": [],
              "nextCheckMinutes": None, "emergency": False, "budgets": [],
              "pauseFloorPercent": pause_floor, "decisionAtPercent": decision_at,
              "checkpointBeforeNextUnit": False, "preserveFullScopeAndQuality": True,
              "pausePending": pending, "currentUnitId": current_unit_id,
              "pauseReason": "user" if stop_requested else ("pending" if pending else None)}
    reasons, warnings = output["reasons"], output["warnings"]
    if hard_stop or phase in {"paused", "completed"}:
        output.update(action="pause", pausePending=True, pauseReason="user" if hard_stop else phase)
        reasons.append("Save without advancing; a paused task has no polling interval")
        return output
    if not isinstance(observation, dict):
        reasons.append("Observation must be an object")
        return output
    model_key = observation.get("modelKey")
    if not isinstance(model_key, str) or not model_key.strip() or "unknown" in model_key.lower() or "未知" in model_key:
        heavy = True
        model_key = "unknown"
        warnings.append("Model settings unavailable; estimates use conservative account-level observations in this run")
    output["mode"] = "heavy" if heavy else "normal"
    observed = observation.get("observedAt")
    if not number(observed) or observed > now + 30 or now - observed > 120:
        reasons.append("Observation time is missing, stale, or in the future; fetch fresh usage")
        return output
    try:
        usage = unwrap(observation.get("usage"))
    except ValueError as exc:
        reasons.append(str(exc))
        return output
    permission = usage.get("ordinaryUsageAllowed")
    if permission is False:
        output["action"] = "pause"
        output["emergency"] = True
        reasons.append("Backend disallows ordinary included usage")
        return output
    if permission is not True:
        reasons.append("Backend ordinary-usage permission is unknown; recovery is unconfirmed")

    multi = usage.get("rateLimitsByLimitId")
    if isinstance(multi, dict) and multi:
        buckets = multi
    else:
        legacy = usage.get("rateLimits")
        buckets = {legacy.get("limitId") or "legacy": legacy} if isinstance(legacy, dict) else {}
    output["availableLimitIds"] = list(buckets)
    selected = list(dict.fromkeys(limit_ids or []))
    if not selected:
        if len(buckets) == 1:
            selected = list(buckets)
        else:
            reasons.append("Select confirmed applicable limit IDs; zero or multiple buckets are ambiguous")
            return output
    if any(key not in buckets for key in selected):
        reasons.append("A selected limit ID is absent from the current usage response")
        return output

    account_id = usage.get("accountId")
    scope = hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:16] if isinstance(account_id, str) and account_id else None
    current = {"observedAt": observed, "runKey": observation.get("runKey"),
               "modelKey": model_key, "accountScope": scope, "windows": []}
    output["observation"] = current
    prior = previous.get("observation", {}) if isinstance(previous, dict) else {}
    if not isinstance(prior, dict):
        prior = {}
    interval = (observed - prior["observedAt"]) / 60 if number(prior.get("observedAt")) else 0
    comparable = (
        1 <= interval <= 30 and scope is not None and scope == prior.get("accountScope")
        and isinstance(current["runKey"], str) and bool(current["runKey"])
        and current["runKey"] == prior.get("runKey")
        and isinstance(current["modelKey"], str) and bool(current["modelKey"])
        and current["modelKey"] == prior.get("modelKey")
    )
    prior_windows = prior.get("windows", [])
    if not isinstance(prior_windows, list):
        prior_windows = []
    next_check = 20
    pause = False
    unknown_window = False
    exact_budgets = []
    estimates_complete = bool(current_unit_id and unit_minutes is not None and save_minutes is not None)
    for key in selected:
        bucket = buckets[key]
        if not isinstance(bucket, dict):
            reasons.append(f"{key}: selected bucket has no readable data")
            unknown_window = True
            continue
        if bucket.get("spendControlReached") is True or bucket.get("rateLimitReachedType"):
            pause = True
            output["emergency"] = True
            reasons.append(f"{key}: backend reports a reached usage/spend limit")
        readable = 0
        for lane in ("primary", "secondary"):
            raw = bucket.get(lane)
            label = f"{key}/{lane}"
            if raw is None:
                warnings.append(f"{label}: no window reported; not counted as unused quota")
                continue
            if (not isinstance(raw, dict) or not number(raw.get("usedPercent"))
                    or not number(raw.get("windowDurationMins")) or raw["windowDurationMins"] <= 0):
                unknown_window = True
                reasons.append(f"{label}: window reading is invalid or incomplete")
                continue
            readable += 1
            used = min(100.0, max(0.0, float(raw["usedPercent"])))
            remaining = 100 - used
            duration = float(raw["windowDurationMins"])
            reset = raw.get("resetsAt") if number(raw.get("resetsAt")) else None
            window = {"limitId": key, "lane": lane, "usedPercent": used,
                      "windowDurationMins": duration, "resetsAt": reset}
            current["windows"].append(window)
            rate = None
            rate_basis = "initial-heuristic"
            rate_observed_at = None
            if comparable and reset is not None and reset > observed:
                for old in prior_windows:
                    if not isinstance(old, dict):
                        continue
                    same = all(old.get(field) == window[field] for field in ("limitId", "lane", "windowDurationMins", "resetsAt"))
                    old_used = old.get("usedPercent")
                    if same and number(old_used) and used > old_used:
                        rate = (used - old_used) / interval
                        rate_observed_at = observed
                        rate_basis = "observed-with-margin"
                        break
                    hint, hint_time = old.get("rateHint"), old.get("rateObservedAt")
                    if (same and old_used == used and number(hint) and hint > 0
                            and number(hint_time) and 0 <= observed - hint_time <= 600):
                        rate = hint
                        rate_observed_at = hint_time
                        rate_basis = "recent-positive-rate"
                        break
            long_window = duration > 1440
            if rate is not None:
                window["rateHint"] = rate
                window["rateObservedAt"] = rate_observed_at
            margin = 3 if heavy else 2
            initial = (1 if heavy else 0.5) if long_window else (3 if heavy else 2)
            minimum = (0.5 if heavy else 0.25) if long_window else (1 if heavy else 0.5)
            per_minute = margin * rate if rate is not None else initial / (3 if heavy else 5)
            cost = max(minimum, per_minute * unit_minutes) if unit_minutes is not None else None
            save_cost = max(0.25, per_minute * save_minutes) if save_minutes is not None else None
            resume_cost = 0
            if resuming:
                resume_cost = max(1 if heavy else 0.5, margin * rate if rate is not None else 0)
            threshold = pause_floor + cost + save_cost + resume_cost if cost is not None and save_cost is not None else None
            headroom = remaining - threshold if threshold is not None else None
            exact_budgets.append((remaining, threshold))
            in_band = remaining <= decision_at
            if in_band:
                pending = True
                output["pausePending"] = True
                if output["pauseReason"] is None:
                    output["pauseReason"] = "quota"
            output["budgets"].append({
                "limitId": key, "lane": lane, "remainingPercent": round(remaining, 3),
                "reservePoints": pause_floor, "unitCostPoints": round(cost, 3) if cost is not None else None,
                "saveCostPoints": round(save_cost, 3) if save_cost is not None else None, "resumeCostPoints": round(resume_cost, 3),
                "requiredPoints": round(threshold, 3) if threshold is not None else None, "ratePointsPerMinute": rate,
                "estimate": rate_basis, "decisionBand": in_band, "resetsAt": reset,
            })
            if remaining <= pause_floor:
                output["emergency"] = True
                output["checkpointBeforeNextUnit"] = True
                pause = True
                reasons.append(f"{label}: {remaining:.2f}% remaining has reached the {pause_floor:g}% saving floor")
            next_check = min(next_check, cadence_minutes(remaining))
            if in_band:
                output["checkpointBeforeNextUnit"] = True
            if headroom is not None and headroom <= 0 and not in_band:
                output["checkpointBeforeNextUnit"] = True
                warnings.append(f"{label}: save before the complete planned unit; preserve its scope, depth and verification requirements")
        if not readable:
            unknown_window = True
            reasons.append(f"{key}: no measurable quota window")
    # Once any applicable window requests stopping, budget against EVERY window,
    # including windows above 10%. A reset cannot cancel a latched stop request.
    if pending:
        output["checkpointBeforeNextUnit"] = True
        if not estimates_complete:
            pause = True
            reasons.append("No identified unfinished unit or evidence-based remaining-work/save estimate; save now")
        elif any(remaining <= required or math.isclose(remaining, required, rel_tol=0, abs_tol=1e-9)
                 for remaining, required in exact_budgets):
            pause = True
            reasons.append("Current unit plus verification, documentation and saving cannot preserve every window's floor")
    if pause:
        output["action"] = "pause"
        output["pausePending"] = True
    elif not unknown_window and permission is True and output["budgets"]:
        output["action"] = "finish_then_pause" if pending else "continue"
        output["nextCheckMinutes"] = next_check
        reasons.append("Finish only the identified current unit, then save and pause" if pending else "Continue the complete original task")
    return output


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observation", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--limit-id", action="append", dest="limit_ids")
    parser.add_argument("--unit-minutes", type=float)
    parser.add_argument("--save-minutes", type=float)
    parser.add_argument("--current-unit-id")
    parser.add_argument("--stop-requested", action="store_true")
    parser.add_argument("--pause-pending", action="store_true")
    parser.add_argument("--hard-stop", action="store_true")
    parser.add_argument("--phase", choices=("working", "finishing", "paused", "completed"), default="working")
    parser.add_argument("--control", type=Path, help="Read persisted phase/current unit/pending stop; never modifies it")
    parser.add_argument("--heavy", action="store_true")
    parser.add_argument("--resuming", action="store_true")
    parser.add_argument("--pause-floor", type=float, default=5)
    parser.add_argument("--decision-at", type=float, default=10)
    args = parser.parse_args()
    try:
        observation = json.loads(args.observation.read_text(encoding="utf-8-sig"))
        previous = json.loads(args.previous.read_text(encoding="utf-8-sig")) if args.previous else None
        if args.control:
            control = json.loads(args.control.read_text(encoding="utf-8-sig"))
            args.phase = control["phase"]
            args.pause_pending = args.pause_pending or control["pause_pending"]
            bound_id = (control.get("current_unit") or {}).get("id")
            if args.current_unit_id and args.current_unit_id != bound_id:
                raise ValueError("Current unit differs from the persisted workflow")
            args.current_unit_id = bound_id
        result = assess(observation, previous, unit_minutes=args.unit_minutes, heavy=args.heavy,
                        save_minutes=args.save_minutes, current_unit_id=args.current_unit_id,
                        stop_requested=args.stop_requested, pause_pending=args.pause_pending,
                        hard_stop=args.hard_stop, phase=args.phase,
                        resuming=args.resuming, limit_ids=args.limit_ids,
                        pause_floor=args.pause_floor, decision_at=args.decision_at)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"action": "unknown", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

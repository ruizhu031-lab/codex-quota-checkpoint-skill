#!/usr/bin/env python3
"""Decide one bounded unit from an already-fetched Codex usage observation.

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
        return 15
    if remaining > 25:
        return 10
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


def assess(observation, previous=None, *, unit_minutes=5, heavy=False,
           resuming=False, limit_ids=None, pause_floor=5, decision_at=10, now=None):
    if not number(unit_minutes) or unit_minutes <= 0:
        raise ValueError("unit_minutes must be a finite positive estimate; it is not a time limit")
    if not number(pause_floor) or not number(decision_at) or not 0 <= pause_floor < decision_at <= 100:
        raise ValueError("Thresholds must satisfy 0 <= pause_floor < decision_at <= 100")
    now = time.time() if now is None else now
    output = {"schemaVersion": 1, "action": "unknown", "reasons": [], "warnings": [],
              "nextCheckMinutes": None, "emergency": False, "budgets": [],
              "pauseFloorPercent": pause_floor, "decisionAtPercent": decision_at,
              "checkpointBeforeNextUnit": False, "preserveFullScopeAndQuality": True}
    reasons, warnings = output["reasons"], output["warnings"]
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
    next_check = 15
    pause = False
    unknown_window = False
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
            cost = max(minimum, margin * rate * unit_minutes) if rate is not None else max(minimum, initial * unit_minutes / (3 if heavy else 5))
            save_cost = max(0.25, margin * rate) if rate is not None else 0.25
            resume_cost = 0
            if resuming:
                resume_cost = max(1 if heavy else 0.5, margin * rate if rate is not None else 0)
            threshold = pause_floor + cost + save_cost + resume_cost
            headroom = remaining - threshold
            in_band = remaining <= decision_at
            output["budgets"].append({
                "limitId": key, "lane": lane, "remainingPercent": round(remaining, 3),
                "reservePoints": pause_floor, "unitCostPoints": round(cost, 3),
                "saveCostPoints": round(save_cost, 3), "resumeCostPoints": round(resume_cost, 3),
                "requiredPoints": round(threshold, 3), "ratePointsPerMinute": rate,
                "estimate": rate_basis, "decisionBand": in_band, "resetsAt": reset,
            })
            if remaining <= pause_floor:
                output["emergency"] = True
                output["checkpointBeforeNextUnit"] = True
                pause = True
                reasons.append(f"{label}: {remaining:.2f}% remaining has reached the {pause_floor:g}% saving floor")
            elif in_band and headroom <= 0:
                output["checkpointBeforeNextUnit"] = True
                pause = True
                reasons.append(f"{label}: inside {pause_floor:g}-{decision_at:g}% band; {remaining:.2f}% cannot cover {threshold:.2f} budget points")
            next_check = min(next_check, cadence_minutes(remaining))
            if in_band:
                output["checkpointBeforeNextUnit"] = True
            if headroom <= 0 and not in_band:
                output["checkpointBeforeNextUnit"] = True
                warnings.append(f"{label}: save before the complete planned unit; preserve its scope, depth and verification requirements")
        if not readable:
            unknown_window = True
            reasons.append(f"{key}: no measurable quota window")
    if pause:
        output["action"] = "pause"
    elif not unknown_window and permission is True and output["budgets"]:
        output["action"] = "continue"
        output["nextCheckMinutes"] = next_check
        reasons.append("No measured applicable window requires a pause under the configured decision band")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observation", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--limit-id", action="append", dest="limit_ids")
    parser.add_argument("--unit-minutes", type=float, default=5)
    parser.add_argument("--heavy", action="store_true")
    parser.add_argument("--resuming", action="store_true")
    parser.add_argument("--pause-floor", type=float, default=5)
    parser.add_argument("--decision-at", type=float, default=10)
    args = parser.parse_args()
    try:
        observation = json.loads(args.observation.read_text(encoding="utf-8-sig"))
        previous = json.loads(args.previous.read_text(encoding="utf-8-sig")) if args.previous else None
        result = assess(observation, previous, unit_minutes=args.unit_minutes, heavy=args.heavy,
                        resuming=args.resuming, limit_ids=args.limit_ids,
                        pause_floor=args.pause_floor, decision_at=args.decision_at)
    except (OSError, ValueError) as exc:
        print(json.dumps({"action": "unknown", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

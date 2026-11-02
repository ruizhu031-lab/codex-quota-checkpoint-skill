"""Deterministic policy and durable handoff checks; no model calls or network."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


BASE = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, BASE / "scripts" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


policy = module("assess")
checkpoint = module("checkpoint")
NOW = 1793601600


def observation(short=40, weekly=20, **fields):
    value = {"observedAt": NOW, "runKey": "task-run-1", "modelKey": "test-model|high",
             "usage": {"ordinaryUsageAllowed": True, "accountId": "fixture-private-account",
                       "rateLimitsByLimitId": {"codex": {
                           "limitId": "codex", "spendControlReached": False,
                           "rateLimitReachedType": None, "credits": {"balance": "0", "unlimited": False},
                           "primary": {"usedPercent": short, "windowDurationMins": 300, "resetsAt": NOW + 18000},
                           "secondary": {"usedPercent": weekly, "windowDurationMins": 10080, "resetsAt": NOW + 600000}}}}}
    value.update(fields)
    return value


def bucket(value):
    return value["usage"]["rateLimitsByLimitId"]["codex"]


class PolicyTests(unittest.TestCase):
    def decide(self, value=None, **options):
        return policy.assess(value if value is not None else observation(), now=options.pop("now", NOW), **options)

    def test_healthy_usage_and_zero_paid_balance(self):
        result = self.decide()
        self.assertEqual(result["action"], "continue")
        self.assertEqual(result["budgets"][0]["remainingPercent"], 60)

    def test_above_ten_percent_does_not_pause_at_old_thresholds(self):
        self.assertEqual(self.decide(observation(75, 29))["action"], "continue")

    def test_weekly_limit_can_stop_despite_full_short_window(self):
        self.assertEqual(self.decide(observation(0, 96))["action"], "pause")

    def test_missing_window_is_not_zero_usage(self):
        value = observation()
        bucket(value)["secondary"] = None
        result = self.decide(value)
        self.assertEqual(len(result["budgets"]), 1)
        self.assertTrue(result["warnings"])

    def test_incomplete_reported_window_prevents_continue(self):
        value = observation()
        bucket(value)["secondary"]["usedPercent"] = None
        self.assertEqual(self.decide(value)["action"], "unknown")

    def test_boolean_is_not_a_percentage(self):
        value = observation()
        bucket(value)["primary"]["usedPercent"] = True
        self.assertEqual(self.decide(value)["action"], "unknown")

    def test_nonfinite_reading_is_unknown(self):
        value = observation()
        bucket(value)["primary"]["usedPercent"] = float("nan")
        self.assertEqual(self.decide(value)["action"], "unknown")

    def test_backend_denial_wins_over_full_percentages(self):
        value = observation(0, 0)
        value["usage"]["ordinaryUsageAllowed"] = False
        result = self.decide(value)
        self.assertEqual(result["action"], "pause")
        self.assertTrue(result["emergency"])

    def test_unknown_permission_cannot_prove_recovery(self):
        value = observation(0, 0)
        value["usage"]["ordinaryUsageAllowed"] = None
        bucket(value)["primary"]["resetsAt"] = NOW - 1
        self.assertEqual(self.decide(value, resuming=True)["action"], "unknown")

    def test_spend_control_and_limit_state(self):
        for key, flag in (("spendControlReached", True), ("rateLimitReachedType", "usageLimit")):
            with self.subTest(key=key):
                value = observation(0, 0)
                bucket(value)[key] = flag
                self.assertEqual(self.decide(value)["action"], "pause")

    def test_stale_and_future_observations(self):
        for timestamp in (NOW - 121, NOW + 31, None):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(self.decide(observation(observedAt=timestamp))["action"], "unknown")

    def test_failed_tool_and_missing_payload(self):
        for payload in ({"isError": True}, {}, None, {"content": None}):
            value = observation(usage=payload)
            self.assertEqual(self.decide(value)["action"], "unknown")

    def test_multiple_buckets_require_confirmed_selection(self):
        value = observation()
        other = deepcopy(bucket(value))
        other["primary"]["usedPercent"] = 100
        value["usage"]["rateLimitsByLimitId"]["other-model"] = other
        self.assertEqual(self.decide(value)["action"], "unknown")
        self.assertEqual(self.decide(value, limit_ids=["codex"])["action"], "continue")
        self.assertEqual(self.decide(value, limit_ids=["codex", "other-model"])["action"], "pause")

    def test_missing_selected_bucket_is_unknown(self):
        self.assertEqual(self.decide(limit_ids=["missing"])["action"], "unknown")

    def test_multi_view_does_not_double_count_legacy(self):
        value = observation()
        value["usage"]["rateLimits"] = deepcopy(bucket(value))
        value["usage"]["rateLimits"]["primary"]["usedPercent"] = 100
        result = self.decide(value)
        self.assertEqual(result["action"], "continue")
        self.assertEqual(len(result["budgets"]), 2)

    def test_legacy_single_bucket_response(self):
        value = observation()
        value["usage"]["rateLimits"] = bucket(value)
        del value["usage"]["rateLimitsByLimitId"]
        self.assertEqual(self.decide(value)["action"], "continue")

    def test_mcp_and_json_rpc_payloads(self):
        value = observation()
        usage = value["usage"]
        for wrapper in ({"result": usage}, {"content": [{"type": "text", "text": json.dumps(usage)}]},
                        {"structuredContent": usage}):
            self.assertEqual(self.decide(observation(usage=wrapper))["action"], "continue")

    def test_heavy_and_recovery_modes_preserve_more_margin(self):
        self.assertEqual(self.decide(observation(93), unit_minutes=3)["action"], "continue")
        self.assertEqual(self.decide(observation(93), unit_minutes=3, heavy=True)["action"], "pause")
        self.assertEqual(self.decide(observation(91), unit_minutes=3, heavy=True)["action"], "continue")
        self.assertEqual(self.decide(observation(91), unit_minutes=3, heavy=True, resuming=True)["action"], "pause")

    def test_unknown_model_defaults_to_heavy_mode(self):
        result = self.decide(observation(92, modelKey="unknown"), unit_minutes=3)
        self.assertEqual(result["mode"], "heavy")
        self.assertEqual(result["action"], "pause")

    def test_real_burn_rate_accounts_for_a_large_next_unit(self):
        prior = self.decide(observation(35, observedAt=NOW - 300), now=NOW - 300)
        result = self.decide(observation(55), previous=prior)
        self.assertEqual(result["budgets"][0]["ratePointsPerMinute"], 4)
        self.assertEqual(result["action"], "continue")
        self.assertTrue(result["checkpointBeforeNextUnit"])
        self.assertTrue(result["preserveFullScopeAndQuality"])
        self.assertNotIn("suggestedUnitMinutes", result)

    def test_real_burn_rate_can_pause_only_inside_decision_band(self):
        prior = self.decide(observation(90, observedAt=NOW - 300), now=NOW - 300)
        result = self.decide(observation(92), previous=prior)
        self.assertAlmostEqual(result["budgets"][0]["ratePointsPerMinute"], 0.4)
        self.assertEqual(result["action"], "pause")

    def test_rounded_unchanged_usage_does_not_imply_free_work(self):
        prior = self.decide(observation(observedAt=NOW - 300), now=NOW - 300)
        result = self.decide(previous=prior)
        self.assertEqual(result["budgets"][0]["estimate"], "initial-heuristic")
        self.assertGreater(result["budgets"][0]["unitCostPoints"], 0)

    def test_changed_model_run_account_or_window_resets_rate(self):
        prior = self.decide(observation(35, observedAt=NOW - 300), now=NOW - 300)
        for changed in ("model", "run", "account", "reset", "decreasing"):
            with self.subTest(changed=changed):
                value = observation(55)
                if changed == "model":
                    value["modelKey"] = "different-model|high"
                elif changed == "run":
                    value["runKey"] = "next-run"
                elif changed == "account":
                    value["usage"]["accountId"] = "different-private-account"
                elif changed == "reset":
                    bucket(value)["primary"]["resetsAt"] += 10
                else:
                    bucket(value)["primary"]["usedPercent"] = 20
                result = self.decide(value, previous=prior)
                self.assertIsNone(result["budgets"][0]["ratePointsPerMinute"])

    def test_account_id_is_not_persisted(self):
        self.assertNotIn("fixture-private-account", json.dumps(self.decide()))

    def test_near_threshold_tightens_check_and_emergency_is_detected(self):
        self.assertEqual(self.decide(observation(92))["nextCheckMinutes"], 3)
        self.assertTrue(self.decide(observation(96))["emergency"])

    def test_invalid_overrides_raise_instead_of_silently_weakening_policy(self):
        for options in ({"unit_minutes": 0}, {"unit_minutes": float("inf")}, {"pause_floor": -1}, {"decision_at": 5}):
            with self.assertRaises(ValueError):
                self.decide(**options)

    def test_exact_five_percent_always_pauses(self):
        for remaining in (0, 1, 4.99, 5):
            for heavy in (False, True):
                with self.subTest(remaining=remaining, heavy=heavy):
                    result = self.decide(observation(100-remaining), heavy=heavy, unit_minutes=0.25)
                    self.assertEqual(result["action"], "pause")
                    self.assertTrue(result["emergency"])

    def test_exact_ten_percent_is_a_decision_instead_of_automatic_pause(self):
        result = self.decide(observation(90))
        self.assertEqual(result["action"], "continue")
        self.assertTrue(result["budgets"][0]["decisionBand"])
        self.assertTrue(result["checkpointBeforeNextUnit"])

    def test_above_ten_percent_never_pauses_only_due_to_budget(self):
        for remaining in (10.01, 11, 25, 30, 45, 55, 90):
            for model in ("unknown", "visible-model|high|fast"):
                with self.subTest(remaining=remaining, model=model):
                    result = self.decide(observation(100-remaining, modelKey=model), heavy=True, unit_minutes=30, resuming=True)
                    self.assertEqual(result["action"], "continue")

    def test_decision_band_checks_every_applicable_window(self):
        value = observation(0, 94)
        self.assertEqual(self.decide(value, heavy=True, unit_minutes=3)["action"], "pause")

    def test_rounded_reading_reuses_recent_positive_rate_without_flapping(self):
        first = self.decide(observation(91, observedAt=NOW-300), now=NOW-300, heavy=True, unit_minutes=3)
        second = self.decide(observation(92), previous=first, heavy=True, unit_minutes=3)
        third = self.decide(observation(92, observedAt=NOW+180), previous=second, now=NOW+180, heavy=True, unit_minutes=3)
        self.assertEqual(second["action"], "continue")
        self.assertEqual(third["action"], "continue")
        self.assertEqual(third["budgets"][0]["estimate"], "recent-positive-rate")
        self.assertEqual(second["budgets"][0]["unitCostPoints"], third["budgets"][0]["unitCostPoints"])

    def test_unknown_model_can_learn_account_rate_with_conservative_margin(self):
        first = self.decide(observation(91, modelKey="unknown", observedAt=NOW-300), now=NOW-300, unit_minutes=3)
        result = self.decide(observation(92, modelKey="unknown"), previous=first, unit_minutes=3)
        self.assertEqual(result["mode"], "heavy")
        self.assertAlmostEqual(result["budgets"][0]["ratePointsPerMinute"], 0.2)
        self.assertEqual(result["action"], "continue")

    def test_recent_rate_hint_expires_without_fresh_positive_usage(self):
        first = self.decide(observation(91, observedAt=NOW-300), now=NOW-300, heavy=True, unit_minutes=3)
        second = self.decide(observation(92), previous=first, heavy=True, unit_minutes=3)
        result = self.decide(observation(92, observedAt=NOW+660), previous=second, now=NOW+660, heavy=True, unit_minutes=3)
        self.assertEqual(result["budgets"][0]["estimate"], "initial-heuristic")

    def test_speed_setting_change_discards_old_rate(self):
        first = self.decide(observation(91, modelKey="model|high|standard", observedAt=NOW-300), now=NOW-300)
        result = self.decide(observation(92, modelKey="model|high|fast"), previous=first)
        self.assertIsNone(result["budgets"][0]["ratePointsPerMinute"])

    def test_higher_quota_checks_are_less_frequent_than_critical_band(self):
        self.assertEqual(self.decide(observation(20))["nextCheckMinutes"], 15)
        self.assertEqual(self.decide(observation(20), heavy=True, unit_minutes=3)["nextCheckMinutes"], 15)
        self.assertEqual(self.decide(observation(92))["nextCheckMinutes"], 3)

    def test_frequency_boundaries_and_lowest_window(self):
        for remaining, minutes in ((51,15),(50,10),(26,10),(25,5),(11,5),(10,3)):
            for heavy in (False,True):
                result = self.decide(observation(100-remaining), heavy=heavy, unit_minutes=0.25)
                self.assertEqual(result["nextCheckMinutes"], minutes)
        self.assertEqual(self.decide(observation(0,60))["nextCheckMinutes"],10)

    def test_large_complete_unit_is_not_time_capped_or_shrunk(self):
        result = self.decide(observation(20),unit_minutes=120,heavy=True)
        self.assertEqual(result["action"],"continue")
        self.assertTrue(result["preserveFullScopeAndQuality"])
        self.assertNotIn("suggestedUnitMinutes",result)
        self.assertEqual(result["nextCheckMinutes"],15)


def state():
    return {"status": "paused_quota", "objective": "完成项目并通过原验收标准",
            "requirements": ["保留用户原修改"], "decisions": ["沿用已有接口，避免破坏调用方"],
            "completed": ["已保存修改"], "in_progress": ["尚未运行相关测试"],
            "next_step": "读取 project.txt，执行相关验证，再完成下一项",
            "verification": ["未验证：本测试夹具只验证交接保存"], "open_questions": [],
            "model_context": "fixture-model|high", "processes": [], "references": [],
            "artifacts": ["project.txt"], "quota_summary": "夹具读数；短窗口预算不足"}


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        testing_root = Path.cwd().resolve()
        self.temporary = tempfile.TemporaryDirectory(prefix="quota-checkpoint-test-", dir=testing_root)
        def cleanup():
            target = Path(self.temporary.name).resolve()
            if target.parent != testing_root or not target.name.startswith("quota-checkpoint-test-"):
                raise ValueError("Refusing cleanup outside the verified test workspace")
            for attempt in range(5):
                try:
                    self.temporary.cleanup()
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.1 * (2 ** attempt))
        self.addCleanup(cleanup)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        (self.root / "project.txt").write_text("original 用户资料\n", encoding="utf-8")
        self.task = "test-project-1"

    def save(self, value=None):
        return checkpoint.save_checkpoint(self.root, self.task, state() if value is None else value)

    def verify(self):
        return checkpoint.verify_checkpoint(self.root, self.task)

    def test_roundtrip_preserves_meaning_and_actual_artifact(self):
        saved = self.save()
        result = self.verify()
        self.assertTrue(result["integrity_ok"])
        self.assertEqual(result["unchanged"], ["project.txt"])
        self.assertEqual(result["changed"], [])
        self.assertIn("原验收标准", Path(saved["handoff"]).read_text(encoding="utf-8"))
        self.assertEqual((self.root / "project.txt").read_text(encoding="utf-8"), "original 用户资料\n")

    def test_versions_preserve_old_checkpoints(self):
        first = self.save()
        second = self.save()
        self.assertNotEqual(first["versionDirectory"], second["versionDirectory"])
        self.assertTrue(Path(first["handoff"]).exists())
        self.assertEqual(self.verify()["versionDirectory"], second["versionDirectory"])

    def test_missing_artifact_cannot_replace_trusted_checkpoint(self):
        saved = self.save()
        value = state()
        value["artifacts"] = ["missing.txt"]
        with self.assertRaises(ValueError):
            self.save(value)
        self.assertEqual(self.verify()["versionDirectory"], saved["versionDirectory"])

    def test_failed_pointer_publication_preserves_trusted_latest(self):
        saved = self.save()
        replace = checkpoint.os.replace
        def fail_pointer(source, destination):
            if Path(destination).name == "LATEST":
                raise PermissionError("simulated pointer publication failure")
            return replace(source, destination)
        with mock.patch.object(checkpoint.os, "replace", side_effect=fail_pointer):
            with self.assertRaises(PermissionError):
                self.save()
        self.assertEqual(self.verify()["versionDirectory"], saved["versionDirectory"])

    def test_failed_write_preserves_trusted_latest(self):
        saved = self.save()
        with mock.patch.object(checkpoint, "write_synced", side_effect=PermissionError("simulated write failure")):
            with self.assertRaises(PermissionError):
                self.save()
        self.assertEqual(self.verify()["versionDirectory"], saved["versionDirectory"])

    def test_changed_user_work_is_reported_without_overwriting(self):
        self.save()
        file = self.root / "project.txt"
        file.write_text("user changed it", encoding="utf-8")
        result = self.verify()
        self.assertTrue(result["integrity_ok"])
        self.assertEqual(result["changed"], ["project.txt"])
        self.assertEqual(file.read_text(encoding="utf-8"), "user changed it")

    def test_deleted_artifacts_are_reported(self):
        self.save()
        (self.root / "project.txt").unlink()
        self.assertEqual(self.verify()["missing"], ["project.txt"])

    def test_corrupted_handoff_is_not_reported_as_intact(self):
        saved = self.save()
        Path(saved["handoff"]).write_text("corrupted", encoding="utf-8")
        self.assertFalse(self.verify()["integrity_ok"])

    def test_checkpoint_path_traversal_is_rejected(self):
        (self.root.parent / "outside.txt").write_text("outside", encoding="utf-8")
        value = state()
        value["artifacts"] = ["../outside.txt"]
        with self.assertRaises(ValueError):
            self.save(value)
        with self.assertRaises(ValueError):
            checkpoint.save_checkpoint(self.root, "../other-task", state())

    def test_pointer_path_traversal_is_rejected(self):
        saved = self.save()
        (Path(saved["taskDirectory"]) / "LATEST").write_text("../../outside", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.verify()

    def test_minimum_evidence_and_required_fields_are_enforced(self):
        for key, replacement in (("verification", []), ("objective", ""), ("next_step", "")):
            value = state()
            value[key] = replacement
            with self.assertRaises(ValueError):
                self.save(value)

    def test_moved_project_can_be_verified_and_movement_is_explicit(self):
        self.save()
        moved = self.root.parent / "moved-project"
        shutil.copytree(self.root, moved)
        result = checkpoint.verify_checkpoint(moved, self.task)
        self.assertTrue(result["rootMoved"])
        self.assertTrue(result["integrity_ok"])
        self.assertEqual(result["changed"], [])

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_git_snapshot_ignores_its_own_progress_files(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
        git("init")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "--allow-empty", "-m", "isolated fixture")
        self.save()
        result = self.verify()
        self.assertTrue(result["savedGit"]["available"])
        self.assertFalse(result["gitChanged"])

    def test_cli_pause_is_a_normal_decision_and_bad_json_is_an_error(self):
        file = self.root / "observation.json"
        value = observation(96)
        value["observedAt"] = time.time()
        bucket(value)["primary"]["resetsAt"] = time.time() + 18000
        file.write_text(json.dumps(value), encoding="utf-8")
        command = [sys.executable, "-X", "utf8", str(BASE / "scripts" / "assess.py"), str(file)]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["action"], "pause")
        file.write_text("bad json", encoding="utf-8")
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

import copy
import json
from pathlib import Path

import pytest
import yaml

from pg_rehearse.analysis.locks import lock_coverage, lock_summary
from pg_rehearse.analysis.performance import compare_performance
from pg_rehearse.analysis.plans import normalize_plan
from pg_rehearse.benchmarks.statistics import summarize
from pg_rehearse.config import load_config
from pg_rehearse.errors import ConfigurationError
from pg_rehearse.models import BenchmarkEvidence, ContentionResult, TimingSample
from pg_rehearse.worker_protocol import (
    WorkerEvidence,
    experiment_id,
    experiment_tasks,
    task_database,
)


@pytest.mark.parametrize(
    "field,value",
    [
        ("benchmark", {"operations": ["missing"]}),
        ("benchmark", {"operations": ["get-user", "get-user"]}),
        ("benchmark", {"operations": ["get-user"], "samples": True}),
        ("benchmark", {"operations": ["get-user"], "trials": 6}),
        ("benchmark", {"operations": ["get-user"], "ratio": 1.0}),
        ("plans", {"operations": ["get-user"], "analyze": "yes"}),
        ("plans", {"operations": ["unknown"]}),
        (
            "contention",
            {
                "blocker": {"id": "bad", "sql": "SELECT id FROM users", "expect": {"row_count": 2}},
                "probe": {"id": "probe", "sql": "SELECT id FROM users", "expect": {"row_count": 2}},
            },
        ),
    ],
)
def test_diagnostic_inputs_fail_before_allocation(
    rehearsal_project: Path, field: str, value: object
) -> None:
    path = rehearsal_project / "control.yml"
    data = yaml.safe_load(path.read_text())
    data[field] = value
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_contention_requires_observation_budget_inside_lock_deadline(
    rehearsal_project: Path,
) -> None:
    path = rehearsal_project / "contention.yml"
    data = yaml.safe_load(path.read_text())
    data["contention"]["observe_ms"] = 1000
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigurationError, match="observe_ms"):
        load_config(path)


def test_benchmark_order_and_database_identity_are_bounded(rehearsal_project: Path) -> None:
    loaded = load_config(rehearsal_project / "benchmark.yml")
    tasks = [t for t in experiment_tasks(loaded) if t[0] == "benchmark"]
    assert tasks[:4] == [
        ("benchmark", 1, "control_a"),
        ("benchmark", 1, "control_b"),
        ("benchmark", 1, "baseline"),
        ("benchmark", 1, "candidate"),
    ]
    assert [t[2] for t in tasks[4:8]] == ["candidate", "baseline", "control_b", "control_a"]
    assert len({task_database("a" * 32, *t) for t in tasks}) == 20
    assert all(len(task_database("a" * 32, *t)) < 64 for t in tasks)
    for task, trial, arm in [
        ("unknown", None, None),
        ("benchmark", None, None),
        ("benchmark", True, "baseline"),
        ("post_deployed", 1, "baseline"),
    ]:
        with pytest.raises(ValueError):
            experiment_id(task, trial, arm)


def test_missing_observation_does_not_mean_no_locks() -> None:
    result = ContentionResult(actor_pids={}, poll_ms=50)
    assert "contention/observation" in lock_coverage(result).missing
    summary = lock_summary(result)
    assert summary["sample_count"] == 0 and summary["first_wait_ms"] is None


def test_plan_normalization_ignores_timings_and_literals_and_retains_original() -> None:
    raw = {
        "Plan": {
            "Node Type": "Seq Scan",
            "Relation Name": "orders",
            "Plan Rows": 100,
            "Filter": "(status = 'private-token'::text)",
            "Unknown Future Field": "retained",
        },
        "Execution Time": 4.5,
    }
    original = copy.deepcopy(raw)
    changed = copy.deepcopy(raw)
    changed["Execution Time"] = 99
    changed["Plan"]["Plan Rows"] = 1
    changed["Plan"]["Filter"] = "(status = 'another-secret'::text)"
    before, after = normalize_plan(raw), normalize_plan(changed)
    assert before["sha256"] == after["sha256"]
    assert before["metrics"]["0"]["Plan Rows"] == 100
    assert raw == original and "private-token" not in json.dumps(before)
    changed["Plan"]["Node Type"] = "Index Scan"
    changed["Plan"]["Index Name"] = "orders_idx"
    assert before["sha256"] != normalize_plan(changed)["sha256"]


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"Plan": {}},
        {"Plan": {"Node Type": "Seq Scan", "Plans": {}}},
        {"Plan": {"Node Type": "Seq Scan", "Filter": 10}},
    ],
)
def test_malformed_plans_are_not_comparable(raw: dict) -> None:
    with pytest.raises(ValueError):
        normalize_plan(raw)


def test_timings_keep_warmups_and_timeouts_out_of_success_percentiles() -> None:
    samples = [
        TimingSample(
            operation_id="q",
            iteration=0,
            warmup=warmup,
            elapsed_ms=ms,
            success=ok,
            error_kind=None if ok else "sql_error",
            sqlstate=None if ok else "57014",
        )
        for warmup, ms, ok in [
            (True, 10000, True),
            (False, 2, True),
            (False, 4, True),
            (False, 100, False),
        ]
    ]
    result = summarize(samples)
    assert result["warmups"] == 1 and result["successful"] == 2 and result["timeouts"] == 1
    assert result["median_ms"] == 3 and result["p95_ms"] == 4
    assert summarize([])["p95_ms"] is None


@pytest.mark.parametrize(
    "variant,status",
    [
        ("regression", "regression_warning"),
        ("few", "insufficient"),
        ("timeout", "insufficient"),
        ("control_noise", "noisy"),
        ("zero", "insufficient"),
        ("unchanged", "no_regression_observed"),
    ],
)
def test_advisory_rule_requires_repeats_samples_and_unchanged_controls(
    rehearsal_project: Path, variant: str, status: str
) -> None:
    loaded = load_config(rehearsal_project / "benchmark.yml")
    receipts = []
    for task, trial, arm in experiment_tasks(loaded):
        if task != "benchmark" or variant == "few" and trial == 5:
            continue
        ms = 30.0 if arm == "candidate" and variant != "unchanged" else 10.0
        if variant == "control_noise" and arm == "control_b":
            ms = 30.0
        if variant == "zero" and arm == "baseline":
            ms = 0.0
        samples = [
            TimingSample(
                operation_id="list-orders", iteration=i, warmup=warmup, elapsed_ms=ms, success=True
            )
            for warmup, count in ((True, 50), (False, 200))
            for i in range(count)
        ]
        if variant == "timeout" and arm == "candidate":
            samples[-1].success = False
            samples[-1].error_kind = "sql_error"
            samples[-1].sqlstate = "57014"
        receipts.append(
            WorkerEvidence(
                run_id="a" * 32,
                completion="complete",
                input_hashes=[],
                roles=[],
                task=task,
                trial=trial,
                arm=arm,
                benchmark=BenchmarkEvidence(
                    samples=samples, environment={}, schedule_sha256="b" * 64
                ),
            )
        )
    arms, outcomes = compare_performance(loaded, receipts)
    assert outcomes[0]["status"] == status
    assert arms and arms[0]["samples"]


def test_plan_sort_direction_and_join_structure_are_meaningful() -> None:
    raw = {
        "Plan": {
            "Node Type": "Sort",
            "Sort Key": ["orders.id DESC"],
            "Plans": [{"Node Type": "Seq Scan", "Relation Name": "orders"}],
        }
    }
    changed = copy.deepcopy(raw)
    changed["Plan"]["Sort Key"] = ["orders.id ASC"]
    assert normalize_plan(raw)["sha256"] != normalize_plan(changed)["sha256"]
    changed["Plan"]["Total Cost"] = float("nan")
    with pytest.raises(ValueError):
        normalize_plan(changed)


def test_passing_model_rejects_unobserved_or_unreleased_contention() -> None:
    from pg_rehearse.models import RunResult

    with pytest.raises(ValueError, match="contention actors"):
        RunResult(
            run_id="test",
            completion="complete",
            verdict="pass",
            cleanup="complete",
            coverage={"required": ["check"], "completed": ["check"]},
            contention=ContentionResult(actor_pids={}, poll_ms=50),
        )

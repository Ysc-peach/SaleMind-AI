"""Opt-in, in-memory evaluation counters; never store prompts or responses."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from threading import Lock


_observer = ContextVar("solution_evaluation_observer", default=None)


class BenchmarkEvaluationReport:
    def __init__(self):
        self._lock = Lock()
        self._data = {
            "provider_availability": {name: {"status": "NOT_REACHED", "success": 0, "failure": 0}
                                      for name in ("embedding", "generation", "verifier")},
            "generation_contract_validity": {name: {"status": "NOT_REACHED", "attempts": 0, "parser_attempts": 0}
                                             for name in ("core", "implementation", "assurance")},
            "global_structure": {"status": "NOT_REACHED"},
            "deterministic_admission": {"status": "NOT_REACHED"},
            "qwen_admission": {"status": "NOT_REACHED", "ADMISSIBLE": 0, "INADMISSIBLE": 0,
                               "ATOMIC": 0, "COMPOUND": 0},
            "assembly": {"status": "NOT_REACHED"},
            "persistence": {"status": "NOT_REACHED", "solution_persisted": False,
                            "provenance_persisted": False},
            "final_solution_quality": {"status": "NOT_EVALUATED"},
        }

    def observe(self, event, **metadata):
        # Explicit event/field allowlists: arbitrary content is never retained.
        with self._lock:
            if event in {"embedding_provider", "generation_provider", "verifier_provider"}:
                role = event.removesuffix("_provider")
                item = self._data["provider_availability"][role]
                success = metadata.get("success") is True
                item["success" if success else "failure"] += 1
                item["status"] = "FAIL" if item["failure"] else "PASS"
                category = metadata.get("category")
                if isinstance(category, str) and category.isidentifier():
                    item.setdefault("failure_categories", []).append(category)
                if role == "generation" and not success:
                    phase = metadata.get("phase")
                    if phase in self._data["generation_contract_validity"]:
                        self._data["generation_contract_validity"][phase]["status"] = "BLOCKED_PROVIDER"
                if role == "generation":
                    phase = metadata.get("phase")
                    if phase in self._data["generation_contract_validity"]:
                        self._data["generation_contract_validity"][phase]["attempts"] += 1
                if role == "verifier" and not success:
                    if self._data["qwen_admission"]["status"] != "FAIL":
                        self._data["qwen_admission"]["status"] = "BLOCKED_PROVIDER"
            elif event.endswith("_started") and event.removesuffix("_started") in {
                "deterministic_admission", "assembly", "persistence",
            }:
                self._data[event.removesuffix("_started")]["status"] = "RUNNING"
            elif event == "generation_parser":
                phase = metadata.get("phase")
                if phase not in self._data["generation_contract_validity"]:
                    return
                item = self._data["generation_contract_validity"][phase]
                item["parser_attempts"] += 1
                item["attempts"] = max(item["attempts"], item["parser_attempts"])
                item["status"] = "PASS" if metadata.get("success") is True else "FAIL"
                if isinstance(metadata.get("count"), int):
                    item["count"] = metadata["count"]
                # Categories originate only from formal contract failures.
                category = metadata.get("category")
                if isinstance(category, str) and category.isidentifier():
                    item.setdefault("rejected_attempt_categories", []).append(category)
            elif event == "verifier_verdict":
                item = self._data["qwen_admission"]
                for field, allowed in (("decision", ("ADMISSIBLE", "INADMISSIBLE")),
                                       ("atomicity", ("ATOMIC", "COMPOUND"))):
                    value = metadata.get(field)
                    if value in allowed:
                        item[value] += 1
                if metadata.get("veto") is True:
                    item["status"] = "FAIL"
            elif event in {"global_structure", "deterministic_admission", "verifier_admission", "assembly", "persistence"}:
                key = "qwen_admission" if event == "verifier_admission" else event
                item = self._data[key]
                item["status"] = "PASS" if metadata.get("success") is True else "FAIL"
                if event == "global_structure" and isinstance(metadata.get("count"), int):
                    item["count"] = metadata["count"]
                if event == "persistence":
                    item["solution_persisted"] = metadata.get("success") is True
                    provenance = metadata.get("provenance")
                    item["provenance_persisted"] = provenance if isinstance(provenance, bool) else None

    def to_dict(self):
        with self._lock:
            return deepcopy(self._data)

    def finish_failure(self):
        """Mark only entered stages failed, not unexecuted downstream stages."""
        with self._lock:
            for key in ("deterministic_admission", "assembly", "persistence"):
                if self._data[key]["status"] == "RUNNING":
                    self._data[key]["status"] = "FAIL"

    def set_quality(self, *, score, rubric_version, hard_gates):
        with self._lock:
            if self._data["persistence"]["status"] != "PASS":
                raise ValueError("Quality requires a persisted final solution")
            if not isinstance(score, (int, float)) or not 0 <= score <= 100:
                raise ValueError("Invalid quality score")
            self._data["final_solution_quality"] = {
                "status": "EVALUATED", "score": score, "rubric_version": rubric_version,
                "hard_gates": dict(hard_gates),
            }


@contextmanager
def evaluation_scope(report):
    token = _observer.set(report)
    try:
        yield report
    finally:
        _observer.reset(token)


def emit_evaluation(event, **metadata):
    report = _observer.get()
    if report is not None:
        report.observe(event, **metadata)

"""Mutation-style flakiness injection operators with known labels and root causes."""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class InjectedMutation:
    """Metadata for an injected synthetic mutant."""

    mutant_id: str
    target_file: str
    target_function: str
    category: Literal["timing", "shared_state", "randomness", "time_tz"]
    label: Literal["flaky", "real_fail"]
    description: str
    original_code: str
    mutated_code: str


class MutationOperator(ABC):
    """Abstract base class for mutation operators inserting specific flakiness patterns."""

    @property
    @abstractmethod
    def category(self) -> Literal["timing", "shared_state", "randomness", "time_tz"]:
        raise NotImplementedError

    @abstractmethod
    def apply(self, source_code: str, target_func_name: str) -> InjectedMutation | None:
        """Inject mutation into target function."""
        raise NotImplementedError


class SleepRaceOperator(MutationOperator):
    """Inserts a thread timing race condition using uncoordinated sleep."""

    @property
    def category(self) -> Literal["timing"]:
        return "timing"

    def apply(self, source_code: str, target_func_name: str) -> InjectedMutation | None:
        tree = ast.parse(source_code)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_func_name:
                func_node = node
                break

        if func_node is None:
            return None

        # Injection snippet: starts background worker with 0.05s sleep while test only sleeps 0.02s
        mutation_lines = [
            "    # Injected sleep race mutation by FlakeGuard",
            "    import threading, time",
            "    _race_flag = [False]",
            "    def _bg_job():",
            "        time.sleep(0.04)",
            "        _race_flag[0] = True",
            "    _th = threading.Thread(target=_bg_job)",
            "    _th.start()",
            "    time.sleep(0.02)",
            "    assert _race_flag[0] is True, 'Sleep race: background worker did not finish in time'",
        ]
        injected_block = "\n".join(mutation_lines)

        lines = source_code.splitlines()
        # Insert after def line
        insert_idx = func_node.lineno  # 1-indexed, so inserting at lineno puts it as the first statement in func
        new_lines = lines[:insert_idx] + [injected_block] + lines[insert_idx:]
        mutated_code = "\n".join(new_lines)

        return InjectedMutation(
            mutant_id=f"mutant_timing_{target_func_name}",
            target_file="",
            target_function=target_func_name,
            category="timing",
            label="flaky",
            description="Injected asynchronous thread race with insufficient sleep delay",
            original_code=source_code,
            mutated_code=mutated_code,
        )


class SharedStateOperator(MutationOperator):
    """Inserts uncleaned module/global mutable state dependency."""

    @property
    def category(self) -> Literal["shared_state"]:
        return "shared_state"

    def apply(self, source_code: str, target_func_name: str) -> InjectedMutation | None:
        tree = ast.parse(source_code)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_func_name:
                func_node = node
                break

        if func_node is None:
            return None

        mutation_lines = [
            "    # Injected shared state mutation by FlakeGuard",
            "    global _FLAKEGUARD_SHARED_CACHE",
            "    try:",
            "        _FLAKEGUARD_SHARED_CACHE['count'] += 1",
            "    except (NameError, KeyError):",
            "        _FLAKEGUARD_SHARED_CACHE = {'count': 1}",
            "    assert _FLAKEGUARD_SHARED_CACHE['count'] == 1, 'Shared state polluted across runs'",
        ]
        injected_block = "\n".join(mutation_lines)

        lines = source_code.splitlines()
        insert_idx = func_node.lineno
        new_lines = lines[:insert_idx] + [injected_block] + lines[insert_idx:]
        mutated_code = "\n".join(new_lines)

        return InjectedMutation(
            mutant_id=f"mutant_shared_{target_func_name}",
            target_file="",
            target_function=target_func_name,
            category="shared_state",
            label="flaky",
            description="Injected module-level dirty cache without teardown",
            original_code=source_code,
            mutated_code=mutated_code,
        )


class RandomnessOperator(MutationOperator):
    """Inserts unseeded random threshold check."""

    @property
    def category(self) -> Literal["randomness"]:
        return "randomness"

    def apply(self, source_code: str, target_func_name: str) -> InjectedMutation | None:
        tree = ast.parse(source_code)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_func_name:
                func_node = node
                break

        if func_node is None:
            return None

        mutation_lines = [
            "    # Injected randomness mutation by FlakeGuard",
            "    import random",
            "    assert random.random() < 0.85, 'Unseeded random value exceeded threshold'",
        ]
        injected_block = "\n".join(mutation_lines)

        lines = source_code.splitlines()
        insert_idx = func_node.lineno
        new_lines = lines[:insert_idx] + [injected_block] + lines[insert_idx:]
        mutated_code = "\n".join(new_lines)

        return InjectedMutation(
            mutant_id=f"mutant_random_{target_func_name}",
            target_file="",
            target_function=target_func_name,
            category="randomness",
            label="flaky",
            description="Injected unseeded random probability assertion",
            original_code=source_code,
            mutated_code=mutated_code,
        )


class TimeTZOperator(MutationOperator):
    """Inserts system clock time-of-day or timezone dependency."""

    @property
    def category(self) -> Literal["time_tz"]:
        return "time_tz"

    def apply(self, source_code: str, target_func_name: str) -> InjectedMutation | None:
        tree = ast.parse(source_code)
        func_node = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == target_func_name:
                func_node = node
                break

        if func_node is None:
            return None

        mutation_lines = [
            "    # Injected time/timezone mutation by FlakeGuard",
            "    from datetime import datetime",
            "    _hour = datetime.now().hour",
            "    assert 8 <= _hour < 18, f'Outside business hours: hour={_hour}'",
        ]
        injected_block = "\n".join(mutation_lines)

        lines = source_code.splitlines()
        insert_idx = func_node.lineno
        new_lines = lines[:insert_idx] + [injected_block] + lines[insert_idx:]
        mutated_code = "\n".join(new_lines)

        return InjectedMutation(
            mutant_id=f"mutant_time_{target_func_name}",
            target_file="",
            target_function=target_func_name,
            category="time_tz",
            label="flaky",
            description="Injected daytime clock dependency (fails at night)",
            original_code=source_code,
            mutated_code=mutated_code,
        )

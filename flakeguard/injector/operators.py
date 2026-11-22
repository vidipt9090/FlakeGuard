"""Mutation-style fault injection operators with known labels and root causes.

Every operator inserts a block as the first statement of one test function or method. Each one is meant to give a
fault that is, by construction, one of:

* timing        intermittent: a worker sleeps a random 0.01 to 0.04 s, the test waits 0.02 s and then checks it finished
* shared_state  order-triggered: all mutated tests of one module share a counter, and only the first to run passes
* randomness    intermittent: ``random.random() < 0.85`` is asserted, so it fails about 15% of runs
* time_tz       clock-triggered: asserts the local hour is 8 to 17, so it fails outside those hours
* order_dep     order-triggered: the victim passes only if its setup test ran earlier in the same process
* real_fail     none of the above: a check that always fails (a real failure, label ``real_fail``)

``tests/test_injector_and_baselines.py`` and ``tests/test_injector_behaviour.py`` check these properties by running the
mutated code, not only by looking for text in it.
"""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

Category = Literal["timing", "shared_state", "randomness", "time_tz", "order_dep", "real_fail"]


@dataclass(frozen=True)
class InjectedMutation:
    """Metadata for an injected synthetic mutant."""

    mutant_id: str
    target_file: str
    target_function: str
    category: Category
    label: Literal["flaky", "real_fail"]
    description: str
    original_code: str
    mutated_code: str


def find_function(tree: ast.AST, name: str, class_name: str | None = None) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The function called ``name``; inside class ``class_name`` when one is given, otherwise the first one found."""
    if class_name is None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return node
        return None
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == class_name:
            for item in cls.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
                    return item
    return None


def insert_block(source_code: str, func: ast.FunctionDef | ast.AsyncFunctionDef, block: list[str]) -> str | None:
    """Put ``block`` before the first statement of ``func``, indented like that statement.

    Returns None when the first statement is on the ``def`` line (a one-line function), which cannot take a block.
    """
    first = func.body[0]
    if first.lineno == func.lineno:
        return None
    indent = " " * first.col_offset
    lines = source_code.splitlines()
    at = first.lineno - 1
    inserted = [indent + line if line else line for line in block]
    out = "\n".join(lines[:at] + inserted + lines[at:])
    return out + "\n" if source_code.endswith("\n") else out


class MutationOperator(ABC):
    """Abstract base class for mutation operators inserting a specific fault into one test."""

    @property
    @abstractmethod
    def category(self) -> Category:
        raise NotImplementedError

    description = ""
    label: Literal["flaky", "real_fail"] = "flaky"
    prefix = "mutant"

    @abstractmethod
    def block(self) -> list[str]:
        """The statements to insert, written at indentation 0."""
        raise NotImplementedError

    def apply(self, source_code: str, target_func_name: str, class_name: str | None = None) -> InjectedMutation | None:
        func = find_function(ast.parse(source_code), target_func_name, class_name)
        if func is None:
            return None
        mutated = insert_block(source_code, func, self.block())
        if mutated is None:
            return None
        where = f"{class_name}_{target_func_name}" if class_name else target_func_name
        return InjectedMutation(
            mutant_id=f"{self.prefix}_{where}", target_file="", target_function=target_func_name,
            category=self.category, label=self.label, description=self.description,
            original_code=source_code, mutated_code=mutated,
        )


class SleepRaceOperator(MutationOperator):
    """A background worker takes a random 0.01 to 0.04 s; the test waits 0.02 s and asserts the worker finished.

    (The first version slept a fixed 0.04 s against a 0.02 s wait, so it failed every time; that is a deterministic
    failure, not a race, and contradicted its ``flaky`` label.)
    """

    category = "timing"
    prefix = "mutant_timing"
    description = "Injected thread race: a worker takes a random 0.01 to 0.04 s, the test waits 0.02 s"

    def block(self) -> list[str]:
        return [
            "# Injected sleep race mutation by FlakeGuard",
            "import random as _fg_random, threading, time",
            "_race_flag = [False]",
            "def _bg_job():",
            "    time.sleep(_fg_random.uniform(0.01, 0.04))",
            "    _race_flag[0] = True",
            "_th = threading.Thread(target=_bg_job)",
            "_th.start()",
            "time.sleep(0.02)",
            "assert _race_flag[0] is True, 'Sleep race: background worker did not finish in time'",
        ]


class SharedStateOperator(MutationOperator):
    """All mutated tests of one module share one counter; only the first to run in the process sees it at 1."""

    category = "shared_state"
    prefix = "mutant_shared"
    description = "Injected module-level counter never reset: every mutated test of the module after the first one fails"

    def block(self) -> list[str]:
        return [
            "# Injected shared state mutation by FlakeGuard",
            "global _FLAKEGUARD_SHARED_CACHE",
            "try:",
            "    _FLAKEGUARD_SHARED_CACHE['count'] += 1",
            "except (NameError, KeyError):",
            "    _FLAKEGUARD_SHARED_CACHE = {'count': 1}",
            "assert _FLAKEGUARD_SHARED_CACHE['count'] == 1, 'Shared state polluted by an earlier test'",
        ]


class RandomnessOperator(MutationOperator):
    """Asserts an unseeded random number is below 0.85: fails about 15% of runs."""

    category = "randomness"
    prefix = "mutant_random"
    description = "Injected unseeded random probability assertion (fails about 15% of runs)"

    def block(self) -> list[str]:
        return [
            "# Injected randomness mutation by FlakeGuard",
            "import random",
            "assert random.random() < 0.85, 'Unseeded random value exceeded threshold'",
        ]


class TimeTZOperator(MutationOperator):
    """Asserts the local hour is 8 to 17: passes in the daytime, fails at night."""

    category = "time_tz"
    prefix = "mutant_time"
    description = "Injected local-clock dependency: fails when the local hour is outside 8 to 17"

    def block(self) -> list[str]:
        return [
            "# Injected time/timezone mutation by FlakeGuard",
            "from datetime import datetime",
            "_hour = datetime.now().hour",
            "assert 8 <= _hour < 18, f'Outside business hours: hour={_hour}'",
        ]


class OrderDependenceOperator(MutationOperator):
    """A setup test sets a module flag; the victim passes only if the setup test ran earlier in the process.

    ``apply`` mutates the victim. ``apply_setup`` mutates the setup test (which keeps passing, and is not flaky).
    """

    category = "order_dep"
    prefix = "mutant_order"
    description = "Injected order dependence: passes only if its setup test ran earlier in the same process"

    def block(self) -> list[str]:
        return [
            "# Injected order dependence mutation by FlakeGuard (victim)",
            "assert globals().get('_FLAKEGUARD_ORDER_READY') is True, 'Order dependence: the setup test has not run yet'",
        ]

    def setup_block(self) -> list[str]:
        return [
            "# Injected order dependence mutation by FlakeGuard (setup)",
            "global _FLAKEGUARD_ORDER_READY",
            "_FLAKEGUARD_ORDER_READY = True",
        ]

    def apply_setup(self, source_code: str, target_func_name: str, class_name: str | None = None) -> str | None:
        func = find_function(ast.parse(source_code), target_func_name, class_name)
        return None if func is None else insert_block(source_code, func, self.setup_block())


class RealFailureOperator(MutationOperator):
    """A check that always fails: a real failure, not a flaky one."""

    category = "real_fail"
    label = "real_fail"
    prefix = "mutant_real"
    description = "Injected deterministic failure"

    def block(self) -> list[str]:
        return [
            "# Injected real failure mutation by FlakeGuard",
            "assert 1 + 1 == 3, 'Injected real failure: this check never passes'",
        ]

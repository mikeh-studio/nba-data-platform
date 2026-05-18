from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.formulas import (
    FormulaError,
    compile_formula_sql,
    evaluate_formula,
    extract_formula_variables,
)


def test_evaluate_formula_uses_safe_arithmetic() -> None:
    value = evaluate_formula("pts + ast * 2", {"pts": "28", "ast": "7"})

    assert value == 42


def test_evaluate_formula_returns_none_for_missing_or_zero_division() -> None:
    assert evaluate_formula("pts + ast * 2", {"pts": "28"}) is None
    assert evaluate_formula("pts / ast", {"pts": "28", "ast": "0"}) is None


def test_compile_formula_sql_maps_only_approved_columns() -> None:
    sql = compile_formula_sql(
        "pts + ast * 2",
        {"pts": "avg_pts", "ast": "avg_ast"},
    )

    assert sql == "((avg_pts) + (((avg_ast) * (2.0))))"


def test_formula_rejects_calls_and_unknown_sql_variables() -> None:
    with pytest.raises(FormulaError):
        extract_formula_variables("__import__('os').system('echo unsafe')")

    with pytest.raises(FormulaError):
        compile_formula_sql("pts + unsafe", {"pts": "avg_pts"})

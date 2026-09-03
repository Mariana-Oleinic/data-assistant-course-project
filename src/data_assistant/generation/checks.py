"""Safe evaluation helpers for common PostgreSQL CHECK expressions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError


def _literal(expression: exp.Expression, row: dict[str, Any]) -> Any:
    if isinstance(expression, exp.Column):
        return row.get(expression.name)
    if isinstance(expression, exp.Null):
        return None
    if isinstance(expression, exp.Boolean):
        return expression.this
    if isinstance(expression, exp.Literal):
        if expression.is_string:
            return expression.this
        try:
            return Decimal(expression.this)
        except InvalidOperation:
            return expression.this
    raise ValueError("Unsupported value in CHECK constraint.")


def _evaluate(expression: exp.Expression, row: dict[str, Any]) -> bool | None:
    if isinstance(expression, exp.Paren):
        return _evaluate(expression.this, row)
    if isinstance(expression, exp.And):
        left, right = _evaluate(expression.this, row), _evaluate(expression.expression, row)
        if left is False or right is False:
            return False
        return None if left is None or right is None else True
    if isinstance(expression, exp.Or):
        left, right = _evaluate(expression.this, row), _evaluate(expression.expression, row)
        if left is True or right is True:
            return True
        return None if left is None or right is None else False
    if isinstance(expression, exp.Not):
        result = _evaluate(expression.this, row)
        return None if result is None else not result
    if isinstance(expression, exp.Is):
        return _literal(expression.this, row) is _literal(expression.expression, row)
    if isinstance(expression, exp.In):
        value = _literal(expression.this, row)
        if value is None:
            return None
        return value in [_literal(item, row) for item in expression.expressions]
    if isinstance(expression, exp.Between):
        value = _literal(expression.this, row)
        low = _literal(expression.args["low"], row)
        high = _literal(expression.args["high"], row)
        if value is None or low is None or high is None:
            return None
        return low <= value <= high

    comparisons = {
        exp.EQ: lambda left, right: left == right,
        exp.NEQ: lambda left, right: left != right,
        exp.GT: lambda left, right: left > right,
        exp.GTE: lambda left, right: left >= right,
        exp.LT: lambda left, right: left < right,
        exp.LTE: lambda left, right: left <= right,
    }
    for kind, compare in comparisons.items():
        if isinstance(expression, kind):
            left = _literal(expression.this, row)
            right = _literal(expression.expression, row)
            if left is None or right is None:
                return None
            return compare(left, right)
    raise ValueError("Unsupported CHECK expression.")


def check_passes(check: str, row: dict[str, Any]) -> bool | None:
    """Return False only for a confidently evaluated constraint violation.

    Unsupported PostgreSQL expressions return None. PostgreSQL also treats an
    unknown/NULL CHECK result as passing, so callers should reject only False.
    """

    try:
        return _evaluate(parse_one(check, read="postgres"), row)
    except (ParseError, TypeError, ValueError):
        return None


def check_columns(check: str) -> set[str]:
    try:
        expression = parse_one(check, read="postgres")
    except ParseError:
        return set()
    return {column.name for column in expression.find_all(exp.Column)}


def allowed_values(check: str, column_name: str) -> list[Any] | None:
    """Extract literal choices from ``column IN (...)`` or ``column = value``."""

    try:
        expression = parse_one(check, read="postgres")
        if (
            isinstance(expression, exp.In)
            and isinstance(expression.this, exp.Column)
            and expression.this.name == column_name
        ):
            return [_literal(item, {}) for item in expression.expressions]
        if isinstance(expression, exp.EQ):
            if isinstance(expression.this, exp.Column) and expression.this.name == column_name:
                return [_literal(expression.expression, {})]
            if (
                isinstance(expression.expression, exp.Column)
                and expression.expression.name == column_name
            ):
                return [_literal(expression.this, {})]
    except (ParseError, ValueError):
        return None
    return None

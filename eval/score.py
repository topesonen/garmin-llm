"""Decide whether a model's query result matches the gold query result.

Both results are lists of rows, each row a tuple of values, as DuckDB returns
them. The rules, decided by Topias on 2026-10-08 (tolerance changed on 2026-10-14):

- Column names are ignored, and so is column order: the model's columns may be
  rearranged, in the same way for every row, to match the gold columns.
- The number of columns and the number of rows must be equal.
- Row order counts only when the question is marked ordered.
- Numbers are equal when they differ by at most ABS_TOLERANCE, whatever their
  type (integer, float or decimal).
- A timestamp at midnight equals the same date. NULL equals only NULL.
- Text must be identical.

A second, lenient check (Topias, 2026-10-19) is reported next to the strict
one: a result with extra columns counts as matching when some of its columns,
as many as the gold result has, match the gold result. It never replaces the
strict verdict.

Usage:
    python eval/score.py        runs the examples at the bottom of this file
"""

import datetime
import math
from decimal import Decimal
from itertools import combinations, permutations

# Two decimal places: an answer rounded to two decimals matches, so 4.17 and
# 4.1667 match, 4.16 and 4.1667 do not. Was 0.001 until 2026-10-14.
ABS_TOLERANCE = 0.005
# Trying every column order grows fast; past this width only the given order is tried.
MAX_COLUMNS_TO_REORDER = 6


def normalise(value):
    """Bring a value to a form in which equal answers compare equal."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    if isinstance(value, datetime.datetime) and value.time() == datetime.time(0):
        return value.date()
    return value


def values_match(gold, model):
    """Compare two single values after normalising them."""
    gold, model = normalise(gold), normalise(model)
    if isinstance(gold, float) and isinstance(model, float):
        if math.isnan(gold) or math.isnan(model):
            return math.isnan(gold) and math.isnan(model)
        return abs(gold - model) <= ABS_TOLERANCE
    return type(gold) is type(model) and gold == model


def rows_match(gold_row, model_row):
    return all(values_match(g, m) for g, m in zip(gold_row, model_row))


def same_rows(gold_rows, model_rows, ordered):
    """Compare two row lists that already have their columns in the same order."""
    if ordered:
        return all(rows_match(g, m) for g, m in zip(gold_rows, model_rows))
    # Unordered: pair each gold row with one model row that has not been used yet.
    unused = list(model_rows)
    for gold_row in gold_rows:
        for index, model_row in enumerate(unused):
            if rows_match(gold_row, model_row):
                del unused[index]
                break
        else:
            return False
    return True


def compare_results(gold_rows, model_rows, ordered):
    """Return (True, "") if the results match, else (False, reason)."""
    if len(gold_rows) != len(model_rows):
        return False, f"row count differs: gold {len(gold_rows)}, model {len(model_rows)}"
    if not gold_rows:
        return True, ""
    gold_width, model_width = len(gold_rows[0]), len(model_rows[0])
    if gold_width != model_width:
        return False, f"column count differs: gold {gold_width}, model {model_width}"

    orders = [tuple(range(gold_width))]
    if 1 < gold_width <= MAX_COLUMNS_TO_REORDER:
        orders = list(permutations(range(gold_width)))
    for order in orders:
        reordered = [tuple(row[i] for i in order) for row in model_rows]
        if same_rows(gold_rows, reordered, ordered):
            return True, ""
    return False, "values differ"


def matches_with_extra_columns(gold_rows, model_rows, ordered):
    """True if the model result has more columns than the gold result, and some
    of its columns, as many as the gold result has, match it."""
    if not gold_rows or len(gold_rows) != len(model_rows):
        return False
    gold_width, model_width = len(gold_rows[0]), len(model_rows[0])
    if model_width <= gold_width:
        return False
    for columns in combinations(range(model_width), gold_width):
        chosen = [tuple(row[i] for i in columns) for row in model_rows]
        if compare_results(gold_rows, chosen, ordered)[0]:
            return True
    return False


if __name__ == "__main__":
    day = datetime.date(2025, 6, 30)
    examples = [
        # (expected, description, gold, model, ordered)
        (True, "same single number", [(42,)], [(42,)], False),
        (True, "integer and float", [(42,)], [(42.0,)], False),
        (True, "decimal and float", [(Decimal("21.0975"), 105.4875)], [(21.0975, 105.4875)], False),
        (True, "within tolerance", [(4.1666667,)], [(4.1667,)], False),
        (True, "rounded to two decimals", [(4.1666667,)], [(4.17,)], False),
        (False, "off in the second decimal", [(4.1666667,)], [(4.16,)], False),
        (True, "rows in another order, unordered question", [(1, 10.0), (2, 20.0)], [(2, 20.0), (1, 10.0)], False),
        (False, "rows in another order, ordered question", [(1, 10.0), (2, 20.0)], [(2, 20.0), (1, 10.0)], True),
        (True, "columns swapped", [(1, 10.0), (2, 20.0)], [(10.0, 1), (20.0, 2)], True),
        (False, "columns swapped in one row only", [(1, 10.0), (2, 20.0)], [(10.0, 1), (2, 20.0)], False),
        (True, "date and midnight timestamp", [(day,)], [(datetime.datetime(2025, 6, 30),)], False),
        (False, "date and text", [(day,)], [("2025-06-30",)], False),
        (False, "extra column", [(day,)], [(day, 104.0)], False),
        (False, "missing row", [(1,), (2,)], [(1,)], False),
        (False, "duplicate row counted once", [(1,), (1,), (2,)], [(1,), (2,), (2,)], False),
        (True, "NULL and NULL", [(None,)], [(None,)], False),
        (False, "NULL and zero", [(None,)], [(0,)], False),
        (True, "both empty", [], [], False),
    ]
    wrong = 0
    for expected, description, gold, model, ordered in examples:
        match, reason = compare_results(gold, model, ordered)
        wrong += match != expected
        status = "ok  " if match == expected else "FAIL"
        print(f"{status} {'match   ' if match else 'no match'}  {description}{': ' + reason if reason else ''}")
    print(f"{len(examples) - wrong} of {len(examples)} examples behave as intended")

    lenient_examples = [
        # (expected, description, gold, model, ordered)
        (True, "answer plus an extra column", [(day,)], [(day, 104.0)], False),
        (True, "answer in the last of three columns", [(5.2,)], [(1, "run", 5.2)], False),
        (True, "two gold columns among three", [(1, 10.0), (2, 20.0)], [(10.0, "x", 1), (20.0, "y", 2)], False),
        (False, "extra column, wrong answer", [(day,)], [(datetime.date(2025, 7, 1), 104.0)], False),
        (False, "same width is the strict check's job", [(1,)], [(2,)], False),
        (False, "fewer columns", [(1, 2)], [(1,)], False),
        (False, "extra row", [(1,)], [(1, 9), (2, 9)], False),
    ]
    for expected, description, gold, model, ordered in lenient_examples:
        match = matches_with_extra_columns(gold, model, ordered)
        wrong += match != expected
        status = "ok  " if match == expected else "FAIL"
        print(f"{status} {'match   ' if match else 'no match'}  lenient: {description}")
    total = len(examples) + len(lenient_examples)
    print(f"{total - wrong} of {total} examples behave as intended, lenient check included")
    raise SystemExit(1 if wrong else 0)

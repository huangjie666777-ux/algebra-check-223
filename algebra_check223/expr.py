"""Rational expression trees: validation, exact rational arithmetic over QQ[x],
domain (forbidden-value) tracking, and step-by-step identity comparison.

Every subexpression keeps the zeros of its own divisors as forbidden values;
simplification never removes them. All arithmetic is exact (sympy over QQ);
no floating-point tolerance is used anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sympy as sp

from .nodes import ValidationError

X = sp.Symbol("x")

MAX_EXPR_DEPTH = 20
MAX_EXPR_NODES = 200
MAX_DEGREE = 12
MAX_EXP = 6
MIN_STEPS = 2
MAX_STEPS = 10

EXPR_TYPES = {"num", "var", "add", "sub", "mul", "div", "pow"}


@dataclass
class Rational:
    """A rational function num/den plus the forbidden polynomials contributed
    by every original subexpression (divisor zeros, zero-power bases)."""
    num: sp.Poly
    den: sp.Poly
    forbidden: frozenset[sp.Poly] = field(default_factory=frozenset)


def _check_int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{what} must be an integer")
    return value


def _check_degree(poly: sp.Poly) -> None:
    if poly.degree() > MAX_DEGREE:
        raise ValidationError(
            f"intermediate numerator/denominator degree exceeds {MAX_DEGREE}")


def _const(num: int, den: int) -> Rational:
    q = sp.Rational(num, den)
    return Rational(sp.Poly(sp.Integer(q.p), X), sp.Poly(sp.Integer(q.q), X))


def _add(a: Rational, b: Rational, sign: int) -> Rational:
    num = a.num * b.den + sign * (b.num * a.den)
    den = a.den * b.den
    _check_degree(num)
    _check_degree(den)
    return Rational(num, den, a.forbidden | b.forbidden)


def _mul(a: Rational, b: Rational) -> Rational:
    num = a.num * b.num
    den = a.den * b.den
    _check_degree(num)
    _check_degree(den)
    return Rational(num, den, a.forbidden | b.forbidden)


def _div(a: Rational, b: Rational) -> Rational:
    if b.num.is_zero:
        raise ValidationError("division by an identically zero expression")
    num = a.num * b.den
    den = a.den * b.num
    _check_degree(num)
    _check_degree(den)
    # Zeros of the divisor's value are forbidden, in addition to everything
    # already forbidden inside the subexpressions.
    return Rational(num, den, a.forbidden | b.forbidden | {b.num})


def _pow(base: Rational, exp: int) -> Rational:
    num = base.num ** exp
    den = base.den ** exp
    _check_degree(num)
    _check_degree(den)
    forbidden = base.forbidden
    if exp == 0:
        # 0**0 is undefined: zeros of the base value stay forbidden even
        # though the simplified value is the constant 1.
        if base.num.is_zero:
            raise ValidationError("zero power of an identically zero expression")
        forbidden = forbidden | {base.num}
    return Rational(num, den, forbidden)


def validate_expr(tree: Any) -> tuple[dict, Rational]:
    """Validate an expression tree; return (normalized copy, exact value)."""
    counter = [0]
    node = _validate(tree, 0, counter)
    return node


def _validate(node: Any, depth: int, counter: list[int]) -> tuple[dict, Rational]:
    if depth > MAX_EXPR_DEPTH:
        raise ValidationError("expression tree is too deep")
    counter[0] += 1
    if counter[0] > MAX_EXPR_NODES:
        raise ValidationError("expression tree has too many nodes")
    if not isinstance(node, dict):
        raise ValidationError(
            "expression node must be an object; code and expression "
            "strings are not accepted")
    ntype = node.get("type")
    if not isinstance(ntype, str) or ntype not in EXPR_TYPES:
        raise ValidationError(f"unknown expression node type: {ntype!r}")

    def child(key: str):
        if key not in node:
            raise ValidationError(f"{ntype} node missing '{key}'")
        return _validate(node[key], depth + 1, counter)

    if ntype == "num":
        n = _check_int(node.get("n"), "num 'n'")
        d = _check_int(node.get("d"), "num 'd'")
        if d == 0:
            raise ValidationError("num 'd' must be non-zero")
        return {"type": "num", "n": n, "d": d}, _const(n, d)
    if ntype == "var":
        return {"type": "var"}, Rational(sp.Poly(X, X), sp.Poly(sp.Integer(1), X))
    if ntype == "pow":
        base_node, base = child("base")
        exp = _check_int(node.get("exp"), "pow 'exp'")
        if not 0 <= exp <= MAX_EXP:
            raise ValidationError(f"pow 'exp' must be between 0 and {MAX_EXP}")
        return {"type": "pow", "base": base_node, "exp": exp}, _pow(base, exp)

    left_node, left = child("left")
    right_node, right = child("right")
    out = {"type": ntype, "left": left_node, "right": right_node}
    if ntype == "add":
        return out, _add(left, right, 1)
    if ntype == "sub":
        return out, _add(left, right, -1)
    if ntype == "mul":
        return out, _mul(left, right)
    return out, _div(left, right)


# -- forbidden points ------------------------------------------------------

def forbidden_poly(value: Rational) -> sp.Poly:
    """Squarefree polynomial over QQ whose real roots are exactly the
    forbidden points of the expression (exact union, no float tolerance)."""
    factors: dict[sp.Expr, int] = {}
    for poly in value.forbidden | {value.den}:
        if poly.is_zero:
            raise ValidationError("identically zero divisor")
        for factor, _ in sp.factor_list(poly.as_expr())[1]:
            factors[factor] = 1
    if not factors:
        return sp.Poly(sp.Integer(1), X)
    return sp.Poly(sp.prod(list(factors)), X)


def forbidden_roots(value: Rational) -> list[sp.Expr]:
    """Exact distinct real roots of the forbidden polynomial."""
    poly = forbidden_poly(value)
    if poly.degree() <= 0:
        return []
    return list(sp.real_roots(poly.as_expr(), X))


def format_number(number: sp.Expr) -> str:
    """Exact string form: rationals stay n/d, algebraic roots stay CRootOf."""
    return sp.sstr(number)


def _real_roots_of(poly: sp.Poly) -> list[sp.Expr]:
    if poly.degree() <= 0:
        return []
    return list(sp.real_roots(poly.as_expr(), X))


# -- step comparison ---------------------------------------------------------

def compare_steps(a: Rational, b: Rational) -> dict:
    """Compare two adjacent steps on their common domain, exactly."""
    pa, pb = forbidden_poly(a), forbidden_poly(b)
    common = sp.Poly(sp.gcd(pa.as_expr(), pb.as_expr()), X)
    removed_poly, rem = sp.div(pa, common)
    if not rem.is_zero:
        raise ValidationError("internal: forbidden polynomial gcd mismatch")
    added_poly, rem = sp.div(pb, common)
    if not rem.is_zero:
        raise ValidationError("internal: forbidden polynomial gcd mismatch")

    # Cross-product difference numerator: a - b == diff / (a.den * b.den).
    diff = sp.Poly(a.num * b.den - b.num * a.den, X)

    result: dict[str, Any] = {}
    if diff.is_zero:
        added = _real_roots_of(added_poly)
        removed = _real_roots_of(removed_poly)
        if not added and not removed:
            result["relation"] = "identical"
        else:
            result["relation"] = "domain_changed"
        result["added_forbidden"] = [sp.sstr(r) for r in added]
        result["removed_forbidden"] = [sp.sstr(r) for r in removed]
    else:
        result["relation"] = "not_identical"
        result["added_forbidden"] = [sp.sstr(r) for r in _real_roots_of(added_poly)]
        result["removed_forbidden"] = [sp.sstr(r) for r in _real_roots_of(removed_poly)]
        result["evidence"] = {
            "polynomial": sp.sstr(sp.expand(diff.as_expr())),
            "coefficients": [sp.sstr(c) for c in sp.Poly(diff.as_expr(), X).all_coeffs()],
        }
    return result

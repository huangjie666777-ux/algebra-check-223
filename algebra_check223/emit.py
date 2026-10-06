"""Emit typesetting nodes from a validated expression tree.

The original tree structure is preserved: divisions stay fractions, powers
stay scripts, and parentheses appear only where precedence requires them.
Nothing is replaced by a simplified or reduced form.
"""
from __future__ import annotations

MINUS = "\u2212"
DOT = "\u22c5"

# Precedence levels: lower binds looser.
_PREC = {"add": 1, "sub": 1, "mul": 2, "div": 2, "pow": 3, "num": 4, "var": 4}


def _text(value: str) -> dict:
    return {"type": "text", "value": value}


def _paren(child: dict) -> dict:
    return {"type": "paren", "child": child}


def _num_node(n: int, d: int) -> dict:
    if d == 1:
        return _text(str(n))
    body = {"type": "frac", "num": _text(str(abs(n))), "den": _text(str(d))}
    if n < 0:
        return {"type": "row", "children": [_text(MINUS), body]}
    return body


def emit(node: dict, parent_prec: int = 0, side: str = "") -> dict:
    """Convert a validated expression node into a typesetting node."""
    ntype = node["type"]
    prec = _PREC[ntype]

    if ntype == "num":
        out = _num_node(node["n"], node["d"])
    elif ntype == "var":
        out = _text("x")
    elif ntype in ("add", "sub"):
        op = "+" if ntype == "add" else MINUS
        right_prec = prec + 1 if ntype == "sub" else prec
        out = {"type": "row", "children": [
            emit(node["left"], prec, "left"),
            _text(op),
            emit(node["right"], right_prec, "right"),
        ]}
    elif ntype == "mul":
        out = {"type": "row", "children": [
            emit(node["left"], prec, "left"),
            _text(DOT),
            emit(node["right"], prec, "right"),
        ]}
    elif ntype == "div":
        out = {"type": "frac",
               "num": emit(node["left"]), "den": emit(node["right"])}
    else:  # pow
        base = emit(node["base"], prec, "base")
        out = {"type": "scripts", "base": base,
               "sup": _text(str(node["exp"]))}

    # Parenthesize when this node binds looser than its context demands,
    # and for the right operand of sub at equal precedence (a-(b-c)).
    # Negative constants get parentheses whenever they are not leading.
    need = prec < parent_prec
    if side == "right" and prec == parent_prec and ntype in ("add", "sub"):
        need = True
    if ntype == "num" and node["n"] < 0 and (parent_prec > 0 or side):
        need = True
    if need:
        return _paren(out)
    return out

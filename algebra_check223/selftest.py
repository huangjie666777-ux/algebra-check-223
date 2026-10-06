"""Self-test: layout correctness, validation rejections, determinism."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from . import expr
from .emit import emit
from .font import MathFont
from .layout import Layout
from .nodes import ValidationError, validate_font_size, validate_tree
from .svg import render_svg

FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "STIXTwoMath-Regular.otf"
font = MathFont(str(FONT_PATH))
SIZE = 48.0


def render(tree, size=SIZE):
    node = validate_tree(tree, lambda ch: font.glyph_for(ch) is not None)
    box = Layout(font, size).layout(node)
    return render_svg(box, font), box


def expect_error(tree, size=SIZE):
    try:
        if not (isinstance(size, (int, float)) and size > 0):
            validate_font_size(size)
        validate_tree(tree, lambda ch: font.glyph_for(ch) is not None)
    except ValidationError:
        return
    raise AssertionError(f"expected ValidationError for {tree!r}")


def layout_box(tree, size=SIZE):
    node = validate_tree(tree, lambda ch: font.glyph_for(ch) is not None)
    return Layout(font, size).layout(node)


def check_layout_fixes():
    # sqrt with a deep radicand: surd must reach below the baseline too
    deep = {"type": "frac", "num": {"type": "text", "value": "1"},
            "den": {"type": "text", "value": "x"}}
    for _ in range(3):
        deep = {"type": "frac", "num": {"type": "text", "value": "1"},
                "den": deep}
    rad = layout_box(deep)
    box = layout_box({"type": "sqrt", "radicand": deep})
    assert box.depth >= rad.depth - 1e-9, (box.depth, rad.depth)
    assert box.height >= rad.height - 1e-9

    # parens around tall, top-heavy content must cover the full height
    tall_num = {"type": "frac", "num": deep, "den": {"type": "text", "value": "2"}}
    inner = layout_box(tall_num)
    wrapped = layout_box({"type": "paren", "child": tall_num})
    assert wrapped.height >= inner.height - 1e-9, (wrapped.height, inner.height)
    assert wrapped.depth >= inner.depth - 1e-9

    # non-string node type / delimiters are validation errors, not 500s
    expect_error({"type": ["text"], "value": "x"})
    expect_error({"type": "paren", "child": {"type": "text", "value": "x"},
                  "left": ["("]})


NUM1 = {"type": "num", "n": 1, "d": 1}
VAR = {"type": "var"}


def check_expr():
    # (x^2-1)/(x-1) -> x+1: same value, x=1 restriction removed
    t1 = {"type": "div",
          "left": {"type": "sub",
                   "left": {"type": "pow", "base": VAR, "exp": 2},
                   "right": NUM1},
          "right": {"type": "sub", "left": VAR, "right": NUM1}}
    t2 = {"type": "add", "left": VAR, "right": NUM1}
    _, v1 = expr.validate_expr(t1)
    _, v2 = expr.validate_expr(t2)
    assert [expr.format_number(r) for r in expr.forbidden_roots(v1)] == ["1"]
    assert expr.forbidden_roots(v2) == []
    cmp = expr.compare_steps(v1, v2)
    assert cmp["relation"] == "domain_changed"
    assert cmp["removed_forbidden"] == ["1"] and cmp["added_forbidden"] == []

    # identical on the same domain
    _, v3 = expr.validate_expr(
        {"type": "mul", "left": {"type": "num", "n": 2, "d": 1}, "right": VAR})
    _, v4 = expr.validate_expr({"type": "add", "left": VAR, "right": VAR})
    assert expr.compare_steps(v3, v4)["relation"] == "identical"

    # not identical: cross-product difference polynomial is reported
    cmp = expr.compare_steps(v2, v3)
    assert cmp["relation"] == "not_identical"
    assert cmp["evidence"]["polynomial"] == "1 - x"

    # zero power keeps the base restriction: (x-2)^0 forbids x=2
    _, v5 = expr.validate_expr(
        {"type": "pow",
         "base": {"type": "sub", "left": VAR,
                  "right": {"type": "num", "n": 2, "d": 1}},
         "exp": 0})
    assert [expr.format_number(r) for r in expr.forbidden_roots(v5)] == ["2"]

    # nested division keeps inner restrictions: 1/(1/x) forbids x=0
    _, v6 = expr.validate_expr(
        {"type": "div", "left": NUM1,
         "right": {"type": "div", "left": NUM1, "right": VAR}})
    assert [expr.format_number(r) for r in expr.forbidden_roots(v6)] == ["0"]

    # irrational forbidden roots are exact and deduplicated
    _, v7 = expr.validate_expr(
        {"type": "div", "left": NUM1,
         "right": {"type": "sub",
                   "left": {"type": "pow", "base": VAR, "exp": 2},
                   "right": {"type": "num", "n": 2, "d": 1}}})
    roots = [expr.format_number(r) for r in expr.forbidden_roots(v7)]
    assert roots == ["-sqrt(2)", "sqrt(2)"], roots

    # rejections
    for bad in ("x+1", 42, None, ["x"]):
        try:
            expr.validate_expr(bad)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"accepted {bad!r}")
    for bad in (
        {"type": "num", "n": 1, "d": 0},
        {"type": "num", "n": 1.5, "d": 1},
        {"type": "num", "n": True, "d": 1},
        {"type": "pow", "base": VAR, "exp": 7},
        {"type": "pow", "base": VAR, "exp": -1},
        {"type": "pow", "base": VAR, "exp": 2.0},
        {"type": "div", "left": VAR,
         "right": {"type": "sub", "left": VAR, "right": VAR}},  # zero divisor
        {"type": "pow", "base": {"type": "pow", "base": VAR, "exp": 4},
         "exp": 4},  # degree 16 > 12
        {"type": "sin", "left": VAR, "right": VAR},
    ):
        try:
            expr.validate_expr(bad)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"accepted {bad!r}")
    deep = VAR
    for _ in range(21):
        deep = {"type": "add", "left": deep, "right": NUM1}
    try:
        expr.validate_expr(deep)
    except ValidationError:
        pass
    else:
        raise AssertionError("accepted depth 21")

    # input tree is not mutated
    tree = {"type": "div", "left": VAR, "right": NUM1}
    snapshot = copy.deepcopy(tree)
    expr.validate_expr(tree)
    assert tree == snapshot

    # emit -> layout -> svg keeps the original form (frac, scripts, parens)
    emitted = emit(t1)
    assert emitted["type"] == "frac"
    (svg, w, h, b), _ = render(emitted)
    assert "<rect" in svg and w > 0 and h > SIZE
    emitted = emit({"type": "mul", "left": t2,
                    "right": {"type": "pow", "base": t2, "exp": 2}})
    assert emitted["children"][0]["type"] == "paren"
    assert emitted["children"][2]["base"]["type"] == "paren"
    render(emitted)


def check_http():
    from fastapi.testclient import TestClient
    from .app import app
    client = TestClient(app, raise_server_exceptions=False)

    steps = [
        {"type": "div",
         "left": {"type": "sub",
                  "left": {"type": "pow", "base": VAR, "exp": 2},
                  "right": NUM1},
         "right": {"type": "sub", "left": VAR, "right": NUM1}},
        {"type": "add", "left": VAR, "right": NUM1},
    ]
    r = client.post("/check", json={"font_size": 40, "steps": steps})
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["steps"]) == 2 and len(data["comparisons"]) == 1
    assert data["steps"][0]["forbidden"] == ["1"]
    assert data["steps"][0]["svg"].startswith("<svg")
    assert data["comparisons"][0]["relation"] == "domain_changed"

    # 1 step / 11 steps rejected
    assert client.post("/check", json={
        "font_size": 40, "steps": steps[:1]}).status_code == 422
    assert client.post("/check", json={
        "font_size": 40, "steps": steps * 6}).status_code == 422
    # expression string rejected
    assert client.post("/check", json={
        "font_size": 40, "steps": ["x+1", "x+1"]}).status_code == 422
    # array node type is a 422, not a 500
    r = client.post("/render", json={
        "font_size": 40, "formula": {"type": ["text"], "value": "x"}})
    assert r.status_code == 422, r.status_code
    # /render still works
    r = client.post("/render", json={
        "font_size": 40, "formula": {"type": "text", "value": "x+1"}})
    assert r.status_code == 200 and r.json()["svg"].startswith("<svg")


def main():
    # text
    (svg, w, h, b), box = render({"type": "text", "value": "xy+1"})
    assert w > 0 and h > 0 and b > 0 and "<path" in svg

    # row aligns on baseline
    (svg, w, h, b), _ = render({"type": "row", "children": [
        {"type": "text", "value": "a"}, {"type": "text", "value": "g"}]})
    assert h > 0 and b > 0

    # fraction
    frac = {"type": "frac", "num": {"type": "text", "value": "1"},
            "den": {"type": "text", "value": "x+2"}}
    (svg, w, h, b), _ = render(frac)
    assert "<rect" in svg and h > SIZE

    # scripts: sup only, sub only, both
    for extra in ({"sup": {"type": "text", "value": "2"}},
                  {"sub": {"type": "text", "value": "i"}},
                  {"sup": {"type": "text", "value": "2"},
                   "sub": {"type": "text", "value": "i"}}):
        node = {"type": "scripts", "base": {"type": "text", "value": "x"}, **extra}
        (svg, w, h, b), _ = render(node)
        assert w > 0

    # sqrt with nested frac; parens around tall content stretch
    nested = {"type": "paren", "child": {"type": "sqrt", "radicand": frac}}
    (svg, w, h, b), _ = render(nested)
    assert h > SIZE * 1.5

    # very tall content triggers assembly (many extender parts)
    tall = frac
    for _ in range(6):
        tall = {"type": "frac", "num": tall, "den": tall}
    (svg, w, h, b), _ = render({"type": "paren", "child": tall})
    assert svg.count("<path") > 10

    # determinism
    s1, _ = render(nested)
    s2, _ = render(nested)
    assert s1 == s2

    # input tree not mutated
    tree = {"type": "frac", "num": {"type": "text", "value": "a"},
            "den": {"type": "text", "value": "b"}}
    snapshot = copy.deepcopy(tree)
    render(tree)
    assert tree == snapshot

    # rejections
    expect_error({"type": "nope"})
    expect_error({"type": "text", "value": ""})
    expect_error({"type": "text", "value": "\u4e2d"})  # CJK not in font
    expect_error({"type": "frac", "num": {"type": "text", "value": "a"}})
    expect_error({"type": "scripts", "base": {"type": "text", "value": "x"}})
    expect_error({"type": "row", "children": []})
    deep = {"type": "text", "value": "x"}
    for _ in range(80):
        deep = {"type": "sqrt", "radicand": deep}
    expect_error(deep)
    for bad in (0, -1, float("inf"), float("nan"), 1e9, "12"):
        try:
            validate_font_size(bad)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"font_size {bad!r} accepted")

    check_layout_fixes()
    check_expr()
    check_http()
    print("selftest OK")


if __name__ == "__main__":
    main()

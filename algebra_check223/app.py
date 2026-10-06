"""HTTP delivery: FastAPI app exposing POST /render and POST /check."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import expr
from .emit import emit
from .font import MathFont, FontError
from .layout import Layout
from .nodes import ValidationError, validate_font_size, validate_tree
from .svg import render_svg

FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "STIXTwoMath-Regular.otf"

app = FastAPI(title="Math Formula Typesetter")
_font = MathFont(str(FONT_PATH))


class RenderRequest(BaseModel):
    formula: Any
    font_size: Any


class CheckRequest(BaseModel):
    steps: Any
    font_size: Any


@app.exception_handler(ValidationError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(FontError)
async def font_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.post("/render")
async def render(req: RenderRequest):
    size = validate_font_size(req.font_size)
    tree = validate_tree(req.formula, lambda ch: _font.glyph_for(ch) is not None)
    box = Layout(_font, size).layout(tree)
    svg, width, height, baseline = render_svg(box, _font)
    return {"svg": svg, "width": width, "height": height, "baseline": baseline}


def _render_step(tree: dict, size: float) -> dict:
    node = validate_tree(emit(tree), lambda ch: _font.glyph_for(ch) is not None)
    box = Layout(_font, size).layout(node)
    svg, width, height, baseline = render_svg(box, _font)
    return {"svg": svg, "width": width, "height": height, "baseline": baseline}


@app.post("/check")
async def check(req: CheckRequest):
    size = validate_font_size(req.font_size)
    if not isinstance(req.steps, list):
        raise ValidationError("steps must be a list of expression trees")
    if not expr.MIN_STEPS <= len(req.steps) <= expr.MAX_STEPS:
        raise ValidationError(
            f"steps must contain between {expr.MIN_STEPS} and {expr.MAX_STEPS} "
            "expression trees")

    values = []
    steps_out = []
    for tree in req.steps:
        normalized, value = expr.validate_expr(tree)
        values.append(value)
        rendered = _render_step(normalized, size)
        rendered["forbidden"] = [
            expr.format_number(r) for r in expr.forbidden_roots(value)]
        rendered["numerator"] = str(value.num.as_expr().expand())
        rendered["denominator"] = str(value.den.as_expr().expand())
        steps_out.append(rendered)

    comparisons = []
    for i in range(len(values) - 1):
        result = expr.compare_steps(values[i], values[i + 1])
        result["step"] = i
        comparisons.append(result)

    return {"steps": steps_out, "comparisons": comparisons}

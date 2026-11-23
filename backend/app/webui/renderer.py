"""Serve the existing HTML/CSS/JS interface unchanged (no redesign).

The legacy client talks to ``google.script.run.apiCall(action, payload, token)``.
We inject a tiny shim that forwards the exact same call to ``POST /api`` — the
same approach the reference Electron shell used, so every current route and
screen keeps working with the Python engine.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"

_JSON_INCLUDE = re.compile(
    r"<\?!?=\s*JSON\.stringify\(include\((['\"])([^'\"]+)\1\)\)\s*;?\s*\?>"
)
_INCLUDE = re.compile(r"<\?!?=\s*include\((['\"])([^'\"]+)\1\)\s*;?\s*\?>")

_DESKTOP_SHIM = """
<script>
(function(){
  function Runner(){ this._s = null; this._f = null; }
  Runner.prototype.withSuccessHandler = function(fn){ this._s = fn; return this; };
  Runner.prototype.withFailureHandler = function(fn){ this._f = fn; return this; };
  Runner.prototype.apiCall = function(action, payload, tk){
    var s = this._s, f = this._f;
    fetch('/api', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ action: action, payload: payload || {}, token: tk || '' }) })
      .then(function(r){ return r.json(); })
      .then(function(res){ if (s) s(res); })
      .catch(function(e){ if (f) f({ message: e && e.message ? e.message : 'network error' }); });
  };
  window.google = window.google || {};
  window.google.script = { run: new Runner() };
})();
</script>
"""


@lru_cache(maxsize=32)
def _read(name: str) -> str:
    path = FRONTEND_DIR / f"{name}.html"
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8-sig")


def _include(name: str) -> str:
    return _read(name)


def render_index() -> str:
    """Resolve Apps Script scriptlets and inject the apiCall shim."""
    html = _read("Client_Index")
    html = _JSON_INCLUDE.sub(lambda m: json.dumps(_include(m.group(2)), ensure_ascii=False), html)
    html = _INCLUDE.sub(lambda m: _include(m.group(2)), html)
    if "<body>" in html:
        html = html.replace("<body>", "<body>" + _DESKTOP_SHIM, 1)
    else:  # pragma: no cover - defensive
        html = _DESKTOP_SHIM + html
    return html


router = APIRouter(tags=["webui"])


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    try:
        return HTMLResponse(render_index())
    except FileNotFoundError as exc:  # pragma: no cover - deployment issue
        raise HTTPException(
            status_code=503,
            detail="فایل‌های رابط کاربری در پوشهٔ frontend یافت نشد.",
        ) from exc


@router.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)

"""Serve the built SPA from FastAPI so one port (PORT) covers everything.

The static build can live in either of these paths; the first one that
contains an index.html wins:
  - backend/app/static/   (preferred for deployment; copy frontend/dist here)
  - frontend/dist/        (fallback so dev/CI can serve straight from the
                           Vite build without a copy step)
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

log = logging.getLogger(__name__)


def _resolve_static_dir() -> Path | None:
    backend_dir = Path(__file__).resolve().parent.parent  # backend/
    repo_root = backend_dir.parent
    candidates = [
        backend_dir / "app" / "static",
        repo_root / "frontend" / "dist",
    ]
    for p in candidates:
        if (p / "index.html").exists():
            return p
    return None


def mount_spa(app: FastAPI) -> None:
    static_dir = _resolve_static_dir()
    if static_dir is None:
        log.warning(
            "no SPA build found at backend/app/static or frontend/dist; "
            "only /api/* will be served. Run `npm --prefix frontend run build`."
        )
        return

    log.info("serving SPA from %s", static_dir)
    index_path = static_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_catch_all(full_path: str, request: Request) -> FileResponse:
        # Never shadow the API: if a /api/* request reaches us, the router
        # didn't match it, so let FastAPI's normal 404 logic continue by
        # raising HTTPException.
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404)
        candidate = (static_dir / full_path).resolve()
        # Prevent path traversal — the resolved file must live under static_dir.
        try:
            candidate.relative_to(static_dir)
        except ValueError:
            raise HTTPException(status_code=404) from None
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_path)

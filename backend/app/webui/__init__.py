"""Web UI package: serves the preserved HTML/CSS/JS interface."""

from app.webui.renderer import render_index, router

__all__ = ["render_index", "router"]

"""White Rose Clinic — Python engine (FastAPI + SQLAlchemy 2.x).

Package layout:
    app.api        HTTP surface (health + action gateway)
    app.core       cross-cutting: config, errors, logging, security, permissions
    app.database   SQLAlchemy base/session/models
    app.schemas    Pydantic request/response models
    app.services   use-cases (phase 3+)
    app.modules    domain modules (phase 3+)
    app.webui      serving the existing HTML/CSS/JS interface
"""

__all__ = ["__version__"]

__version__ = "0.6.0"

"""Run with: python -m uvicorn grantiq.app.main:app --host 127.0.0.1."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import ROOT
from .database import initialize, SessionLocal
from .security import session_secret
from .services.repository import get_profile

def create_app(session_factory=SessionLocal, *, enable_scheduler=None):
    @asynccontextmanager
    async def lifespan(app):
        initialize(session_factory.kw.get("bind"))
        with session_factory() as session:
            get_profile(session)
            from .services.scheduler import ensure_schedule
            ensure_schedule(session)
            from .services.research_context import seed_prospects
            seed_prospects(session)
        from .services.scheduler import SearchWorker
        worker = SearchWorker(session_factory) if (enable_scheduler if enable_scheduler is not None else session_factory is SessionLocal) else None
        if worker:
            worker.start()
        try:
            yield
        finally:
            if worker:
                worker.stop()

    app = FastAPI(title="GrantIQ", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.session_factory = session_factory
    app.state.password = os.getenv("GRANTIQ_ADMIN_PASSWORD", "")

    @app.middleware("http")
    async def access_control(request: Request, call_next):
        local = request.client is not None and request.client.host in {"127.0.0.1", "::1"}
        if not app.state.password and not local:
            return JSONResponse({"detail": "Local mode accepts loopback connections only. Configure password, session secret, and allowed hosts for shared access."}, status_code=403)
        public = request.url.path in {"/login", "/health"} or request.url.path.startswith("/static/")
        if app.state.password and not public and not request.session.get("authenticated"):
            return RedirectResponse("/login", status_code=303)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # Session middleware wraps access_control so session data is available there.
    app.add_middleware(SessionMiddleware, secret_key=session_secret(), same_site="lax", https_only=os.getenv("GRANTIQ_SECURE_COOKIES", "false").lower() == "true", max_age=8*3600)
    hosts = [h.strip() for h in os.getenv("GRANTIQ_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)
    app.mount("/static", StaticFiles(directory=str(ROOT / "grantiq" / "app" / "static")), name="static")
    from .routes.web import router
    app.include_router(router)
    from .routes.research import router as research_router
    app.include_router(research_router)
    from .routes.schedule import router as schedule_router
    app.include_router(schedule_router)
    from .routes.prospects import router as prospects_router
    app.include_router(prospects_router)

    from .routes.presentation import router as presentation_router
    app.include_router(presentation_router)

    @app.get("/health")
    def health():
        return {"status": "ok", "application": "GrantIQ"}
    return app

app = create_app()

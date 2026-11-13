import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .db import init_db
from .routers import load_routers


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .config import check_secret_key, get_settings
    warning = check_secret_key(get_settings().kaji_secret_key)          # refuse une clé d'exemple AVANT d'ouvrir la base ou d'accepter une requête
    if warning:
        logging.getLogger("uvicorn.error").warning(warning)
    init_db()
    from . import audit
    from .db import get_engine
    from sqlalchemy.orm import Session
    with Session(get_engine()) as db:
        audit.purge_old(db, get_settings().kaji_audit_retention_days)
    task = None
    if get_settings().kaji_scheduler:                                  # planificateur d'actions (lot #411) : une tâche de fond, arrêtée avec l'application
        import asyncio

        from . import scheduler
        from .proxmox import ProxmoxClient
        task = asyncio.create_task(scheduler.loop(ProxmoxClient, lambda: Session(get_engine())))
    yield
    if task is not None:
        task.cancel()


app = FastAPI(title="Kaji", lifespan=lifespan)
for _router in load_routers():           # ordre déclaré par chaque module (voir routers/__init__.py)
    app.include_router(_router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """En-têtes défensifs sur toutes les réponses ; l'API n'est jamais mise en cache (état du cluster, sessions)."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    """Erreurs de validation SANS la valeur saisie. Par défaut FastAPI renvoie « input » : sur un champ manquant,
    c'est le corps entier de la requête, donc un mot de passe ou le secret d'un token serait recopié en clair."""
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})


@app.get("/api/health")
async def health():
    return {"status": "ok"}

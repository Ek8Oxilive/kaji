from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .db import init_db
from .routers import actions, auth, cluster, clone, cloudinit, connections, create, destroy, disks, hardware, live, migrate, nets, resources, snapshots


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Kaji", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(connections.router)
app.include_router(cluster.router)
# hardware, snapshots, nets, disks et clone avant actions : la route générique .../{vmid}/{action} les intercepterait sinon
app.include_router(hardware.router)
app.include_router(snapshots.router)
app.include_router(nets.router)
app.include_router(disks.router)
app.include_router(clone.router)
app.include_router(cloudinit.router)
app.include_router(destroy.router)
app.include_router(migrate.router)
app.include_router(actions.router)
app.include_router(resources.router)
app.include_router(create.router)
app.include_router(live.router)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    """Erreurs de validation SANS la valeur saisie. Par défaut FastAPI renvoie « input » : sur un champ manquant,
    c'est le corps entier de la requête, donc un mot de passe ou le secret d'un token serait recopié en clair."""
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})


@app.get("/api/health")
async def health():
    return {"status": "ok"}

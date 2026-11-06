from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .routers import actions, auth, cluster, connections, create, hardware, live, nets, resources, snapshots


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Kaji", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(connections.router)
app.include_router(cluster.router)
# hardware, snapshots et nets avant actions : la route générique .../{vmid}/{action} les intercepterait sinon
app.include_router(hardware.router)
app.include_router(snapshots.router)
app.include_router(nets.router)
app.include_router(actions.router)
app.include_router(resources.router)
app.include_router(create.router)
app.include_router(live.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}

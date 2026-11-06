from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db
from .routers import auth, connections


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Kaji", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(connections.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}

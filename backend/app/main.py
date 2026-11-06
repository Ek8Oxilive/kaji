from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="PUD", lifespan=lifespan)


@app.get("/api/health")
async def health():
    return {"status": "ok"}

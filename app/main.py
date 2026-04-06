from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.api import health, webhook, auth
from app.api.debug import router as debug_router
from app.services.scheduler_service import start_scheduler_background

app = FastAPI(title="Personal Secretary Agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler_background()
    yield


app = FastAPI(title="Personal Secretary Agent", lifespan=lifespan)

app.include_router(health.router, tags=["health"])
app.include_router(webhook.router, tags=["webhook"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(debug_router, prefix="/debug", tags=["debug"])


@app.get("/")
async def root():
    return {"message": "Personal Secretary Agent API"}

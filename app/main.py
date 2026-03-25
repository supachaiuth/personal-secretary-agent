from fastapi import FastAPI
from app.api import health, webhook

app = FastAPI(title="Personal Secretary Agent")

app.include_router(health.router, tags=["health"])
app.include_router(webhook.router, tags=["webhook"])


@app.get("/")
async def root():
    return {"message": "Personal Secretary Agent API"}

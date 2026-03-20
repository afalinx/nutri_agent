from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from app.logging import setup_logging
from app.api.routes.users import router as users_router
from app.api.routes.plans import router as plans_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("NutriAgent backend starting")
    yield
    logger.info("NutriAgent backend shutting down")


app = FastAPI(
    title="NutriAgent API",
    description="AI-powered personalized meal planning with verified KBJU",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(users_router)
app.include_router(plans_router)


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok"}

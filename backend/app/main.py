from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.routes.catalog import router as catalog_router
from app.api.routes.plans import router as plans_router
from app.api.routes.recipes import router as recipes_router
from app.api.routes.users import router as users_router
from app.core import cache
from app.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("NutriAgent backend starting")
    yield
    await cache.close()
    logger.info("NutriAgent backend shutting down")


app = FastAPI(
    title="NutriAgent API",
    description="AI-powered personalized meal planning with verified KBJU",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4321",
        "http://127.0.0.1:4321",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users_router)
app.include_router(plans_router)
app.include_router(recipes_router)
app.include_router(catalog_router)


@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok"}

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.companies import router as companies_router
from app.api.v1.events import router as events_router
from app.api.v1.feed import router as feed_router
from app.api.v1.insights import router as insights_router
from app.api.v1.research import router as research_router
from app.api.v1.system import router as system_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(companies_router)
api_router.include_router(events_router)
api_router.include_router(feed_router)
api_router.include_router(insights_router)
api_router.include_router(research_router)
api_router.include_router(system_router)

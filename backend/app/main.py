import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.browser.manager import browser_manager
from app.config import settings
from app.db.connection import engine
from app.db.models import Base

from app.api import auth, keywords, competition, bid, products, tracking, bestsellers, tasks, utils, insights, image, price_compare, related

# 프론트엔드 빌드 경로
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: DB 테이블 생성
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown: 브라우저 종료
    await browser_manager.close()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 라우터 등록
app.include_router(auth.router)
app.include_router(keywords.router)
app.include_router(competition.router)
app.include_router(bid.router)
app.include_router(products.router)
app.include_router(tracking.router)
app.include_router(bestsellers.router)
app.include_router(tasks.router)
app.include_router(utils.router)
app.include_router(insights.router)
app.include_router(image.router)
app.include_router(price_compare.router)
app.include_router(related.router)

# 프론트엔드 정적 파일 서빙
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        """SPA 라우팅: API가 아닌 모든 요청을 index.html로"""
        file_path = FRONTEND_DIST / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
else:
    @app.get("/")
    async def root():
        return {
            "app": settings.APP_NAME,
            "status": "running",
            "message": "프론트엔드 빌드가 없습니다. frontend/ 에서 npm run build 를 실행하세요.",
        }

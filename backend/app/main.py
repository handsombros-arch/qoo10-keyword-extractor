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
from app.services.auto_login import auto_login_on_startup

from app.api import auth, keywords, competition, bid, products, tracking, bestsellers, tasks, utils, insights, image, price_compare, related, margin, recommendations, user_data, automation, extension

# 프론트엔드 빌드 경로
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: DB 테이블 생성 + 브라우저 쿠키 기반 로그인 상태 복원
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 신규 컬럼 idempotent 마이그레이션
        # (create_all 은 신규 테이블만 만들고 기존 테이블의 컬럼은 추가 안 함)
        await _migrate_add_columns(conn)
    # 쿠키 파일이 있으면 로그인 유지된 것으로 낙관적 판정 (검증은 첫 사용 시)
    try:
        if settings.COOKIES_PATH.exists():
            browser_manager._logged_in = True
    except Exception:
        pass

    # 자동 로그인 시도 (백그라운드) — 쿠키 만료 시 자격정보로 재로그인
    asyncio.create_task(auto_login_on_startup())

    yield
    # Shutdown: 브라우저 종료 (명시적 종료, 로그인 플래그 리셋)
    await browser_manager.close()


async def _migrate_add_columns(conn) -> None:
    """기존 테이블에 신규 컬럼 추가 (idempotent).

    Postgres: ADD COLUMN IF NOT EXISTS
    SQLite:   PRAGMA 로 컬럼 존재 체크 후 ADD
    실패는 무시 (이미 존재 등 정상 시나리오 포함).
    """
    is_postgres = settings.DATABASE_URL.startswith("postgresql")
    new_columns = [
        # (table, column, type)
        ("keywords", "category_inferred", "TEXT"),
        ("keywords", "is_brand", "INTEGER DEFAULT 0"),
        ("keywords", "brand_kr", "TEXT"),
        ("keywords", "brand_jp", "TEXT"),
        ("keywords", "brand_en", "TEXT"),
        ("qoo10_products", "set_count", "INTEGER DEFAULT 1"),
        ("qoo10_products", "set_count_source", "TEXT"),
        ("qoo10_products", "set_count_vision", "INTEGER"),
        ("qoo10_products", "set_count_vision_confidence", "REAL"),
        ("qoo10_products", "set_count_verified_at", "TIMESTAMP"),
        ("qoo10_products", "product_name_ko", "TEXT"),
        ("qoo10_products", "qoo10_title_jp", "TEXT"),
        ("qoo10_products", "qoo10_tags", "TEXT"),
        ("qoo10_products", "qoo10_option_name", "TEXT"),
        ("qoo10_products", "qoo10_marketing", "TEXT"),
        ("qoo10_products", "qoo10_content_generated_at", "TIMESTAMP"),
        ("domestic_products", "image_local_path", "TEXT"),
        ("domestic_products", "image_score_overall", "REAL"),
        ("domestic_products", "image_score_json", "TEXT"),
        ("domestic_products", "shipping_kind", "TEXT"),
        ("domestic_products", "shipping_amount", "INTEGER"),
        ("domestic_products", "shipping_threshold", "INTEGER"),
        ("domestic_products", "detail_scraped_at", "TIMESTAMP"),
        ("domestic_products", "detail_image_paths", "TEXT"),
        ("domestic_products", "weight_g", "REAL"),
        ("domestic_products", "weight_source", "TEXT"),
        ("brands", "aliases", "TEXT DEFAULT '[]'"),
        ("qoo10_products", "cover_description", "TEXT"),
        ("domestic_products", "cover_description", "TEXT"),
        ("domestic_match_candidates", "quality_score", "REAL"),
        ("domestic_products", "extras_eval_json", "TEXT"),
        ("qoo10_products", "qoo10_jp_detail", "TEXT"),
    ]
    for table, col, col_type in new_columns:
        try:
            if is_postgres:
                await conn.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"
                )
            else:
                # SQLite — PRAGMA 로 컬럼 존재 확인
                res = await conn.exec_driver_sql(f"PRAGMA table_info({table})")
                cols = [row[1] for row in res.fetchall()]
                if col not in cols:
                    await conn.exec_driver_sql(
                        f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                    )
        except Exception:
            # 이미 있거나 권한 문제 — 다음 시작에 지장 없음
            pass


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
app.include_router(margin.router)
app.include_router(recommendations.router)
app.include_router(user_data.router)
app.include_router(automation.router)
app.include_router(extension.router)

# 이미지 폴더 정적 서빙 — 패널이 한국 SKU extras 보여주기 위해 (WWW-1)
_IMAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "image"
if _IMAGE_ROOT.exists():
    app.mount("/image", StaticFiles(directory=str(_IMAGE_ROOT)), name="image")

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

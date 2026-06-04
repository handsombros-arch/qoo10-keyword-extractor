import os
from pathlib import Path

from dotenv import load_dotenv


# .env 파일 로드 (backend/.env)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BACKEND_DIR / ".env")


class Settings:
    APP_NAME: str = "Qoo10 키워드 추출기"
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    DB_PATH: Path = DATA_DIR / "qoo10.db"
    SESSION_DIR: Path = DATA_DIR / "session"
    COOKIES_PATH: Path = SESSION_DIR / "cookies.json"
    DATABASE_URL: str = ""

    CORS_ORIGINS: list = ["http://localhost:5173", "http://127.0.0.1:5173"]

    QSM_URL: str = "https://qsm.qoo10.jp/"
    QOO10_SEARCH_URL: str = "https://www.qoo10.jp/s/"
    QOO10_ADPLUS_URL: str = "https://qsm.qoo10.jp/GMKT.INC.Gsm.Web/ADPlus/"
    QOO10_BESTSELLER_URL: str = "https://www.qoo10.jp/gmkt.inc/Bestsellers/"
    PAPAGO_URL: str = "https://papago.naver.com/"
    # Papago NCP(네이버 클라우드) NMT API — 유료. 크리덴셜 있으면 Papago, 없으면 Google 폴백.
    PAPAGO_API_URL: str = "https://naveropenapi.apigw.ntruss.com/nmt/v1/translation"
    PAPAGO_CLIENT_ID: str = ""
    PAPAGO_CLIENT_SECRET: str = ""
    COUPANG_SEARCH_URL: str = "https://www.coupang.com/np/search"
    NAVER_SHOPPING_URL: str = "https://search.shopping.naver.com/search/all"

    def __init__(self):
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.SESSION_DIR.mkdir(parents=True, exist_ok=True)

        # Papago NCP 크리덴셜 (.env). 비어있으면 Google 폴백.
        self.PAPAGO_CLIENT_ID = os.getenv("PAPAGO_CLIENT_ID", "").strip()
        self.PAPAGO_CLIENT_SECRET = os.getenv("PAPAGO_CLIENT_SECRET", "").strip()
        _papago_url = os.getenv("PAPAGO_API_URL", "").strip()
        if _papago_url:
            self.PAPAGO_API_URL = _papago_url

        env_url = os.getenv("DATABASE_URL", "").strip()
        if env_url:
            # postgresql:// → postgresql+asyncpg:// 로 자동 변환
            if env_url.startswith("postgresql://") and "+asyncpg" not in env_url:
                env_url = env_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            # asyncpg는 ?pgbouncer=true 같은 쿼리 파라미터를 모름 → 제거
            if "?" in env_url:
                env_url = env_url.split("?", 1)[0]
            self.DATABASE_URL = env_url
        else:
            # 폴백: 로컬 SQLite (개발/오프라인용)
            self.DATABASE_URL = f"sqlite+aiosqlite:///{self.DB_PATH}"


settings = Settings()

# 세팅 가이드

두 대 이상의 PC에서 같은 데이터를 공유하며 작업하기 위한 Supabase 기반 세팅.

## 아키텍처

- **코드**: GitHub (이 저장소) — `git pull`/`push`로 동기화
- **DB**: Supabase Postgres — PC 간 자동 공유
- **세션 쿠키**: PC 로컬 (`backend/data/session/`) — PC마다 Qoo10에 따로 로그인
- **실행**: 각 PC에서 `start.pyw` 더블클릭 (localhost:8000)

---

## 1. Supabase 프로젝트 생성 (최초 1회, 한쪽 PC에서)

1. https://supabase.com 로그인 → **New project**
2. 이름: `qoo10-extractor` / Region: `Northeast Asia (Seoul)` 권장
3. DB 비밀번호 설정 (분실 시 재설정 가능)
4. 프로젝트 생성 후 **Project Settings → Database → Connection string → URI** 의 **Transaction pooler (port 6543)** 또는 **Direct (port 5432)** 복사
5. 형식: `postgresql://postgres.xxxx:비밀번호@aws-1-ap-northeast-2.pooler.supabase.com:5432/postgres`

> 테이블은 앱 첫 실행 시 `Base.metadata.create_all`로 자동 생성됩니다. 별도 스키마 SQL 실행 불필요.

## 2. PC별 공통 세팅

```bash
git clone https://github.com/handsombros-arch/qoo10-keyword-extractor.git
cd qoo10-keyword-extractor

# 백엔드
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# .env 생성 (Supabase URL 붙여넣기)
copy .env.example .env
# → .env 열어서 DATABASE_URL 값 수정

# 프론트엔드
cd ..\frontend
npm install
npm run build
```

## 3. (선택) 기존 SQLite 데이터 1회 이관

원래 PC에 `backend/data/qoo10.db` 데이터가 있다면 이관:

```bash
cd backend
.venv\Scripts\activate
python scripts/migrate_sqlite_to_postgres.py
```

- 한쪽 PC에서 **한 번만** 실행
- 이관 후에는 `backend/data/qoo10.db` 삭제 가능 (Postgres 사용 중이면 참조 안 함)

## 4. 실행

- `start.pyw` 더블클릭 → `http://localhost:8000`
- 첫 실행 시 Qoo10 로그인 화면 뜸 (쿠키는 PC별로 따로 저장됨)

---

## 일상 워크플로우

```bash
# 작업 시작
git pull

# 코드 수정...
# start.pyw 로 실행, 데이터는 Supabase에 자동 저장됨

# 코드 변경사항 공유
git add .
git commit -m "메시지"
git push
```

## 주의사항

- **두 PC에서 동시에 코드 수정 → push** 하면 충돌. 작업 전 `git pull` 먼저.
- `backend/data/session/cookies.json`은 PC별 로컬 파일 (.gitignore). 각 PC마다 Qoo10에 따로 로그인해야 함.
- Supabase 무료 티어: DB 500MB. 키워드 데이터는 수년치 쌓여도 충분.
- `.env` 파일은 git 제외됨. PC마다 직접 생성해야 함.

#!/bin/bash
# 엘비텐 맥북 RD 자동화 — 1회 셋업 스크립트
# 사용법: repo 를 clone 한 뒤  bash automation/mac/setup.sh
set -e

REPO="$HOME/qoo10-keyword-extractor"
BE="$REPO/backend"
PY="$BE/venv/bin/python"

echo "==> 1) 위치 확인"
if [ ! -d "$BE" ]; then
  echo "❌ $BE 가 없습니다. 먼저 repo 를 \$HOME 에 clone 하세요:"
  echo "   git clone https://github.com/handsombros-arch/qoo10-keyword-extractor.git ~/qoo10-keyword-extractor"
  exit 1
fi
mkdir -p "$REPO/logs"

echo "==> 2) 파이썬 가상환경 + 패키지 설치 (수 분 소요)"
cd "$BE"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium   # 실 Chrome 없을 때 폴백용

echo "==> 3) .env 확인"
if [ ! -f "$BE/.env" ]; then
  echo "⚠️  $BE/.env 가 없습니다. 윈도우 PC 의 backend/.env 를 복사해 넣어주세요."
  echo "    (최소 DATABASE_URL 한 줄은 반드시 필요 — Supabase 연결)"
fi

echo "==> 4) launchd 스케줄 파일 생성 (\$HOME 경로 자동 반영)"
LA="$HOME/Library/LaunchAgents"
mkdir -p "$LA"
sed "s|__PY__|$PY|g; s|__BE__|$BE|g; s|__REPO__|$REPO|g" \
    "$REPO/automation/mac/com.elviten.backend.plist.tmpl" > "$LA/com.elviten.backend.plist"
sed "s|__PY__|$PY|g; s|__BE__|$BE|g; s|__REPO__|$REPO|g" \
    "$REPO/automation/mac/com.elviten.rd-daily.plist.tmpl" > "$LA/com.elviten.rd-daily.plist"

echo ""
echo "✅ 셋업 끝. 다음 순서로 진행하세요 (가이드 README 참고):"
echo "  A) 백엔드 켜기:   launchctl load ~/Library/LaunchAgents/com.elviten.backend.plist"
echo "  B) 1분 뒤 Chrome 창이 뜨면 → QSM(큐텐) 로그인 1회"
echo "  C) 수동 테스트:   cd ~/qoo10-keyword-extractor && backend/venv/bin/python automation/trigger_daily_rd.py --cats 3,7"
echo "  D) 매일 자동 켜기: launchctl load ~/Library/LaunchAgents/com.elviten.rd-daily.plist"

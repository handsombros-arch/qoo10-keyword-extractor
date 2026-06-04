"""매일 자동: 키워드 RD 추출 + 낙찰가(경매) 수집 — 뷰티/식품 기본.

당일 안 뽑으면 다음날 못 뽑으므로(큐텐 일자 데이터 복구 불가) 매일 1회 자동 수집.
맥북 24h 서버의 launchd/cron 에서 호출하는 용도. 백엔드(start.pyw 상응)가 실행 중이어야 함.

사용:
    python automation/trigger_daily_rd.py                 # 뷰티(3)+식품(7), 낙찰가 포함
    python automation/trigger_daily_rd.py --cats 3,7,2    # 카테고리 직접 지정
    python automation/trigger_daily_rd.py --no-bids       # 낙찰가 제외
    python automation/trigger_daily_rd.py --olive         # 올리브영 랭킹도 같이

전제: 데이터 안전가드(save_keywords)가 들어가 있어 0건/부분실패 시 기존 보존됨.
"""
from __future__ import annotations

import argparse
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx

BACKEND = "http://localhost:8000"
POLL = 5
DEFAULT_CATS = [3, 7]   # 03.뷰티&화장품, 07.식품


def _poll(client: httpx.Client, task_id: str, label: str) -> bool:
    last = ""
    while True:
        try:
            t = client.get(f"{BACKEND}/api/tasks/{task_id}", timeout=15).json()
        except Exception as e:
            print(f"  [{label}] 조회 실패(재시도): {e}")
            time.sleep(POLL); continue
        st, msg = t.get("status"), t.get("message", "")
        if msg != last:
            print(f"  [{label}] [{st}] {t.get('progress', 0)}/{t.get('total', 0)} — {msg}")
            last = msg
        if st == "completed":
            return True
        if st == "failed":
            print(f"  [{label}] 실패: {msg}")
            return False
        time.sleep(POLL)


def main() -> int:
    p = argparse.ArgumentParser(description="일일 키워드 RD + 낙찰가 수집")
    p.add_argument("--cats", default=",".join(map(str, DEFAULT_CATS)),
                   help="카테고리 코드 콤마구분 (기본 3,7 = 뷰티/식품)")
    p.add_argument("--no-bids", action="store_true", help="낙찰가 수집 제외")
    p.add_argument("--olive", action="store_true", help="올리브영 랭킹도 같이 수집")
    p.add_argument("--backend", default=BACKEND)
    args = p.parse_args()
    cats = [int(x) for x in args.cats.split(",") if x.strip().isdigit()]

    with httpx.Client() as c:
        # 로그인 체크
        try:
            st = c.get(f"{args.backend}/api/auth/status", timeout=10).json()
            if not (st.get("logged_in") or st.get("is_logged_in")):
                print("[ERR] 큐텐 미로그인 — 수집 불가. 백엔드 Chrome 로그인 필요.")
                return 1
        except Exception as e:
            print(f"[ERR] 백엔드 응답 없음: {e} (start.pyw 실행 확인)")
            return 1

        body = {
            "categories": cats,
            "translate": True,
            "fill_total_products": True,
            "collect_bids": not args.no_bids,
        }
        print(f"[trigger] 키워드 RD 수집 카테고리={cats} 낙찰가={'O' if not args.no_bids else 'X'}")
        try:
            r = c.post(f"{args.backend}/api/keywords/trend", json=body, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"[ERR] 수집 시작 실패: {e}")
            return 1
        data = r.json()
        if data.get("error"):
            print(f"[ERR] {data['error']}")
            return 1
        tid = data.get("master_task_id")
        print(f"[OK] 시작: {data.get('message', '')}")
        ok = _poll(c, tid, "RD") if tid else True

        # 올리브영(옵션)
        if args.olive:
            try:
                r2 = c.post(f"{args.backend}/api/kr-trend/collect", params={"top_n": 30}, timeout=30)
                t2 = (r2.json() or {}).get("master_task_id")
                print("[OK] 올리브영 수집 시작")
                if t2:
                    _poll(c, t2, "올영")
            except Exception as e:
                print(f"  [올영] 실패: {e}")

        print("[완료] 일일 수집 종료" if ok else "[경고] 수집 실패 — 로그 확인(데이터는 가드로 보존)")
        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

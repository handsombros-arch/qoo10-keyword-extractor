import re
from datetime import date

from app.scrapers.base import BaseScraper


class RankingTrackerScraper(BaseScraper):
    """M10: 검색 노출 순위 추적"""

    async def run(self, items: list[dict], **params) -> dict:
        page = await self.browser.get_page()
        task_id = self.tasks.create_task("순위 추적", len(items))
        self.tasks.start_task(task_id)

        results = []

        try:
            for item in items:
                product_id = item.get("product_id", "")
                keyword = item.get("keyword", "")
                tracking_item_id = item.get("id", 0)

                self.tasks.update_progress(task_id, 0, f"'{keyword}' 순위 확인 중...")

                search_url = f"https://www.qoo10.jp/s/?keyword={keyword}"
                await page.goto(search_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                rank = await self._find_product_rank(page, product_id)

                results.append({
                    "tracking_item_id": tracking_item_id,
                    "lookup_date": date.today(),
                    "rank_position": rank,
                })

                rank_display = f"{rank}위" if rank > 0 else "100위 이상"
                self.tasks.update_progress(task_id, 1, f"'{keyword}' → {rank_display}")

            self.tasks.complete_task(task_id, f"{len(results)}개 항목 순위 추적 완료")
            return {"task_id": task_id, "results": results}

        except Exception as e:
            self.tasks.fail_task(task_id, str(e))
            return {"task_id": task_id, "error": str(e)}

    # 현 큐텐 검색결과: 상품ID = goodscode 속성 (구 data-item-no / a[href*=/g/] 폐기됨, 2026-06 검증).
    # [goodscode] 요소를 DOM 순서로 중복제거 → 순위 리스트. product_id(=goodscode) 위치가 순위.
    _RANK_JS = """() => {
      const out = []; const seen = new Set();
      for (const e of document.querySelectorAll('[goodscode],[data-goodscode]')) {
        const gc = e.getAttribute('goodscode') || e.getAttribute('data-goodscode');
        if (gc && !seen.has(gc)) { seen.add(gc); out.push(String(gc)); }
      }
      return out;
    }"""

    async def _find_product_rank(self, page, product_id: str, max_rank: int = 100) -> int:
        """상품 순위 찾기 — goodscode 순서 기반 (2026-06 재작성, 207개 추출+라운드트립 검증)."""
        # 충분히 스크롤해 결과 로드
        for _ in range(8):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)
        try:
            ranked = await page.evaluate(self._RANK_JS)
        except Exception:
            return 0
        pid = str(product_id).strip()
        for i, gc in enumerate(ranked):
            if i >= max_rank:
                break
            if gc == pid:
                return i + 1
        return 0  # 0 = 미발견 (max_rank 내 없음)

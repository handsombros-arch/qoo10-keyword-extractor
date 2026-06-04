"""네이버 검색결과 __NEXT_DATA__ 파서 (R-9, 2026-06-04).

확장(진짜 Chrome, AKAMAI 통과)이 search.shopping.naver.com 검색결과의
__NEXT_DATA__ 를 떠오면, 거기서 상품을 구조화 추출한다.

원본 VBA 는 깨지기 쉬운 DOM 클래스(basicList_*, "22.11.27 변경" 도배)를 긁지만,
여기선 SSR 구조화 데이터(props.pageProps)를 파싱 → 셀렉터 깨짐 없음 + 배송비 포함.

리스트 위치:
- props.pageProps.compositeList.list[].item   (type=product, 메인 ~46개)
- props.pageProps.superSavingProducts[]        (슈퍼세이빙 보충 ~13개)
필드: productTitle/productName, lowPrice/price, dlvryFee(배송비, '0'=무료),
      mallName, mallProductUrl(smartstore 직링크), category1~4Name, imageUrl, rank ...
"""
import re
from typing import List, Dict


def _to_int(v) -> int | None:
    if v is None:
        return None
    s = re.sub(r"[^\d]", "", str(v))
    return int(s) if s != "" else None


def _category(item: dict) -> str:
    parts = [item.get(f"category{i}Name") for i in range(1, 5)]
    return " > ".join(p for p in parts if p)


def _parse_product(item: dict) -> Dict:
    dlvry = item.get("dlvryFee")
    if dlvry in (None, ""):
        dlvry = item.get("krwDlvryFee")
    if dlvry in (None, ""):
        dlvry = item.get("deliveryFeeContent")
    return {
        "product_name": item.get("productTitle") or item.get("productName"),
        "product_name_full": item.get("productName"),
        "price": _to_int(item.get("lowPrice") or item.get("price")),
        "shipping_fee": _to_int(dlvry),            # 0 = 무료배송, None = 미상
        "shop_name": item.get("mallName"),
        "product_url": item.get("mallProductUrl") or item.get("mallPcUrl"),
        "category": _category(item),
        "image_url": item.get("imageUrl"),
        "rank": item.get("rank"),
        "mall_product_id": item.get("mallProductId") or item.get("id"),
        "review_count": item.get("reviewCountSum"),
        "maker": item.get("maker") or item.get("comNm"),
    }


def parse_naver_search_dump(dump: dict, max_results: int = 50) -> List[Dict]:
    """확장 naverSearchDump 결과(next_data 포함 dict) → 상품 리스트(배송비 포함)."""
    nd = (dump or {}).get("next_data") or {}
    pp = (nd.get("props") or {}).get("pageProps") or {}
    out: List[Dict] = []
    seen = set()

    def _add(item: dict):
        if not isinstance(item, dict):
            return
        if not (item.get("productTitle") or item.get("productName")):
            return
        p = _parse_product(item)
        key = p.get("product_url") or p.get("mall_product_id") or p.get("product_name")
        if key and key not in seen:
            seen.add(key)
            out.append(p)

    # 1) 메인 리스트 — compositeList.list[].item (type=product)
    cl = pp.get("compositeList") or {}
    for entry in (cl.get("list") or []):
        if isinstance(entry, dict) and entry.get("type") == "product":
            _add(entry.get("item"))

    # 2) 슈퍼세이빙 보충 (중복 제거)
    for item in (pp.get("superSavingProducts") or []):
        _add(item)

    return out[:max_results]

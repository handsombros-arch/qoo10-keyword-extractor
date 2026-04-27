from datetime import date, datetime

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Keyword(Base):
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword_jp = Column(String, nullable=False)
    keyword_kr = Column(String)
    lookup_date = Column(Date, default=date.today)
    category = Column(String)             # M02 트렌드 페이지에서 수집한 큐텐 카테고리 그룹
    category_inferred = Column(String)    # LLM 추론 카테고리 (03.뷰티&화장품 등 6분류 + 기타)
    is_brand = Column(Integer, default=0) # 0=일반, 1=브랜드 (LLM + whitelist 판별)
    brand_kr = Column(String)
    brand_jp = Column(String)
    brand_en = Column(String)
    classification = Column(String)  # 원본/유사/연관
    rank = Column(Integer)
    index_key = Column(String)
    competition_intensity = Column(Float)
    search_volume_weekly = Column(Integer)
    search_volume_daily = Column(Integer)
    total_products = Column(Integer)
    products_jp = Column(Integer)
    products_kr = Column(Integer)
    products_cn = Column(Integer)
    products_other = Column(Integer)
    volume_change_flag = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)


class VolumeHistory(Base):
    __tablename__ = "volume_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lookup_date = Column(Date, default=date.today)
    index_key = Column(String)
    keyword_jp = Column(String)
    competition_intensity = Column(Float)
    search_volume_weekly = Column(Integer)
    search_volume_daily = Column(Integer)
    total_products = Column(Integer)
    products_jp = Column(Integer)
    products_kr = Column(Integer)
    products_cn = Column(Integer)
    products_other = Column(Integer)


class BidHistory(Base):
    __tablename__ = "bid_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lookup_date = Column(Date, default=date.today)
    index_key = Column(String)
    keyword_jp = Column(String)
    related_keyword_count = Column(Integer)
    bid_count = Column(Integer)
    search_volume_weekly = Column(Integer)
    search_volume_daily = Column(Integer)
    bid_price_1 = Column(Integer)
    bid_price_2 = Column(Integer)
    bid_price_3 = Column(Integer)
    bid_price_4 = Column(Integer)
    bid_price_5 = Column(Integer)
    bid_price_6 = Column(Integer)
    bid_price_7 = Column(Integer)
    bid_price_8 = Column(Integer)
    bid_price_9 = Column(Integer)
    bid_price_10 = Column(Integer)


class TrackingItem(Base):
    __tablename__ = "tracking_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(String, nullable=False)
    keyword = Column(String, nullable=False)
    product_name = Column(String)
    cover_image_url = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    histories = relationship("TrackingHistory", back_populates="tracking_item")


class TrackingHistory(Base):
    __tablename__ = "tracking_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tracking_item_id = Column(Integer, ForeignKey("tracking_items.id"))
    lookup_date = Column(Date, default=date.today)
    rank_position = Column(Integer)
    tracking_item = relationship("TrackingItem", back_populates="histories")


class Qoo10Product(Base):
    __tablename__ = "qoo10_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    search_keyword = Column(String)
    product_name = Column(String)
    price_jpy = Column(Integer)
    shipping_fee = Column(String)
    origin = Column(String)
    cover_image_url = Column(String)
    product_url = Column(String)
    lookup_date = Column(Date, default=date.today)
    set_count = Column(Integer, default=1)         # 묶음 개수 (정규식+LLM 추출)
    set_count_source = Column(String)               # "regex" / "llm" / "default"
    set_count_vision = Column(Integer)              # 비전이 본 패키지 수 (200%+ 마진 케이스만)
    set_count_vision_confidence = Column(Float)
    set_count_verified_at = Column(DateTime)
    product_name_ko = Column(String)                # 일본어 → 한국어 번역 (번역 캐시 활용)


class DomesticProduct(Base):
    __tablename__ = "domestic_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String)  # "coupang" or "naver"
    search_keyword = Column(String)
    product_name = Column(String)
    price_krw = Column(Integer)
    price_usd = Column(Float)
    shipping_fee = Column(String)
    origin = Column(String)
    cover_image_url = Column(String)
    product_url = Column(String)
    lookup_date = Column(Date, default=date.today)
    image_local_path = Column(String)        # image/{date}/{kr_name}/cover.jpg
    image_score_overall = Column(Float)       # 정렬용 종합 점수
    image_score_json = Column(Text)           # 4항목 raw 점수 JSON
    # ─── Phase 2 — 상세 페이지 진입 결과 ───
    shipping_kind = Column(String)            # "free" / "paid" / "conditional" / "unknown"
    shipping_amount = Column(Integer)         # paid/conditional 시 KRW
    shipping_threshold = Column(Integer)      # conditional 시 무료 기준 (예: 50000)
    detail_scraped_at = Column(DateTime)      # 상세 진입 처리 시점
    detail_image_paths = Column(Text)         # 누끼/내용물 이미지 로컬 경로 JSON 배열
    # ─── Phase 4 — 무게 추출 ───
    weight_g = Column(Float)                  # +200g 패키지 룰 적용된 등록용 무게 (g)
    weight_source = Column(String)            # "name" / "ocr" / "manual" / "default"


class DomesticProductOption(Base):
    """한국 상품 옵션 단위 가격 (1:N).

    상세 페이지에서 옵션 셀렉트(드롭다운/라디오/컬러칩 등)를 클릭하며
    각 옵션의 가격을 캡처. 같은 product_id 의 옵션은 captured_at 갱신 시 모두 덮어씀
    (이전 옵션은 별도 테이블에 보존하지 않고 최신 스냅샷만 유지).

    option_name 예시: "30ml", "블랙", "1+1 패키지", "Set A".
    """
    __tablename__ = "domestic_product_options"

    id = Column(Integer, primary_key=True, autoincrement=True)
    domestic_product_id = Column(Integer, ForeignKey("domestic_products.id"), index=True)
    option_name = Column(String, nullable=False)
    option_price_krw = Column(Integer)
    in_stock = Column(Integer, default=1)        # 0=품절, 1=재고
    captured_at = Column(DateTime, default=datetime.utcnow)


class BestsellerItem(Base):
    __tablename__ = "bestseller_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category = Column(String)
    category_code = Column(Integer)
    rank = Column(Integer)
    product_name = Column(String)
    brand = Column(String)
    price_jpy = Column(Integer)
    shipping_fee = Column(String)
    origin = Column(String)
    cover_image_url = Column(String)
    product_url = Column(String)
    sales_volume = Column(Integer)
    lookup_date = Column(Date, default=date.today)


class UserData(Base):
    """범용 JSON 저장: 시트·관심 키워드·샵 캐시 등을 PC 간 공유."""
    __tablename__ = "user_data"

    key = Column(String, primary_key=True)
    data = Column(Text)  # JSON 문자열
    updated_at = Column(DateTime, default=datetime.utcnow)


class TranslationCache(Base):
    """번역 캐시 (jp → ko 등 일반).

    같은 원문이 여러 lookup_date 에 반복 등장하므로 1회 번역 후 재사용.
    PK 는 (source_text, source_lang, target_lang) 복합 키 — 향후 다른 언어쌍 확장 대비.
    """
    __tablename__ = "translation_cache"

    source_text = Column(String, primary_key=True)
    source_lang = Column(String, primary_key=True, default="ja")
    target_lang = Column(String, primary_key=True, default="ko")
    translated = Column(Text, nullable=False)
    model = Column(String)              # "ollama:qwen2.5:7b" 등
    created_at = Column(DateTime, default=datetime.utcnow)


class DomesticMatchCandidate(Base):
    """큐텐 ↔ 한국 상품 매칭 후보 (3-1, 3-2 결과).

    같은 (qoo10_product_id, domestic_product_id) 쌍 중복 방지.
    한 큐텐 상품에 여러 후보가 있을 수 있으며 score 내림차순 정렬해 사용.

    source_match_kind:
      - "keyword": 큐텐 search_keyword(jp→kr 번역)으로 검색된 한국 상품 (기존 흐름)
      - "translated_name": 번역된 큐텐 product_name_ko 로 검색된 결과
      - "brand_expanded": 브랜드 키워드 확장 (3-2)에서 발견된 결과

    decision: "pending" | "accepted" | "rejected" — 임계값 + 향후 사용자 검수
    """
    __tablename__ = "domestic_match_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    qoo10_product_id = Column(Integer, ForeignKey("qoo10_products.id"), index=True)
    domestic_product_id = Column(Integer, ForeignKey("domestic_products.id"), index=True)
    source_match_kind = Column(String)
    name_score = Column(Float)                  # 텍스트 유사도 (선택)
    image_score = Column(Float)                 # 비전 유사도 0~1
    image_match_note = Column(Text)             # 비전 사유 텍스트
    decision = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)


class Brand(Base):
    """K-뷰티/식품 브랜드 화이트리스트.

    LLM 호출 절감 + 의역 방지용. brand.py 의 1차 매칭 소스.
    두 PC가 같은 Supabase 를 보므로 자동 추가가 즉시 양쪽에서 가시화됨.

    source:
      - "seed": 초기 시드 (scripts/seed_brands.py)
      - "auto": LLM 판별 후 confidence > BRAND_AUTO_ADD_THRESHOLD (기본 0.9)
      - "manual": 셀러가 직접 추가
    """
    __tablename__ = "brands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kr = Column(String, nullable=False, unique=True, index=True)
    jp = Column(String, default="")
    en = Column(String, default="")
    source = Column(String, default="auto")
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

"""의미 기반 상품 매칭.

큐텐 일본어 키워드 (또는 한국어 검색 키워드) 와 네이버 한국어 상품명 후보들 사이
임베딩 유사도를 계산해 가짜 매칭(번역 단어는 같지만 다른 상품)을 걸러낸다.

모델: BAAI/bge-m3 (다국어 SOTA)
- 첫 호출 시 ~2GB 다운로드 (Hugging Face 캐시: %USERPROFILE%\.cache\huggingface\)
- GPU(CUDA) 자동 감지, 없으면 CPU
- VRAM ~2.3GB / 100건 임베딩 ~0.1s on GPU

import 자체가 무거우므로 함수 내부에서 지연 로딩.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL = None
_MODEL_LOCK = threading.Lock()
_MODEL_NAME = "BAAI/bge-m3"
_LOAD_FAILED = False


def _get_model():
    """모델 lazy load. 한 번만 로드 후 캐시. 실패 시 None 반환 (fallback 용)."""
    global _MODEL, _LOAD_FAILED
    if _MODEL is not None:
        return _MODEL
    if _LOAD_FAILED:
        return None

    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        if _LOAD_FAILED:
            return None
        try:
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            logger.warning(
                f"[semantic_match] sentence-transformers 미설치 ({e}). "
                f"임베딩 매칭 비활성화 — pip install sentence-transformers"
            )
            _LOAD_FAILED = True
            return None

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"[semantic_match] 모델 로딩: {_MODEL_NAME} on {device}")
        try:
            _MODEL = SentenceTransformer(_MODEL_NAME, device=device)
            logger.info(f"[semantic_match] 모델 로드 완료 (device={device})")
        except Exception as e:
            logger.error(f"[semantic_match] 모델 로드 실패: {e}", exc_info=True)
            _LOAD_FAILED = True
            return None
    return _MODEL


def is_available() -> bool:
    """모델이 로드 가능한지 (호출 시 로드 시도)."""
    return _get_model() is not None


def match_candidates(
    query: str,
    candidates: list[str],
    threshold: float = 0.5,
) -> list[tuple[int, float]]:
    """query 와 각 candidate 의 코사인 유사도. threshold 이상만 (idx, score) 반환.

    score 내림차순. 모델 사용 불가 시 모든 인덱스를 score=None 으로 반환 (fallback).
    """
    if not query or not candidates:
        return []

    model = _get_model()
    if model is None:
        # fallback: 모두 통과 시그널
        return [(i, 0.0) for i in range(len(candidates))]

    try:
        from sentence_transformers import util  # noqa: WPS433
        q_emb = model.encode(
            query, convert_to_tensor=True, normalize_embeddings=True
        )
        c_emb = model.encode(
            candidates, convert_to_tensor=True, normalize_embeddings=True,
            batch_size=32,
        )
        scores = util.cos_sim(q_emb, c_emb)[0].tolist()
    except Exception as e:
        logger.error(f"[semantic_match] 임베딩 실패: {e}", exc_info=True)
        return [(i, 0.0) for i in range(len(candidates))]

    out = [(i, float(s)) for i, s in enumerate(scores) if s >= threshold]
    out.sort(key=lambda x: x[1], reverse=True)
    return out

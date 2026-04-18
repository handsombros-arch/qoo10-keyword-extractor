"""이미지 워터마크 제거 (LaMa 인페인팅)."""
import io
from typing import Optional

import numpy as np
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image

router = APIRouter(prefix="/api/image", tags=["image"])


# LaMa 모델은 최초 호출 시 지연 로딩
_model = None


def _get_model():
    global _model
    if _model is None:
        from iopaint.model.lama import LaMa
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = LaMa(device=device)
    return _model


@router.get("/capability")
async def capability():
    """현재 서버 환경 감지"""
    try:
        import torch
        has_cuda = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if has_cuda else None
        vram_gb = None
        if has_cuda:
            props = torch.cuda.get_device_properties(0)
            vram_gb = round(props.total_memory / (1024**3), 1)
        return {
            "has_cuda": has_cuda,
            "gpu_name": gpu_name,
            "vram_gb": vram_gb,
            "device": "cuda" if has_cuda else "cpu",
            "available_models": ["lama"],
        }
    except Exception as e:
        return {"has_cuda": False, "error": str(e), "available_models": ["lama"]}


@router.post("/remove-watermark")
async def remove_watermark(
    file: UploadFile = File(...),
    region: str = Form("bottom-right"),  # bottom-right / bottom-left / top-right / top-left / custom
    margin_pct: float = Form(12.0),  # 가장자리에서부터 N% 영역
    custom_mask: Optional[UploadFile] = File(None),
):
    """이미지 우하단 등 지정 영역의 워터마크를 LaMa로 제거."""
    # 입력 이미지 로드
    data = await file.read()
    img = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.array(img)
    h, w = arr.shape[:2]

    # 마스크 생성
    if custom_mask is not None:
        mdata = await custom_mask.read()
        m_img = Image.open(io.BytesIO(mdata)).convert("L").resize((w, h))
        mask = np.array(m_img)
        mask = (mask > 127).astype(np.uint8) * 255
    else:
        mask = np.zeros((h, w), dtype=np.uint8)
        pct = max(1.0, min(50.0, margin_pct)) / 100.0
        mw, mh = int(w * pct), int(h * pct)
        if region == "bottom-right":
            mask[h - mh:, w - mw:] = 255
        elif region == "bottom-left":
            mask[h - mh:, :mw] = 255
        elif region == "top-right":
            mask[:mh, w - mw:] = 255
        elif region == "top-left":
            mask[:mh, :mw] = 255
        else:
            # 기본값
            mask[h - mh:, w - mw:] = 255

    # LaMa 인페인팅 — 마스크 주변만 crop 처리해 원본 픽셀 보존
    model = _get_model()
    from iopaint.schema import InpaintRequest, HDStrategy, LDMSampler, SDSampler

    req = InpaintRequest(
        # CROP 모드: 마스크 영역만 잘라서 처리 → 나머지 이미지는 원본 그대로
        hd_strategy=HDStrategy.CROP,
        hd_strategy_crop_margin=64,
        hd_strategy_crop_trigger_size=1,  # 항상 crop 모드 발동
        hd_strategy_resize_limit=4096,
        ldm_steps=25,
        ldm_sampler=LDMSampler.plms,
        sd_sampler=SDSampler.uni_pc,
        sd_steps=20,
    )
    # iopaint LaMa는 BGR 입력/출력을 기대
    import cv2
    arr_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    result_bgr = model(arr_bgr, mask, req)
    if result_bgr.dtype != np.uint8:
        result_bgr = result_bgr.astype(np.uint8)
    result_rgb = cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB)

    # 최종 방어: 원본에 마스크 영역만 덮어써서 비마스크 픽셀 100% 보존
    final = arr.copy()
    mask_bool = mask > 127
    final[mask_bool] = result_rgb[mask_bool]

    out_img = Image.fromarray(final)
    buf = io.BytesIO()
    out_img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

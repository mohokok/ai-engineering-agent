"""Single source of truth for ALHARAM ALDAHABY / الهرم الذهبي company branding and assets."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

COMPANY_NAME_EN = "ALHARAM ALDAHABY"
COMPANY_SUBTITLE_EN = "Engineering Consultancy"
COMPANY_FULL_EN = f"{COMPANY_NAME_EN} {COMPANY_SUBTITLE_EN}"

COMPANY_NAME_AR = "الهرم الذهبي"
COMPANY_SUBTITLE_AR = "للاستشارات الهندسية"
COMPANY_FULL_AR = f"{COMPANY_NAME_AR} {COMPANY_SUBTITLE_AR}"

COMPANY_BILINGUAL_LINE = f"{COMPANY_FULL_EN} | {COMPANY_FULL_AR}"

# Exact palette derived from the owner-supplied corporate logo
BRAND_COLORS: dict[str, str] = {
    "brown": "#5A3A1A",
    "brown_dark": "#432A12",
    "gold": "#E0AE1B",
    "gold_soft": "#F7ECC4",
    "bg_cream": "#FAF7F0",
    "surface_warm": "#F4EFE4",
    "border_warm": "#E2D6BE",
    "text_primary": "#2C1D0D",
    "text_muted": "#6E5841",
    "surface_white": "#FFFFFF",
}

BACKEND_LOGO_PATH: Path = Path(__file__).resolve().parent.parent / "assets" / "branding" / "logo.jpg"
FRONTEND_LOGO_RELATIVE_URL = "/branding/logo.jpg"

DEFAULT_CLASSIFICATION = "PRELIMINARY"


def logo_sha256() -> str:
    """Return lowercase hex SHA-256 of the backend branding logo asset."""
    return sha256(BACKEND_LOGO_PATH.read_bytes()).hexdigest()


def build_classification_footer(classification: str | None = None, language: str = "ar") -> str:
    """Return standardized classification footer string with company attribution."""
    cls_text = ((classification or DEFAULT_CLASSIFICATION).strip() or DEFAULT_CLASSIFICATION).upper()
    if language == "en":
        return (
            f"{COMPANY_FULL_EN} | Classification: {cls_text} — "
            "Preliminary advisory engineering output; review and sign-off by a licensed engineer required."
        )
    return (
        f"{COMPANY_FULL_AR} ({COMPANY_FULL_EN}) | التصنيف: {cls_text} — "
        "مخرج دعم استشاري هندسي أولي؛ يتطلب المراجعة والاعتماد من مهندس مرخص قبل التنفيذ."
    )


def build_backup_branding_metadata(classification: str = DEFAULT_CLASSIFICATION) -> dict[str, str]:
    """Return immutable company branding & classification metadata embedded in backup manifests."""
    return {
        "company_name_en": COMPANY_NAME_EN,
        "company_subtitle_en": COMPANY_SUBTITLE_EN,
        "company_full_en": COMPANY_FULL_EN,
        "company_name_ar": COMPANY_NAME_AR,
        "company_subtitle_ar": COMPANY_SUBTITLE_AR,
        "company_full_ar": COMPANY_FULL_AR,
        "logo_asset": "branding/logo.jpg",
        "logo_sha256": logo_sha256(),
        "classification": classification,
        "disclaimer_en": (
            "Engineering advisory support workspace backup; outputs remain PRELIMINARY until licensed engineer review."
        ),
        "disclaimer_ar": (
            "نسخة احتياطية لمساحة العمل الاستشارية؛ تبقى المخرجات أولية (PRELIMINARY) لحين اعتماد مهندس مرخص."
        ),
    }

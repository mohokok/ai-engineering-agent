"""Consistent safe bilingual JSON error envelope builder for HTTP, validation, and 500 errors."""

from typing import Any

from fastapi.encoders import jsonable_encoder

from app.core.logging import get_correlation_id
from app.core.security import sanitize_secret_text

_STATUS_MAP: dict[int, tuple[str, str, str]] = {
    400: (
        "BAD_REQUEST",
        "The request could not be processed due to invalid input.",
        "تعذر تنفيذ الطلب بسبب مدخلات غير صالحة.",
    ),
    401: (
        "UNAUTHORIZED",
        "Authentication or API credential check failed. Verify your local Credential Manager key.",
        "فشل التحقق من مفتاح الاعتماد. تحقق من المفتاح المحفوظ في مخزن بيانات الاعتماد.",
    ),
    403: (
        "FORBIDDEN",
        "Access to this local resource was denied.",
        "تم رفض الوصول إلى هذا المورد المحلي.",
    ),
    404: (
        "NOT_FOUND",
        "The requested resource was not found.",
        "لم يتم العثور على المورد المطلوب.",
    ),
    409: (
        "CONFLICT",
        "Operation blocked to preserve existing immutable records or versions.",
        "تم منع العملية للحفاظ على السجلات أو الإصدارات غير القابلة للاستبدال.",
    ),
    413: (
        "PAYLOAD_TOO_LARGE",
        "Uploaded file batch exceeds the configured local size limit.",
        "يتجاوز حجم الملف المرفوع الحد الأقصى المسموح به.",
    ),
    422: (
        "VALIDATION_ERROR",
        "Input validation failed. Review highlighted fields and missing requirements.",
        "فشل التحقق من صحة المدخلات. راجع الحقول والمتطلبات الناقصة.",
    ),
    429: (
        "USAGE_LIMIT_EXCEEDED",
        "Configured AI usage cap or provider quota has been reached.",
        "تم بلوغ حد الاستخدام المحدد أو حصة مزود الذكاء الاصطناعي.",
    ),
    500: (
        "INTERNAL_ERROR",
        "Internal server error. Check local workspace logs with the correlation ID.",
        "حدث خطأ داخلي في الخادم. راجع سجل النظام المحلي باستخدام رقم التتبع.",
    ),
    502: (
        "PROVIDER_ERROR",
        "Upstream AI provider returned an unexpected error. Try again shortly.",
        "أرجع مزود الذكاء الاصطناعي خطأً غير متوقع. حاول مرة أخرى بعد قليل.",
    ),
    503: (
        "SERVICE_UNAVAILABLE",
        "AI service is temporarily unavailable. Deterministic engineering features remain ready.",
        "خدمة الذكاء الاصطناعي غير متاحة مؤقتاً. تبقى الأدوات الحتمية جاهزة للعمل.",
    ),
}


def build_error_payload(
    *,
    status_code: int,
    detail: Any,
    correlation_id: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    """Construct an API error payload keeping `detail` compatible while adding bilingual `error` & `correlation_id`."""
    cid = correlation_id or get_correlation_id()
    default_code, default_en, default_ar = _STATUS_MAP.get(
        status_code,
        (
            f"HTTP_{status_code}",
            f"Request failed with HTTP {status_code}.",
            f"فشل الطلب برمز الحالة HTTP {status_code}.",
        ),
    )
    resolved_code = error_code or default_code

    if status_code >= 500 and status_code not in (502, 503):
        # Never expose internal stack traces, file paths, or raw exception strings on 500s.
        safe_detail: Any = default_en
        safe_en = default_en
    else:
        if isinstance(detail, str):
            safe_detail = sanitize_secret_text(detail.strip()) or default_en
            safe_en = safe_detail
        elif isinstance(detail, list):
            encoded_list = jsonable_encoder(
                detail,
                custom_encoder={Exception: lambda exc: str(exc)},
            )
            safe_items: list[Any] = []
            parts: list[str] = []
            for item in encoded_list:
                if isinstance(item, dict):
                    cleaned_item = {
                        str(k): sanitize_secret_text(v) if isinstance(v, str) else v
                        for k, v in item.items()
                    }
                    if "msg" in cleaned_item:
                        parts.append(str(cleaned_item["msg"]))
                    safe_items.append(cleaned_item)
                else:
                    s = sanitize_secret_text(str(item))
                    safe_items.append(s)
                    parts.append(s)
            safe_detail = safe_items or default_en
            safe_en = "; ".join(parts) if parts else default_en
        else:
            safe_detail = sanitize_secret_text(str(jsonable_encoder(detail))) if detail else default_en
            safe_en = str(safe_detail)

    return {
        "detail": safe_detail,
        "error": {
            "code": resolved_code,
            "message": safe_en,
            "message_ar": default_ar,
            "correlation_id": cid,
            "status": status_code,
        },
        "correlation_id": cid,
    }

"""Owner-local live verification script for Step 04 Gemini integration.

Run locally ONLY after saving your real Gemini API key through the Settings UI
(`http://127.0.0.1:5173` -> AI Provider Settings -> Save API Key to Keyring):

    backend\\.venv\\Scripts\\python.exe scripts\\verify_gemini_live.py

This script reads the key exclusively from Windows Credential Manager (`keyring`),
never writes keys to disk/logs, and prints only sanitized model, token, and short
text-excerpt summaries for all five live acceptance checks.
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
from typing import Any, Callable
import zlib

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.db.migrations import upgrade_database  # noqa: E402
from app.db.session import create_db_engine, create_session_factory  # noqa: E402
from app.providers import (  # noqa: E402
    GeminiProvider,
    KeyringSecretStore,
    LLMRequest,
    MediaInput,
    ProviderAuthError,
    ProviderError,
    SecretStore,
)
from app.providers.base import sanitize_secret_text  # noqa: E402
from app.services.provider_settings import (  # noqa: E402
    execute_provider_request,
    get_provider_settings,
    refresh_provider_models,
    test_provider_connection,
)


class LiveStructuredCheckSchema(BaseModel):
    """Minimal schema for verifying live Gemini structured JSON output."""

    discipline: str
    classification: str
    note: str


def build_minimal_valid_pdf(text: str = "Concrete Beam Check Span 6.0m") -> bytes:
    """Construct a valid single-page PDF 1.4 byte stream with exact xref offsets."""
    safe_text = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in text)
    safe_text = safe_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream_body = f"BT\n/F1 12 Tf\n72 720 Td\n({safe_text}) Tj\nET\n".encode("ascii")

    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ),
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
        (
            f"5 0 obj\n<< /Length {len(stream_body)} >>\nstream\n".encode("ascii")
            + stream_body
            + b"endstream\nendobj\n"
        ),
    ]

    buf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(buf))
        buf.extend(obj)

    xref_pos = len(buf)
    buf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    buf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(buf)


def build_minimal_valid_png(width: int = 16, height: int = 16) -> bytes:
    """Construct a valid solid-color RGBA PNG image using Python standard library."""

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack("!I", len(data)) + chunk_type + data + struct.pack("!I", crc)

    row = b"\x00" + (b"\x1a\x56\xdb\xff" * width)
    compressed = zlib.compress(row * height)
    ihdr = struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def _short_excerpt(text: str, secret: str | None, limit: int = 140) -> str:
    clean = " ".join(sanitize_secret_text(text, secret).split())
    return clean[:limit] + ("..." if len(clean) > limit else "")


def run_live_checks(
    *,
    secret_store: SecretStore | None = None,
    client_factory: Callable[[str], Any] | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Execute the five owner-local live checks using keyring and print sanitized results."""
    settings = get_settings()
    resolved_db_url = database_url or settings.database_url
    upgrade_database(resolved_db_url, "head")
    engine = create_db_engine(resolved_db_url)
    SessionLocal = create_session_factory(engine)
    store = secret_store or KeyringSecretStore()

    owner_key = store.get_api_key("gemini")
    if not owner_key:
        raise RuntimeError(
            "No Gemini API key found in Windows Credential Manager (keyring). "
            "Open the Settings UI, save your key there, and re-run this script."
        )

    fake_bad_key = "invalid-key-live-verification-probe"
    results: dict[str, Any] = {}

    try:
        with SessionLocal() as db:
            cfg = refresh_provider_models(db, store, client_factory=client_factory)
            results["credential_backend"] = cfg.credential_backend
            results["models_source"] = cfg.models_source
            active_models = next(
                (p.get("models", []) for p in cfg.available_providers if p.get("id") == cfg.active_provider),
                [],
            )
            results["refreshed_generate_content_models_count"] = len(active_models)
            results["configured_models"] = {"fast": cfg.models.fast, "deep": cfg.models.deep}
            if cfg.model_warning:
                results["model_warning"] = cfg.model_warning

            # 1. Live Test Connection using owner's keyring-stored key
            conn_res = test_provider_connection(
                db, store, complexity="fast", client_factory=client_factory
            )
            results["check_1_test_connection"] = {
                "connected": conn_res.connected,
                "model": conn_res.model,
                "latency_ms": conn_res.latency_ms,
                "total_tokens": conn_res.usage.total_tokens,
            }

            # 2. Live invalid-key error verification (in-memory only; keyring untouched)
            bad_provider = GeminiProvider(
                fake_bad_key,
                fast_model=cfg.models.fast,
                deep_model=cfg.models.deep,
                client_factory=client_factory,
            )
            try:
                bad_provider.test_connection(model=cfg.models.fast)
            except ProviderAuthError as exc:
                results["check_2_invalid_key"] = {
                    "rejected_cleanly": True,
                    "error_type": type(exc).__name__,
                    "message": _short_excerpt(str(exc), fake_bad_key, limit=180),
                }
            except ProviderError as exc:
                results["check_2_invalid_key"] = {
                    "rejected_cleanly": True,
                    "error_type": type(exc).__name__,
                    "message": _short_excerpt(str(exc), fake_bad_key, limit=180),
                }
            else:
                raise RuntimeError("Invalid-key probe unexpectedly succeeded.")

            # 3. Live structured-JSON call
            struct_resp = execute_provider_request(
                db,
                store,
                LLMRequest(
                    prompt=(
                        "Return JSON summarizing a conceptual civil site check with "
                        "classification set to 'Preliminary'."
                    ),
                    complexity="fast",
                    response_schema=LiveStructuredCheckSchema,
                ),
                client_factory=client_factory,
            )
            results["check_3_structured_json"] = {
                "model": struct_resp.model,
                "total_tokens": struct_resp.usage.total_tokens,
                "parsed_keys": sorted(list((struct_resp.parsed_json or {}).keys()))
                if isinstance(struct_resp.parsed_json, dict)
                else [],
            }

            # 4. Live small PDF page analysis
            pdf_bytes = build_minimal_valid_pdf()
            pdf_resp = execute_provider_request(
                db,
                store,
                LLMRequest(
                    prompt="Briefly read the engineering text on this single PDF page.",
                    complexity="fast",
                    media=[MediaInput(data=pdf_bytes, mime_type="application/pdf", filename="sample.pdf")],
                    max_output_tokens=160,
                ),
                client_factory=client_factory,
            )
            results["check_4_pdf_analysis"] = {
                "model": pdf_resp.model,
                "total_tokens": pdf_resp.usage.total_tokens,
                "excerpt": _short_excerpt(pdf_resp.text, owner_key),
            }

            # 5. Live small image analysis
            png_bytes = build_minimal_valid_png()
            img_resp = execute_provider_request(
                db,
                store,
                LLMRequest(
                    prompt="Briefly describe the dominant color of this small image.",
                    complexity="fast",
                    media=[MediaInput(data=png_bytes, mime_type="image/png", filename="swatch.png")],
                    max_output_tokens=120,
                ),
                client_factory=client_factory,
            )
            results["check_5_image_analysis"] = {
                "model": img_resp.model,
                "total_tokens": img_resp.usage.total_tokens,
                "excerpt": _short_excerpt(img_resp.text, owner_key),
            }
    finally:
        engine.dispose()

    return results


def main() -> int:
    try:
        summary = run_live_checks()
    except Exception as exc:
        print(f"LIVE VERIFICATION FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

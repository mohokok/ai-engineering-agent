"""Tests for Step 09 review findings report (Orchestrator + review skill), Arabic RTL DOCX/PDF, and deliverables."""

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from docx import Document
from docx.oxml.ns import qn
import ezdxf
from fastapi.testclient import TestClient
import httpx
from openpyxl import Workbook
from PIL import Image
import pymupdf
import pytest

from app.core.config import Settings
from app.main import create_app
from app.providers.secrets import SecretStore
from app.services.workspace import resolve_project_file_path


class _InMemorySecretStore(SecretStore):
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._keys: dict[str, str] = dict(initial or {})

    @property
    def backend_name(self) -> str:
        return "InMemoryTestKeyring"

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        self._keys[provider_name] = api_key

    def get_api_key(self, provider_name: str) -> str | None:
        return self._keys.get(provider_name)

    def delete_api_key(self, provider_name: str) -> None:
        self._keys.pop(provider_name, None)


def _test_settings(tmp_path: Path) -> Settings:
    return Settings(workspaces_dir=tmp_path / "workspaces", database_url="")


def _make_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    text = (
        "Structural Design Specification Note: Clear beam span = 6.00 m, slab thickness = 220 mm, "
        "concrete grade C30, cover 35 mm. Mechanical shaft ventilation minimum 18 ACH."
    )
    page.insert_textbox(pymupdf.Rect(50, 50, 545, 790), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_dxf_bytes(*, insunits: int, width: float, height: float, layer_name: str) -> bytes:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = insunits
    msp = doc.modelspace()
    doc.layers.add(layer_name)
    pts = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height)]
    msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer_name})
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def _make_xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Schedule"
    ws["A1"] = "Room"
    ws["B1"] = "Width (m)"
    ws["C1"] = "Length (m)"
    ws["D1"] = "Area (m2)"
    ws["A2"] = "Clinic Examination Room"
    ws["B2"] = 6.0
    ws["C2"] = 4.0
    ws["D2"] = "=B2*C2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_step09_end_to_end_review_report_extractions_research_docx_pdf_rtl_and_download(
    tmp_path: Path,
) -> None:
    """Verify source-linked findings, category separation, Arabic RTL DOCX/PDF generation, 08/10 saves, and downloads."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://www.hse.gov.uk/ventilation-clinic-check":
            return httpx.Response(
                200,
                text=(
                    "<html><head><title>Healthcare Clinical Ventilation Code</title></head><body><main>"
                    "<p>Mechanical ventilation requirements for clinical rooms mandate continuous clean supply air, "
                    "minimum 18 air changes per hour in treatment suites, and documented commissioning airflow logs "
                    "prior to facility acceptance.</p>"
                    "</main></body></html>"
                ),
                headers={"content-type": "text/html"},
            )
        if url == "https://blocked.example.org/paywalled-spec":
            return httpx.Response(403, text="Forbidden")
        return httpx.Response(404, text="Not found")

    settings = _test_settings(tmp_path)
    app = create_app(
        settings,
        secret_store=_InMemorySecretStore(),
        research_http_transport=httpx.MockTransport(handler),
    )

    with TestClient(app) as client:
        # 1. Create Arabic project
        proj_res = client.post(
            "/api/projects",
            json={
                "name": "مشروع عيادة طرابلس التخصصية",
                "code": "CLN-09",
                "client_name": "المركز الصحي",
                "location": "طرابلس",
            },
        )
        assert proj_res.status_code == 201, proj_res.text
        proj = proj_res.json()
        project_id = proj["id"]
        workspace_slug = proj["workspace_slug"]

        # 2. Upload multi-format files (PDF, valid metric DXF, doubtful inches DXF, XLSX formula sheet)
        pdf_bytes = _make_pdf_bytes()
        metric_dxf = _make_dxf_bytes(insunits=6, width=6.0, height=4.0, layer_name="الجدران_المعمارية")
        doubtful_dxf = _make_dxf_bytes(insunits=1, width=3.0, height=4.0, layer_name="DOUBTFUL_INCHES")
        xlsx_bytes = _make_xlsx_bytes()

        up_res = client.post(
            f"/api/projects/{project_id}/files",
            files=[
                ("files", ("spec_clinic.pdf", pdf_bytes, "application/pdf")),
                ("files", ("plan_metric.dxf", metric_dxf, "application/dxf")),
                ("files", ("plan_doubtful.dxf", doubtful_dxf, "application/dxf")),
                (
                    "files",
                    (
                        "room_schedule.xlsx",
                        xlsx_bytes,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ),
                ),
            ],
        )
        assert up_res.status_code == 201, up_res.text
        uploaded_files = [item["file"] for item in up_res.json()["items"]]
        for f in uploaded_files:
            ext_res = client.post(f"/api/files/{f['id']}/extract", json={})
            assert ext_res.status_code == 201, ext_res.text

        # 3. Run controlled research (1 reviewed substantive source + 1 blocked 403 source)
        res_run = client.post(
            "/api/research/runs",
            json={
                "query": "clinical ventilation requirements",
                "project_id": project_id,
                "urls": [
                    "https://www.hse.gov.uk/ventilation-clinic-check",
                    "https://blocked.example.org/paywalled-spec",
                ],
                "classification": "Preliminary",
                "synthesize_with_ai": False,
            },
        )
        assert res_run.status_code == 201, res_run.text
        research_run_id = res_run.json()["id"]

        # 4. Generate Step 09 Arabic RTL Review Report (0 AI tokens baseline)
        rep_res = client.post(
            f"/api/projects/{project_id}/review-reports",
            json={
                "title": "تقرير مراجعة مخططات ومستندات العيادة",
                "discipline": "Multidisciplinary",
                "language": "ar",
                "classification": "For Review",
                "review_notes": "تحقق من المساحات وتوافق التهوية",
                "use_ai": False,
            },
        )
        assert rep_res.status_code == 201, rep_res.text
        rep = rep_res.json()

        # Classification, revision block, token counters
        assert rep["classification"] == "For Review"
        assert rep["version"] == 1
        assert rep["revision"] == "Rev 01"
        assert rep["token_usage"]["total_tokens"] == 0
        assert rep["estimated_prompt_tokens"] > 0
        assert rep["prompt_char_cap"] == 10_000
        assert rep["revision_block"]["classification"] == "For Review"
        assert rep["revision_block"]["source_files_count"] == 4
        assert rep["revision_block"]["reviewed_research_count"] == 1

        # Deterministic inventory mode produces plain inventory disclaimer + concrete findings ONLY (zero boilerplate)
        assert rep["is_inventory_only"] is True
        assert "ليس مراجعة هندسية" in (rep["summary"] or "")
        assert len(rep["document_register"]) == 4
        assert len(rep["findings"]) >= 1
        for finding in rep["findings"]:
            assert len(finding["source_links"]) >= 1
            assert "طابق القيم والوحدات المستخرجة" not in finding["recommendation"]
            for link in finding["source_links"]:
                assert link["ref_id"].startswith(("EXT-", "RES-"))
                assert link["source_id"]

        # Doubtful CAD units flagged prominently as high severity needing verification
        assert any(
            f["severity"] == "high"
            and f["status"] == "needs_verification"
            and "plan_doubtful.dxf" in f["location_or_drawing_ref"]
            for f in rep["findings"]
        )

        # Strictly separated categories & non-net-area label on area-bearing layer
        assert len(rep["verified_facts"]) >= 2
        assert rep["verified_facts_total"] >= len(rep["verified_facts"])
        assert any("https://www.hse.gov.uk/ventilation-clinic-check" in str(vf["source_links"]) for vf in rep["verified_facts"])
        assert len(rep["calculated_items"]) >= 1
        assert any("24.0 m²" in c["text"] and "مجموع هندسي وليس صافي مساحة مبنى" in c["text"] for c in rep["calculated_items"])
        assert all(
            a["text"].startswith("افتراض أولي يحتاج تأكيد المالك:")
            for a in rep["assumptions"]
        )
        assert len(rep["recommendations"]) >= 1

        # Blocked 403 URL stays in gaps, never cited in source_registry or verified_facts!
        assert any("blocked.example.org" in g for g in rep["gaps_or_unextracted"])
        assert all(r.get("url") != "https://blocked.example.org/paywalled-spec" for r in rep["source_registry"])

        # Saved in BOTH 08_Reports and 10_Final_Deliverables (DOCX + PDF each = 4 deliverables)
        deliverables = rep["deliverables"]
        assert len(deliverables) == 4
        folders_and_formats = {(d["folder_name"], d["format"]) for d in deliverables}
        assert folders_and_formats == {
            ("08_Reports", "docx"),
            ("08_Reports", "pdf"),
            ("10_Final_Deliverables", "docx"),
            ("10_Final_Deliverables", "pdf"),
        }

        # Verify companion JSON log in 08_Reports too
        short_id = rep["id"].replace("-", "")[:8]
        json_08 = resolve_project_file_path(
            settings.workspaces_dir, workspace_slug, f"08_Reports/review_{short_id}_v1.json"
        )
        assert json_08.is_file()

        # Verify DOCX RTL XML properties + Arabic content open cleanly with python-docx
        docx_deliv = [d for d in deliverables if d["folder_name"] == "10_Final_Deliverables" and d["format"] == "docx"][0]
        docx_path = resolve_project_file_path(settings.workspaces_dir, workspace_slug, docx_deliv["relative_path"])
        assert docx_path.is_file()
        doc = Document(str(docx_path))
        assert doc.sections[0]._sectPr.find(qn("w:bidi")) is not None
        assert doc.tables[0]._tbl.tblPr.find(qn("w:bidiVisual")) is not None
        docx_all_text = "\n".join(p.text for p in doc.paragraphs)
        assert "For Review" in docx_all_text
        assert "تقرير مراجعة مخططات ومستندات العيادة" in docx_all_text

        # Verify PDF renders cleanly with embedded Arabic font & text
        pdf_deliv = [d for d in deliverables if d["folder_name"] == "10_Final_Deliverables" and d["format"] == "pdf"][0]
        pdf_path = resolve_project_file_path(settings.workspaces_dir, workspace_slug, pdf_deliv["relative_path"])
        assert pdf_path.is_file()
        pdf_doc = pymupdf.open(str(pdf_path))
        assert len(pdf_doc) >= 1
        pdf_text = "\n".join(page.get_text("text") for page in pdf_doc)
        pdf_norm = pdf_text.replace("\xa0", " ").replace("\xad", "-")
        assert "CLN-09" in pdf_norm
        assert "For Review" in pdf_norm
        assert "Rev 01" in pdf_norm
        pdf_doc.close()

        # Verify Deliverables endpoints + download SHA-256 round-trip
        all_delivs = client.get(f"/api/deliverables?project_id={project_id}").json()
        assert all_delivs["total"] == 4
        only_10 = client.get(f"/api/projects/{project_id}/deliverables?folder_name=10_Final_Deliverables").json()
        assert only_10["total"] == 2

        for d in (docx_deliv, pdf_deliv):
            dl = client.get(d["download_url"])
            assert dl.status_code == 200
            assert "attachment" in (dl.headers.get("content-disposition") or "").lower()
            assert hashlib.sha256(dl.content).hexdigest() == d["sha256"]

        # Tamper detection on download: mutating file on disk fails integrity check cleanly
        pdf_path.write_bytes(b"corrupted bytes")
        tampered = client.get(pdf_deliv["download_url"])
        assert tampered.status_code == 400
        assert "integrity mismatch" in tampered.json()["detail"].lower()


def test_step09_ai_enhance_caps_prompt_enforces_ref_links_versions_cleanly_and_checks_step04(
    tmp_path: Path,
) -> None:
    """Verify AI enhancement caps prompt chars, drops hallucinated unlinked findings, versions v1->v2 cleanly, and obeys Step 04."""
    captured_prompts: list[str] = []

    def client_factory(_key: str) -> Any:
        class _Models:
            def list(self) -> list[Any]:
                return []

            def generate_content(self, **kwargs: Any) -> Any:
                prompt_str = "\n".join(str(p) for p in (kwargs.get("contents") or []))
                captured_prompts.append(prompt_str)
                return SimpleNamespace(
                    text="{}",
                    parsed={
                        "executive_summary": "AI-reviewed structural specification and schedule alignment.",
                        "findings": [
                            {
                                "finding_id": "REV-AI-1",
                                "discipline": "Structural",
                                "severity": "medium",
                                "location_or_drawing_ref": "spec_clinic.pdf Page 1",
                                "evidence": "Beam span 6.00 m and C30 concrete cover 35 mm require exposure class verification.",
                                "recommendation": "Confirm exposure class against soil report.",
                                "status": "needs_verification",
                                "statement_category": "verified_fact",
                                "source_ref_ids": ["EXT-1"],
                            },
                            {
                                "finding_id": "REV-FAKE-DROP",
                                "discipline": "Electrical",
                                "severity": "critical",
                                "location_or_drawing_ref": "Imaginary Sheet E-99",
                                "evidence": "Invented generator rating 999 kVA.",
                                "recommendation": "Ignore.",
                                "status": "open",
                                "statement_category": "verified_fact",
                                "source_ref_ids": ["NONEXISTENT-999"],
                            },
                        ],
                        "verified_facts": [
                            {"text": "Slab thickness noted as 220 mm in PDF spec.", "source_ref_ids": ["EXT-1"]},
                            {"text": "Invented fake fact without valid source.", "source_ref_ids": ["BAD-REF"]},
                        ],
                        "assumptions": ["Site soil sulfate class requires geotechnical verification."],
                        "recommendations": ["Coordinate slab openings with HVAC shaft duct sizes."],
                        "suggested_classification": "For Approval",
                    },
                    usage_metadata=SimpleNamespace(prompt_token_count=760, candidates_token_count=120, total_token_count=880),
                )

        return SimpleNamespace(models=_Models())

    settings = _test_settings(tmp_path)
    app = create_app(
        settings,
        secret_store=_InMemorySecretStore({"gemini": "test-step09-gemini"}),
        provider_client_factory=client_factory,
    )

    with TestClient(app) as client:
        # 0-source project with use_ai=True MUST spend 0 Gemini tokens!
        empty_proj = client.post("/api/projects", json={"name": "Empty Project", "code": "EMP-09"}).json()
        empty_rep = client.post(
            f"/api/projects/{empty_proj['id']}/review-reports",
            json={"language": "en", "classification": "Preliminary", "use_ai": True},
        )
        assert empty_rep.status_code == 201
        assert len(captured_prompts) == 0
        assert empty_rep.json()["token_usage"]["total_tokens"] == 0

        # Project with substantive PDF extract + English LTR report
        proj = client.post("/api/projects", json={"name": "Hospital Wing B", "code": "HWB-09"}).json()
        pid = proj["id"]
        slug = proj["workspace_slug"]

        up = client.post(
            f"/api/projects/{pid}/files",
            files=[("files", ("spec_clinic.pdf", _make_pdf_bytes(), "application/pdf"))],
        )
        assert up.status_code == 201

        # Generate v1 deterministically (0 tokens) in English LTR
        v1_res = client.post(
            f"/api/projects/{pid}/review-reports",
            json={
                "language": "en",
                "classification": "For Coordination",
                "use_ai": False,
            },
        )
        assert v1_res.status_code == 201, v1_res.text
        v1 = v1_res.json()
        assert v1["version"] == 1
        assert v1["revision"] == "Rev 01"
        assert v1["classification"] == "For Coordination"
        assert v1["estimated_prompt_tokens"] > 0
        assert len(captured_prompts) == 0

        # Verify v1 English DOCX does NOT force RTL w:bidi on section
        v1_docx_rel = [d["relative_path"] for d in v1["deliverables"] if d["format"] == "docx" and d["folder_name"] == "10_Final_Deliverables"][0]
        v1_docx_path = resolve_project_file_path(settings.workspaces_dir, slug, v1_docx_rel)
        v1_sha_before = hashlib.sha256(v1_docx_path.read_bytes()).hexdigest()
        assert Document(str(v1_docx_path)).sections[0]._sectPr.find(qn("w:bidi")) is None

        # Enhance v1 via AI -> creates NEW v2 (Rev 02), keeps v1 untouched, drops unlinked hallucinations!
        v2_res = client.post(
            f"/api/review-reports/{v1['id']}/ai-synthesize",
            json={"complexity": "fast"},
        )
        assert v2_res.status_code == 200, v2_res.text
        v2 = v2_res.json()
        assert v2["version"] == 2
        assert v2["revision"] == "Rev 02"
        assert v2["status"] == "ai_enhanced"
        # Owner's For Coordination classification NOT overwritten to AI's For Approval suggestion
        assert v2["classification"] == "For Coordination"
        assert v2["token_usage"]["total_tokens"] == 880
        assert len(captured_prompts) == 1
        assert "<UNTRUSTED_EXTRACTED_EVIDENCE>" in captured_prompts[0]
        assert len(captured_prompts[0]) < 12_000

        finding_ids = [f["finding_id"] for f in v2["findings"]]
        assert "REV-AI-1" in finding_ids
        assert "REV-FAKE-DROP" not in finding_ids
        assert all("Invented fake fact" not in vf["text"] for vf in v2["verified_facts"])
        assert any(a["text"].startswith("Assumption (to confirm with owner):") for a in v2["assumptions"])

        # v1 file remains 100% untouched on disk!
        assert hashlib.sha256(v1_docx_path.read_bytes()).hexdigest() == v1_sha_before

        # Step 04 token budget block: remaining daily tokens (120) smaller than est_tokens -> HTTP 429 before LLM call
        upd = client.put(
            "/api/settings/provider",
            json={
                "active_provider": "gemini",
                "models": {"fast": "gemini-3.8-flash", "deep": "gemini-4-argon"},
                "usage_limits": {
                    "daily_request_limit": 100,
                    "daily_token_limit": 1000,
                    "monthly_request_limit": 1000,
                    "monthly_token_limit": 500000,
                    "max_output_tokens": 4096,
                },
            },
        )
        assert upd.status_code == 200
        blocked = client.post(f"/api/review-reports/{v1['id']}/ai-synthesize", json={"complexity": "fast"})
        assert blocked.status_code == 429
        assert len(captured_prompts) == 1


def test_step09_only_cites_reliable_text_and_excludes_failed_blank_cid_reversed_or_low_confidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 09 findings/facts must NEVER cite garbled CID, reversed Arabic, blank/failed, or low-confidence OCR pages."""
    from app.db.models import FileExtraction

    # Mixed PDF: Page 1 has clean reliable spec; Page 2 has literal (cid:101)(cid:102) + reversed Arabic tokens
    mixed_doc = pymupdf.open()
    p1 = mixed_doc.new_page()
    p1.insert_text((50, 80), "Valid Design Note: Column C1 design load = 850.00 kN.", fontsize=12)
    p2 = mixed_doc.new_page()
    p2.insert_text((50, 80), "GARBLED_DO_NOT_CITE (cid:101)(cid:102) يف نم ىلع ىلإ", fontsize=12)
    mixed_pdf = mixed_doc.tobytes()
    mixed_doc.close()

    settings = _test_settings(tmp_path)

    # 1. Run extraction with Tesseract unavailable -> Page 1 = text, Page 2 = failed (native_text_unreliable)
    with monkeypatch.context() as m:
        m.setattr("app.services.extractors.ocr._DEFAULT_WINDOWS_TESSERACT_PATHS", ())
        m.setattr("app.services.extractors.ocr.shutil.which", lambda *_a, **_kw: None)

        app = create_app(settings)
        with TestClient(app) as client:
            proj = client.post("/api/projects", json={"name": "Reliability Gate Project", "code": "REL-09"}).json()
            pid = proj["id"]
            up = client.post(
                f"/api/projects/{pid}/files",
                files=[("files", ("mixed_spec.pdf", mixed_pdf, "application/pdf"))],
            ).json()
            fid = up["items"][0]["file"]["id"]
            ext_res = client.post(f"/api/files/{fid}/extract")
            assert ext_res.status_code == 201
            assert ext_res.json()["status"] == "partial_ocr_unavailable"
            assert ext_res.json()["ocr_status"] == "partial_ocr_unavailable"

            rep = client.post(
                f"/api/projects/{pid}/review-reports",
                json={"language": "en", "classification": "For Review", "use_ai": False},
            ).json()

    serialized = str(rep)
    assert "Column C1 design load = 850.00 kN" in serialized
    assert "GARBLED_DO_NOT_CITE" not in serialized
    assert "(cid:101)" not in serialized
    assert any("page:2" in g for g in rep["gaps_or_unextracted"])
    # Verified facts and findings MUST cite only EXT-* linked to clean Page 1 (never Page 2 garbled text)
    assert any("Column C1 design load = 850.00 kN" in vf["text"] for vf in rep["verified_facts"])
    assert any("Page Reliability" in f["location_or_drawing_ref"] for f in rep["findings"])

    # 2. Inject blank + low-confidence OCR + recovered reliable OCR cases -> only clean text is cited!
    with app.state.session_factory() as db:
        ext_row = db.get(FileExtraction, ext_res.json()["id"])
        assert ext_row is not None
        payload_copy = dict(ext_row.payload_json)
        payload_copy["items"] = [
            {
                "item_index": 1,
                "item_type": "ocr_text",
                "source_file": "mixed_spec.pdf",
                "file_id": fid,
                "version_number": 1,
                "page_or_sheet": "page:1",
                "location": "ocr_full_page",
                "text": "مخطط الأعمدة الموثوق: حمل العمود 1250.00 kN",
                "raw_native_text": "RAW_REVERSED_NEVER_CITE يف نم ىلع",
                "native_text_unreliable": True,
                "ocr_confidence_mean": 92.4,
                "ocr_low_confidence": False,
                "page_status": "ocr_text",
                "extraction_method": "ocr",
            },
            {
                "item_index": 2,
                "item_type": "ocr_text",
                "source_file": "mixed_spec.pdf",
                "file_id": fid,
                "version_number": 1,
                "page_or_sheet": "page:2",
                "location": "ocr_full_page",
                "text": "LOWCONF_NOISE_DO_NOT_CITE",
                "ocr_confidence_mean": 38.0,
                "ocr_low_confidence": True,
                "page_status": "ocr_text",
                "extraction_method": "ocr",
            },
            {
                "item_index": 3,
                "item_type": "ocr_text",
                "source_file": "mixed_spec.pdf",
                "file_id": fid,
                "version_number": 1,
                "page_or_sheet": "page:3",
                "location": "ocr_full_page",
                "text": None,
                "page_status": "ocr_empty_or_blank",
                "extraction_method": "ocr",
            },
        ]
        ext_row.status = "extracted"
        ext_row.ocr_status = "ocr_applied (native text unreliable)"
        ext_row.payload_json = payload_copy
        db.commit()

    with TestClient(app) as client:
        rep2 = client.post(
            f"/api/projects/{pid}/review-reports",
            json={"language": "ar", "classification": "For Review", "use_ai": False},
        ).json()

    # Unverified OCR goes strictly to ocr_text_items; never into verified_facts or findings!
    ocr_texts_joined = " ".join(o["text"] for o in rep2["ocr_text_items"])
    vf_texts_joined = " ".join(v["text"] for v in rep2["verified_facts"])
    findings_joined = " ".join(f["evidence"] + " " + f["recommendation"] for f in rep2["findings"])
    registry_excerpts = " ".join(str(r.get("excerpt") or "") for r in rep2["source_registry"])

    assert "مخطط الأعمدة الموثوق: حمل العمود 1250.00 kN" in ocr_texts_joined
    assert "مخطط الأعمدة الموثوق" not in vf_texts_joined
    assert "مخطط الأعمدة الموثوق" not in findings_joined
    assert "RAW_REVERSED_NEVER_CITE" not in str(rep2)
    assert "LOWCONF_NOISE_DO_NOT_CITE" not in vf_texts_joined
    assert "LOWCONF_NOISE_DO_NOT_CITE" not in findings_joined
    assert "LOWCONF_NOISE_DO_NOT_CITE" not in registry_excerpts
    assert any("page:2" in g and "38.0%" in g for g in rep2["gaps_or_unextracted"])
    assert any("page:3" in g and "ocr_empty_or_blank" in g for g in rep2["gaps_or_unextracted"])


def test_step09b_cad_area_bearing_layers_confirmed_unit_and_no_none_unit(tmp_path: Path) -> None:
    """Only area-bearing layers appear with 'geometric sum, not net building area', confirmed unit matches cleanly, and never 'None'."""
    from app.db.models import FileExtraction

    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 1  # inches header overriding via confirm-unit = m
    msp = doc.modelspace()
    doc.layers.add("A-AREA")
    doc.layers.add("FURNITURE")
    doc.layers.add("DIMENSIONS")
    # 6 x 4 = 24.0 area-bearing rectangle on A-AREA
    msp.add_lwpolyline([(0, 0), (6, 0), (6, 4), (0, 4)], close=True, dxfattribs={"layer": "A-AREA"})
    # Large dummy rectangles on non-area layers that MUST NOT inflate area sums!
    msp.add_lwpolyline([(10, 0), (20, 0), (20, 10), (10, 10)], close=True, dxfattribs={"layer": "FURNITURE"})
    msp.add_lwpolyline([(30, 0), (40, 0), (40, 5), (30, 5)], close=True, dxfattribs={"layer": "DIMENSIONS"})
    buf = io.StringIO()
    doc.write(buf)
    dxf_bytes = buf.getvalue().encode("utf-8")

    # Also build a tiny second DXF whose extraction payload simulates a legacy row with declared_unit=None
    legacy_dxf_bytes = _make_dxf_bytes(insunits=0, width=5.0, height=4.0, layer_name="A-AREA")

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        proj = client.post("/api/projects", json={"name": "Hospital Area Layers", "code": "HAL-09B"}).json()
        pid = proj["id"]
        up = client.post(
            f"/api/projects/{pid}/files",
            files=[
                ("files", ("confirmed_plan.dxf", dxf_bytes, "application/dxf")),
                ("files", ("legacy_no_unit.dxf", legacy_dxf_bytes, "application/dxf")),
            ],
        ).json()
        f_conf_id = up["items"][0]["file"]["id"]
        f_leg_id = up["items"][1]["file"]["id"]

        ext1 = client.post(f"/api/files/{f_conf_id}/extract", json={}).json()
        assert ext1["units_doubtful"] is True
        # Confirm unit as 'm' via confirm-unit endpoint
        conf_res = client.post(f"/api/extractions/{ext1['id']}/confirm-unit", json={"confirmed_unit": "m"})
        assert conf_res.status_code == 200, conf_res.text

        ext2 = client.post(f"/api/files/{f_leg_id}/extract", json={}).json()

    # Mutate ext2 in DB to simulate legacy row where declared_unit/units were None
    with app.state.session_factory() as db:
        row2 = db.get(FileExtraction, ext2["id"])
        assert row2 is not None
        p2 = dict(row2.payload_json)
        p2["cad_units"] = None
        p2["units_doubtful"] = False  # Simulate broken legacy row trying to expose stale area_m2 without valid unit
        inv2 = dict(p2["drawing_inventory"])
        inv2["declared_unit"] = None
        inv2["units"] = None
        inv2["insunits_code"] = 0
        inv2["units_doubtful"] = True
        p2["drawing_inventory"] = inv2
        row2.payload_json = p2
        db.commit()

    with TestClient(app) as client:
        rep = client.post(
            f"/api/projects/{pid}/review-reports",
            json={"language": "en", "classification": "For Review", "use_ai": False},
        ).json()

    # 1. FURNITURE (100.0) & DIMENSIONS (50.0) MUST be excluded; ONLY A-AREA (24.0 m2) appears with required disclaimer!
    calc_joined = " | ".join(c["text"] for c in rep["calculated_items"])
    assert "A-AREA" in calc_joined
    assert "24.0 m²" in calc_joined
    assert "geometric sum, not net building area" in calc_joined
    assert "100.0" not in calc_joined
    assert "50.0" not in calc_joined
    assert "owner-confirmed; raw header $INSUNITS=1 in" in calc_joined

    # 2. Active confirmed unit matches consistently in source_registry (never contradictory m vs unclarified in)
    conf_refs = [r for r in rep["source_registry"] if r["source_name"] == "confirmed_plan.dxf"]
    assert conf_refs and "m (owner-confirmed; raw header $INSUNITS=1 in)" in conf_refs[0]["location"]

    # 3. Legacy DXF with missing/None unit raises HIGH finding, withholds m2, and NEVER prints 'None'
    assert any(
        f["severity"] == "high"
        and f["status"] == "needs_verification"
        and "legacy_no_unit.dxf" in f["location_or_drawing_ref"]
        for f in rep["findings"]
    )
    assert "unit: None" not in str(rep)
    assert "unit_basis=None" not in str(rep)
    assert "unspecified unit" in str(rep) or "unitless" in str(rep)


def test_step09b_dxf_vs_dwg_mismatch_raises_high_reconciliation_and_withholds_conflicting_areas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When paired DXF and DWG of the same drawing differ by >1%, raise HIGH finding and withhold both areas from calculated_items."""
    # Same shared architectural layers A-AREA & A-WALL across renamed files ok.dxf (5000 m2) and Turj-fin.dwg (4000 m2)
    def _build_dxf(*, insunits: int, w: float, h: float) -> bytes:
        d = ezdxf.new("R2018")
        d.header["$INSUNITS"] = insunits
        d.layers.add("A-AREA")
        d.layers.add("A-WALL")
        d.modelspace().add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True, dxfattribs={"layer": "A-AREA"})
        b = io.StringIO()
        d.write(b)
        return b.getvalue().encode("utf-8")

    ok_dxf_bytes = _build_dxf(insunits=6, w=100.0, h=50.0)  # 5000.0 m2
    dwg_scaled_dxf = _build_dxf(insunits=6, w=80.0, h=50.0)  # 4000.0 m2 -> 20% mismatch

    fake_oda = tmp_path / "ODAFileConverter.exe"
    fake_oda.write_bytes(b"stub")

    def fake_oda_run(cmd: list[str], **_kw: Any) -> SimpleNamespace:
        # probe check (--version) or actual conversion (src_dir, out_dir, ...)
        if len(cmd) >= 3 and Path(cmd[1]).is_dir():
            out_dir = Path(cmd[2])
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "Turj-fin.dxf").write_bytes(dwg_scaled_dxf)
        return SimpleNamespace(returncode=0, stdout="27.10.0\n", stderr="")

    monkeypatch.setattr("app.services.extractors.oda._resolve_oda_executable", lambda _p="": str(fake_oda))
    monkeypatch.setattr("app.services.extractors.oda.subprocess.run", fake_oda_run)

    settings = Settings(
        workspaces_dir=tmp_path / "workspaces",
        database_url="",
        oda_file_converter_path=str(fake_oda),
    )
    app = create_app(settings)
    with TestClient(app) as client:
        proj = client.post("/api/projects", json={"name": "Reconcile Hospital", "code": "REC-09B"}).json()
        pid = proj["id"]
        up = client.post(
            f"/api/projects/{pid}/files",
            files=[
                ("files", ("ok.dxf", ok_dxf_bytes, "application/dxf")),
                ("files", ("Turj-fin.dwg", b"AC1032_SYNTHETIC_DWG_HEADER_STUB", "application/acad")),
            ],
        ).json()
        f_dxf_id = up["items"][0]["file"]["id"]
        f_dwg_id = up["items"][1]["file"]["id"]

        assert client.post(f"/api/files/{f_dxf_id}/extract", json={}).status_code == 201
        res_dwg = client.post(f"/api/files/{f_dwg_id}/extract", json={})
        assert res_dwg.status_code == 201, res_dwg.text

        rep = client.post(
            f"/api/projects/{pid}/review-reports",
            json={"language": "en", "classification": "For Review", "use_ai": False},
        ).json()

    # Conflicting 5000.0 m2 and 4000.0 m2 MUST NOT appear in calculated_items; HIGH reconciliation finding raised instead!
    assert rep["calculated_items"] == []
    assert any(
        f["severity"] == "high"
        and f["discipline"] == "CAD Reconciliation"
        and f["status"] == "needs_verification"
        and "ok.dxf" in f["location_or_drawing_ref"]
        and "Turj-fin.dwg" in f["location_or_drawing_ref"]
        and len(f["source_links"]) == 2
        for f in rep["findings"]
    )


def test_step09b_ocr_separated_document_register_no_boilerplate_and_showing_n_of_m_appendix(
    tmp_path: Path,
) -> None:
    """Verify OCR is separated with confidence N%, boilerplate eliminated, Document Register included, and showing N of M + full Appendix/JSON."""
    import json
    from docx import Document as DocxDoc

    # 1. Clean 18-page native PDF -> creates >15 verified facts cleanly (testing Showing 15 of M & Appendix A!)
    doc_18p = pymupdf.open()
    for p_num in range(1, 19):
        page = doc_18p.new_page()
        page.insert_text(
            (50, 80),
            f"Design Spec Section {p_num}: Corridor minimum width = 2.40 m and slab thickness = 250 mm.",
            fontsize=11,
        )
    pdf_18p = doc_18p.tobytes()
    doc_18p.close()

    # 2. Scanned 2-page PDF -> OCR at 78.0% & 58.0% confidences
    img = Image.new("RGB", (400, 120), color=(255, 255, 255))
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    scan_doc = pymupdf.open()
    for _ in range(2):
        pg = scan_doc.new_page(width=400, height=120)
        pg.insert_image(pymupdf.Rect(0, 0, 400, 120), stream=img_buf.getvalue())
    scan_pdf = scan_doc.tobytes()
    scan_doc.close()

    settings = _test_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        proj = client.post("/api/projects", json={"name": "Honest Inventory Spec", "code": "INV-09B"}).json()
        pid = proj["id"]
        slug = proj["workspace_slug"]
        up = client.post(
            f"/api/projects/{pid}/files",
            files=[
                ("files", ("native_18p.pdf", pdf_18p, "application/pdf")),
                ("files", ("scanned_ocr_2p.pdf", scan_pdf, "application/pdf")),
            ],
        ).json()
        f_nat_id = up["items"][0]["file"]["id"]
        f_scan_id = up["items"][1]["file"]["id"]
        client.post(f"/api/files/{f_nat_id}/extract", json={})

    scan_idx = {"n": 0}

    def scan_ocr_runner(_bytes: bytes, _lang: str) -> dict[str, Any]:
        scan_idx["n"] += 1
        if scan_idx["n"] == 1:
            return {"text": "OCR_NOISE_P1_TOKEN @@@ Beam 5.5 m", "confidence_mean": 78.0}
        return {"text": "OCR_NOISE_P2_TOKEN ### blurry", "confidence_mean": 58.0}

    from app.services.extraction import extract_project_file
    with app.state.session_factory() as db:
        extract_project_file(db, settings, f_scan_id, ocr_runner=scan_ocr_runner)

    with TestClient(app) as client:
        rep = client.post(
            f"/api/projects/{pid}/review-reports",
            json={"language": "en", "classification": "Preliminary", "use_ai": False},
        ).json()

    # Deterministic inventory disclaimer present in summary
    assert rep["is_inventory_only"] is True
    assert "NOT an engineering design review" in (rep["summary"] or "")

    # Document Register has both files with (file, type, pages/entities, extraction status, confidence)
    reg_by_name = {r["file_name"]: r for r in rep["document_register"]}
    assert set(reg_by_name.keys()) == {"native_18p.pdf", "scanned_ocr_2p.pdf"}
    assert reg_by_name["native_18p.pdf"]["pages_or_entities"] == "18 pages"
    assert reg_by_name["native_18p.pdf"]["confidence"] == "Native deterministic"
    assert "68.0%" in reg_by_name["scanned_ocr_2p.pdf"]["confidence"]

    # OCR text is NEVER in verified_facts and NEVER dumped into findings; lives strictly in ocr_text_items!
    assert len(rep["ocr_text_items"]) == 2
    assert any("OCR_NOISE_P1_TOKEN" in o["text"] and "confidence 78.0%, not verified" in o["status_label"] for o in rep["ocr_text_items"])
    assert any("OCR_NOISE_P2_TOKEN" in o["text"] and "confidence 58.0%, low confidence — not verified" in o["status_label"] for o in rep["ocr_text_items"])
    vf_all_txt = " ".join(s["text"] for s in rep["appendix_verified_facts"])
    findings_all_txt = " ".join(f["evidence"] + " " + f["recommendation"] for f in rep["findings"])
    assert "OCR_NOISE_P1_TOKEN" not in vf_all_txt
    assert "OCR_NOISE_P2_TOKEN" not in vf_all_txt
    assert "OCR_NOISE_P1_TOKEN" not in findings_all_txt
    assert "OCR_NOISE_P2_TOKEN" not in findings_all_txt

    # Concrete low-confidence finding exists for page 2 (WITHOUT generic boilerplate!)
    assert len(rep["findings"]) == 1
    assert "scanned_ocr_2p.pdf" in rep["findings"][0]["location_or_drawing_ref"]
    assert "Cross-check extracted figures" not in findings_all_txt

    # Showing N of M verified facts + complete Appendix in DOCX/PDF/JSON!
    assert rep["verified_facts_shown"] == 15
    assert rep["verified_facts_total"] == 20  # 1 meta + 18 native pages + 1 scanned meta = 20
    assert len(rep["verified_facts"]) == 15
    assert len(rep["appendix_verified_facts"]) == rep["verified_facts_total"]

    # Check DOCX & PDF both contain Document Register, Inventory notice, Showing 15 of M, and Appendix A
    docx_rel = [d["relative_path"] for d in rep["deliverables"] if d["folder_name"] == "10_Final_Deliverables" and d["format"] == "docx"][0]
    pdf_rel = [d["relative_path"] for d in rep["deliverables"] if d["folder_name"] == "10_Final_Deliverables" and d["format"] == "pdf"][0]
    docx_txt = "\n".join(p.text for p in DocxDoc(str(resolve_project_file_path(settings.workspaces_dir, slug, docx_rel))).paragraphs)
    assert f"Showing 15 of {rep['verified_facts_total']}" in docx_txt
    assert "Appendix A:" in docx_txt
    assert "NOT an engineering review" in docx_txt or "NOT an engineering design review" in docx_txt

    pdf_doc = pymupdf.open(str(resolve_project_file_path(settings.workspaces_dir, slug, pdf_rel)))
    pdf_txt = "\n".join(pg.get_text("text") for pg in pdf_doc).replace("\xa0", " ").replace("\xad", "-")
    pdf_doc.close()
    assert f"Showing 15 of {rep['verified_facts_total']}" in pdf_txt
    assert "0. Document Register" in pdf_txt
    assert "2.3 Extracted Text (OCR" in pdf_txt
    assert "Appendix A:" in pdf_txt

    short_id = rep["id"].replace("-", "")[:8]
    json_path = resolve_project_file_path(settings.workspaces_dir, slug, f"08_Reports/review_{short_id}_v1.json")
    json_data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(json_data["appendix_verified_facts"]) == rep["verified_facts_total"]
    assert json_data["verified_facts_shown"] == 15



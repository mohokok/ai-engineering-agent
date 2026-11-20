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

        # EVERY finding links to at least 1 real extraction or reviewed research source location!
        assert len(rep["findings"]) >= 4
        for finding in rep["findings"]:
            assert len(finding["source_links"]) >= 1
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

        # Strictly separated categories
        assert len(rep["verified_facts"]) >= 2
        assert any("https://www.hse.gov.uk/ventilation-clinic-check" in str(vf["source_links"]) for vf in rep["verified_facts"])
        assert len(rep["calculated_items"]) >= 1
        assert any("24.0 m²" in c["text"] and c["formula_or_method"] for c in rep["calculated_items"])
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

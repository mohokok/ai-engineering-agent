"""Tests for Step 22 company branding (ALHARAM ALDAHABY / الهرم الذهبي): assets, DOCX/PDF/XLSX/DXF exports, QA export, and backup manifest."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
import unicodedata
import zipfile

from docx import Document as DocxDocument
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
import pymupdf

from app.core.branding import (
    BACKEND_LOGO_PATH,
    BRAND_COLORS,
    COMPANY_FULL_AR,
    COMPANY_FULL_EN,
    COMPANY_NAME_AR,
    COMPANY_NAME_EN,
    COMPANY_SUBTITLE_AR,
    COMPANY_SUBTITLE_EN,
    FRONTEND_LOGO_RELATIVE_URL,
    logo_sha256,
)
from app.core.config import Settings
from app.main import create_app
from app.providers.secrets import SecretStore
from app.schemas.boq import BoqChecksSummaryOut
from app.schemas.drawings import DoorSpec, ParametricPlanModel, RoomSpec, WallSpec, WindowSpec
from app.schemas.planning import ScheduleResultOut, WbsItemIn
from app.schemas.qa import IssueOut, QaCheckMetricOut, QaContextIsolationReport
from app.schemas.reports import RevisionBlockOut
from app.schemas.standards import StandardDocumentOut
from app.services.boq_export import generate_boq_xlsx
from app.services.calc_export import (
    CalculationRenderData,
    generate_calculation_docx,
    generate_calculation_pdf,
    generate_calculation_xlsx,
)
from app.services.comparison_export import (
    ComparisonRenderData,
    generate_comparison_docx,
    generate_comparison_pdf,
    generate_comparison_xlsx,
)
from app.services.parametric_cad import (
    build_schedules_from_model,
    compute_room_metrics,
    generate_parametric_dxf,
    generate_true_scale_parametric_pdf,
)
from app.services.planning_export import (
    ScheduleRenderData,
    generate_schedule_pdf,
    generate_schedule_xlsx,
)
from app.services.qa_export import (
    QaReportRenderData,
    generate_qa_report_docx,
    generate_qa_report_pdf,
)
from app.services.report_generator import (
    ReviewReportRenderData,
    generate_review_report_docx,
    generate_review_report_pdf,
)
from app.services.spec_export import (
    SpecificationRenderData,
    generate_specification_docx,
    generate_specification_pdf,
)
from app.services.specialist_export import (
    SpecialistRenderData,
    generate_specialist_docx,
    generate_specialist_pdf,
    generate_specialist_xlsx,
)
from app.services.standards_export import (
    StandardsRegisterRenderData,
    generate_standards_register_docx,
    generate_standards_register_pdf,
    generate_standards_register_xlsx,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_LOGO_PATH = REPO_ROOT / "frontend" / "public" / "branding" / "logo.jpg"


class _TestSecretStore(SecretStore):
    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

    @property
    def backend_name(self) -> str:
        return "InMemoryTestKeyring"

    def set_api_key(self, provider_name: str, api_key: str) -> None:
        self._keys[provider_name] = api_key

    def get_api_key(self, provider_name: str) -> str | None:
        return self._keys.get(provider_name)

    def delete_api_key(self, provider_name: str) -> None:
        self._keys.pop(provider_name, None)


def _assert_docx_branded(docx_path: Path, expected_classification: str) -> None:
    assert docx_path.is_file()
    expected_logo_hash = logo_sha256()
    with zipfile.ZipFile(docx_path, "r") as zf:
        media_entries = [name for name in zf.namelist() if name.startswith("word/media/")]
        assert media_entries, f"{docx_path.name} missing embedded header logo media"
        hashes = {sha256(zf.read(m)).hexdigest() for m in media_entries}
        assert expected_logo_hash in hashes, f"{docx_path.name} embedded image differs from logo.jpg"

    doc = DocxDocument(str(docx_path))
    hdr_txt = "\n".join(
        p.text
        for sec in doc.sections
        for tbl in sec.header.tables
        for row in tbl.rows
        for cell in row.cells
        for p in cell.paragraphs
    )
    ftr_txt = "\n".join(p.text for sec in doc.sections for p in sec.footer.paragraphs)
    assert COMPANY_NAME_EN in hdr_txt, f"Missing English company name in {docx_path.name} header"
    assert COMPANY_NAME_AR in hdr_txt, f"Missing Arabic company name in {docx_path.name} header"
    assert expected_classification in ftr_txt, f"Missing classification footer in {docx_path.name}"


def _assert_pdf_branded(pdf_path: Path, expected_classification: str) -> None:
    assert pdf_path.is_file()
    with pymupdf.open(str(pdf_path)) as pdf_doc:
        assert len(pdf_doc) >= 1
        for page_idx, page in enumerate(pdf_doc, start=1):
            assert len(page.get_images()) >= 1, (
                f"{pdf_path.name} page {page_idx} missing embedded logo image"
            )
            norm = unicodedata.normalize("NFKC", page.get_text("text"))
            assert COMPANY_NAME_EN in norm, f"{pdf_path.name} page {page_idx} missing {COMPANY_NAME_EN}"
            assert "الهرم" in norm and "الذهبي" in norm, (
                f"{pdf_path.name} page {page_idx} missing Arabic company name"
            )
            assert expected_classification in norm, (
                f"{pdf_path.name} page {page_idx} missing classification {expected_classification}"
            )


def _assert_xlsx_branded(xlsx_path: Path, expected_classification: str) -> None:
    assert xlsx_path.is_file()
    wb = load_workbook(str(xlsx_path))
    assert len(wb.worksheets) >= 1
    for ws in wb.worksheets:
        assert len(getattr(ws, "_images", [])) >= 1, f"{xlsx_path.name}:{ws.title} missing logo image"
        hdr = str(ws.oddHeader.center.text or "")
        ftr = str(ws.oddFooter.center.text or "")
        assert COMPANY_NAME_EN in hdr and COMPANY_NAME_AR in hdr
        assert expected_classification in ftr
        sheet_vals = [
            str(ws.cell(row=r, column=c).value or "")
            for r in range(1, ws.max_row + 1)
            for c in range(1, ws.max_column + 1)
            if ws.cell(row=r, column=c).value is not None
        ]
        joined = "\n".join(sheet_vals)
        assert COMPANY_NAME_EN in joined and COMPANY_NAME_AR in joined
        assert expected_classification in joined


def test_branding_assets_and_source_of_truth_byte_identical() -> None:
    """Verify byte-identical logo copies (SHA-256) and synchronized Python/TS branding definitions."""
    assert FRONTEND_LOGO_PATH.is_file(), "Owner-supplied frontend logo.jpg is missing"
    assert BACKEND_LOGO_PATH.is_file(), "Backend branding logo.jpg copy is missing"

    fe_bytes = FRONTEND_LOGO_PATH.read_bytes()
    be_bytes = BACKEND_LOGO_PATH.read_bytes()
    fe_hash = sha256(fe_bytes).hexdigest()
    be_hash = sha256(be_bytes).hexdigest()
    assert fe_hash == be_hash == logo_sha256()
    assert len(fe_bytes) == 53527

    with Image.open(BACKEND_LOGO_PATH) as img:
        assert img.size == (1193, 210)

    assert COMPANY_NAME_EN == "ALHARAM ALDAHABY"
    assert COMPANY_SUBTITLE_EN == "Engineering Consultancy"
    assert COMPANY_NAME_AR == "الهرم الذهبي"
    assert COMPANY_SUBTITLE_AR == "للاستشارات الهندسية"
    assert BRAND_COLORS["brown"] == "#5A3A1A"
    assert BRAND_COLORS["gold"] == "#E0AE1B"
    assert BRAND_COLORS["bg_cream"] == "#FAF7F0"

    ts_src = (REPO_ROOT / "frontend" / "src" / "branding.ts").read_text(encoding="utf-8")
    assert COMPANY_NAME_EN in ts_src
    assert COMPANY_SUBTITLE_EN in ts_src
    assert COMPANY_NAME_AR in ts_src
    assert COMPANY_SUBTITLE_AR in ts_src
    assert FRONTEND_LOGO_RELATIVE_URL in ts_src

    index_html = (REPO_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'href="/branding/logo.jpg"' in index_html
    assert COMPANY_FULL_EN in index_html and COMPANY_FULL_AR in index_html

    index_css = (REPO_ROOT / "frontend" / "src" / "index.css").read_text(encoding="utf-8")
    assert "--brand-brown: #5a3a1a;" in index_css
    assert "--brand-gold: #e0ae1b;" in index_css
    assert "--brand-bg: #faf7f0;" in index_css
    assert "fonts.googleapis.com" not in index_css
    assert "fonts.gstatic.com" not in index_css


def test_all_docx_pdf_xlsx_dxf_outputs_carry_logo_bilingual_header_and_classification(tmp_path: Path) -> None:
    """Verify every document exporter (Steps 9-19 + QA) embeds corporate logo, bilingual name, and classification."""
    classification = "PRELIMINARY"
    issued = "2026-11-22 12:00 UTC"

    # 1. Step 9 Review Report (AR + EN)
    for lang in ("ar", "en"):
        rep_data = ReviewReportRenderData(
            project_code="SYN-22",
            project_name="Synthetic Brand Tower",
            client_name="Synthetic Client",
            location="Synthetic Site",
            title=f"Synthetic Review ({lang})",
            discipline="architecture",
            language=lang,
            classification=classification,
            summary="Synthetic summary block.",
            revision_block=RevisionBlockOut(
                version=1,
                revision="Rev 01",
                classification=classification,
                prepared_by="Deterministic Engine",
                review_notice="Advisory only",
                issued_at_iso=issued,
                change_note="Initial synthetic test",
                source_files_count=0,
                reviewed_research_count=0,
            ),
            findings=[],
            verified_facts=[],
            calculated_items=[],
            assumptions=[],
            recommendations=[],
            gaps_or_unextracted=[],
            source_registry=[],
        )
        rep_docx = tmp_path / f"review_{lang}.docx"
        rep_pdf = tmp_path / f"review_{lang}.pdf"
        generate_review_report_docx(rep_docx, rep_data)
        generate_review_report_pdf(rep_pdf, rep_data)
        _assert_docx_branded(rep_docx, classification)
        _assert_pdf_branded(rep_pdf, classification)

    # 2. Step 10 BOQ XLSX
    boq_xlsx = tmp_path / "boq_ar.xlsx"
    boq_checks = BoqChecksSummaryOut(
        total_items=1,
        verified_items_count=0,
        needs_check_items_count=0,
        manual_items_count=1,
        priced_items_count=1,
        unpriced_items_count=0,
        verified_priced_subtotal=0.0,
        needs_check_priced_subtotal=0.0,
        grand_total=500.0,
        issues_count=0,
        high_issues_count=0,
        issues=[],
        flagged_item_ids=[],
        flagged_items=[],
    )
    generate_boq_xlsx(
        boq_xlsx,
        title="Synthetic BOQ",
        project_code="SYN-22",
        project_name="Synthetic Brand Tower",
        classification=classification,
        currency="LYD",
        revision="Rev 01",
        export_version=1,
        language="ar",
        items=[{"item_no": "1.1", "description": "Synthetic Slab", "unit": "m2", "quantity": 10.0, "unit_rate": 50.0, "total": 500.0, "verification_status": "Manual"}],
        checks=boq_checks,
    )
    _assert_xlsx_branded(boq_xlsx, classification)

    # 3. Step 13 Calculations DOCX / PDF / XLSX
    calc_data = CalculationRenderData(
        project_code="SYN-22",
        project_name="Synthetic Brand Tower",
        title="Synthetic Calc",
        discipline="plumbing",
        calculation_type="plumbing_pipe_sizing",
        language="en",
        classification=classification,
        revision="Rev 01",
        version=1,
        export_version=1,
        issued_at_iso=issued,
        inputs={
            "flow_rate_lps": 1.2,
            "pipe_length_m": 25.0,
            "minor_loss_allowance_pct": 10.0,
            "max_velocity_mps": 2.0,
            "max_head_loss_m_per_100m": 4.0,
        },
        units={
            "flow_rate_lps": "L/s",
            "pipe_length_m": "m",
            "minor_loss_allowance_pct": "%",
            "max_velocity_mps": "m/s",
            "max_head_loss_m_per_100m": "m/100m",
            "internal_diameter_mm": "mm",
            "head_loss_m_per_100m": "m/100m",
        },
        equations="Q = A * V",
        method="Deterministic synthetic arithmetic",
        assumptions=["Preliminary synthetic assumption"],
        results={"internal_diameter_mm": 40.0, "head_loss_m_per_100m": 2.5},
        acceptance_criteria=["V <= 2.0 m/s"],
        acceptance_passed=True,
        references=[],
        data_provenance="owner_supplied",
    )
    calc_docx, calc_pdf, calc_xlsx = tmp_path / "calc.docx", tmp_path / "calc.pdf", tmp_path / "calc.xlsx"
    generate_calculation_docx(calc_docx, calc_data)
    generate_calculation_pdf(calc_pdf, calc_data)
    generate_calculation_xlsx(calc_xlsx, calc_data)
    _assert_docx_branded(calc_docx, classification)
    _assert_pdf_branded(calc_pdf, classification)
    _assert_xlsx_branded(calc_xlsx, classification)

    # 4. Step 14 Specifications DOCX / PDF
    spec_data = SpecificationRenderData(
        project_code="SYN-22",
        project_name="Synthetic Brand Tower",
        title="Synthetic Technical Spec",
        discipline="civil",
        language="ar",
        classification=classification,
        revision="Rev 01",
        version=1,
        export_version=1,
        issued_at_iso=issued,
        use_ai=False,
        ai_draft_status="deterministic_only",
        owner_approved_by=None,
        owner_approved_at_iso=None,
        summary="Synthetic spec summary",
    )
    spec_docx, spec_pdf = tmp_path / "spec.docx", tmp_path / "spec.pdf"
    generate_specification_docx(spec_docx, spec_data)
    generate_specification_pdf(spec_pdf, spec_data)
    _assert_docx_branded(spec_docx, classification)
    _assert_pdf_branded(spec_pdf, classification)

    # 5. Step 15 Comparison DOCX / PDF / XLSX
    cmp_data = ComparisonRenderData(
        project_code="SYN-22",
        project_name="Synthetic Brand Tower",
        title="Synthetic Technical Comparison",
        comparison_scope="HVAC System",
        discipline="hvac",
        language="en",
        classification=classification,
        revision="Rev 01",
        version=1,
        export_version=1,
        issued_at_iso=issued,
        use_ai=False,
        ai_draft_status="deterministic_only",
        owner_decision_status="pending_owner_decision",
        owner_selected_option_id=None,
        owner_decision_note=None,
        owner_decided_by=None,
        owner_decided_at_iso=None,
        summary="Synthetic comparison",
    )
    cmp_docx, cmp_pdf, cmp_xlsx = tmp_path / "cmp.docx", tmp_path / "cmp.pdf", tmp_path / "cmp.xlsx"
    generate_comparison_docx(cmp_docx, cmp_data)
    generate_comparison_pdf(cmp_pdf, cmp_data)
    generate_comparison_xlsx(cmp_xlsx, cmp_data)
    _assert_docx_branded(cmp_docx, classification)
    _assert_pdf_branded(cmp_pdf, classification)
    _assert_xlsx_branded(cmp_xlsx, classification)

    # 6. Step 16 Planning PDF / XLSX
    plan_data = ScheduleRenderData(
        project_code="SYN-22",
        project_name="Synthetic Brand Tower",
        title="Synthetic Schedule",
        discipline="planning",
        language="ar",
        classification=classification,
        revision="Rev 01",
        version=1,
        export_version=1,
        is_baseline=False,
        issued_at_iso=issued,
        use_ai=False,
        ai_draft_status="deterministic_only",
        owner_approved_by=None,
        owner_approved_at_iso=None,
        summary="Synthetic CPM summary",
        wbs_items=[WbsItemIn(wbs_code="1.0", title="Mobilization", parent_code=None, discipline="general")],
        result=ScheduleResultOut(
            project_start_date="2026-12-01",
            effective_start_date="2026-12-01",
            calendar_preset="libya_sun_thu",
            calendar_summary="Sun-Thu",
            critical_path_complete=True,
        ),
    )
    plan_pdf, plan_xlsx = tmp_path / "plan.pdf", tmp_path / "plan.xlsx"
    generate_schedule_pdf(plan_pdf, plan_data)
    generate_schedule_xlsx(plan_xlsx, plan_data)
    _assert_pdf_branded(plan_pdf, classification)
    _assert_xlsx_branded(plan_xlsx, classification)

    # 7. Step 17 Standards Register DOCX / PDF / XLSX
    now_utc = datetime.now(timezone.utc)
    std_doc = StandardDocumentOut(
        id="std-1",
        project_id=None,
        standard_number="SYN-100",
        title="Synthetic Standard Title",
        issuing_body="SYN",
        edition_year="2024",
        status="active",
        superseded_by_id=None,
        superseded_by_number=None,
        superseded_by_title=None,
        replacement_chain_summary=None,
        supersession_note=None,
        jurisdiction="Synthetic",
        adopted_locally=True,
        owner_notes="Synthetic owner note",
        owner_excerpts=[],
        metadata_status="owner_confirmed",
        metadata_label="Owner-confirmed",
        suggested_metadata=None,
        use_ai=False,
        ai_suggestion_status="deterministic_only",
        tokens_used=0,
        token_usage={},
        original_filename="syn.pdf",
        file_relative_path="11_References/syn.pdf",
        file_sha256="a" * 64,
        file_size_bytes=1234,
        mime_type="application/pdf",
        version=1,
        history=[],
        where_cited=[],
        citation_warnings=[],
        created_at=now_utc,
        updated_at=now_utc,
    )
    std_data = StandardsRegisterRenderData(
        scope_label="SYN-22",
        language="en",
        classification=classification,
        issued_at_iso=issued,
        standards=[std_doc],
    )
    std_docx, std_pdf, std_xlsx = tmp_path / "std.docx", tmp_path / "std.pdf", tmp_path / "std.xlsx"
    generate_standards_register_docx(std_docx, std_data)
    generate_standards_register_pdf(std_pdf, std_data)
    generate_standards_register_xlsx(std_xlsx, std_data)
    _assert_docx_branded(std_docx, classification)
    _assert_pdf_branded(std_pdf, classification)
    _assert_xlsx_branded(std_xlsx, classification)

    # 8. Steps 18 & 19 Specialist / Structural DOCX / PDF / XLSX
    spec18 = SpecialistRenderData(
        project_code="SYN-22",
        project_name="Synthetic Brand Tower",
        title="Synthetic Specialist Assessment",
        domain="hvac",
        workflow_mode="check",
        language="ar",
        classification=classification,
        revision="Rev 01",
        version=1,
        status="completed",
        checks_passed=True,
        standards_status="no verified standard on file - verify against the locally adopted code",
        software_recommendation="Use validated software",
        ai_draft_status="deterministic_only",
        owner_approved_by=None,
        issued_at_iso=issued,
    )
    s18_docx, s18_pdf, s18_xlsx = tmp_path / "s18.docx", tmp_path / "s18.pdf", tmp_path / "s18.xlsx"
    generate_specialist_docx(s18_docx, spec18)
    generate_specialist_pdf(s18_pdf, spec18)
    generate_specialist_xlsx(s18_xlsx, spec18)
    _assert_docx_branded(s18_docx, classification)
    _assert_pdf_branded(s18_pdf, classification)
    _assert_xlsx_branded(s18_xlsx, classification)

    # 9. Step 11 Parametric CAD DXF & 2-page PDF
    model = ParametricPlanModel(
        rooms=[
            RoomSpec(
                room_id="R1",
                name_ar="قاعة synthetic",
                name_en="Synthetic Hall",
                x_mm=0.0,
                y_mm=0.0,
                width_mm=4000.0,
                height_mm=3000.0,
            )
        ],
        walls=[
            WallSpec(wall_id="W1", start_mm=(0.0, 0.0), end_mm=(4000.0, 0.0)),
            WallSpec(wall_id="W2", start_mm=(4000.0, 0.0), end_mm=(4000.0, 3000.0)),
        ],
        doors=[DoorSpec(door_id="D1", position_mm=(1500.0, 0.0), width_mm=900.0)],
        windows=[WindowSpec(window_id="WIN1", position_mm=(0.0, 1500.0), width_mm=1200.0)],
    )
    rooms_m = compute_room_metrics(model.rooms)
    door_sched, win_sched = build_schedules_from_model(model)
    dxf_path, cad_pdf = tmp_path / "plan.dxf", tmp_path / "plan_cad.pdf"
    generate_parametric_dxf(
        dxf_path,
        model=model,
        rooms=rooms_m,
        door_schedule=door_sched,
        window_schedule=win_sched,
        drawing_no="A-101",
        title="Synthetic Plan",
        scale_denominator=100,
        paper_size="A3",
        revision="Rev 01",
        classification=classification,
        notes="Synthetic note",
    )
    dxf_txt = dxf_path.read_text(encoding="utf-8", errors="ignore")
    assert COMPANY_FULL_EN in dxf_txt
    assert COMPANY_FULL_AR in dxf_txt

    generate_true_scale_parametric_pdf(
        cad_pdf,
        model=model,
        rooms=rooms_m,
        door_schedule=door_sched,
        window_schedule=win_sched,
        project_code="SYN-22",
        project_name="Synthetic Brand Tower",
        drawing_no="A-101",
        title="Synthetic Plan",
        scale_denominator=100,
        paper_size="A3",
        revision="Rev 01",
        classification=classification,
        notes="Synthetic note",
    )
    _assert_pdf_branded(cad_pdf, classification)

    # 10. QA Report DOCX / PDF directly
    qa_render = QaReportRenderData(
        review_id="rev-synthetic-22",
        project_code="SYN-22",
        project_name="Synthetic Brand Tower",
        classification=classification,
        review_status="issues_found",
        open_issues_count=1,
        issues_opened_count=1,
        tokens_used=0,
        language="ar",
        version=1,
        issued_at_iso=issued,
        context_summary=QaContextIsolationReport(),
        checks=[QaCheckMetricOut(category="arithmetic", checked_count=1, failed_count=0, passed=True, details="ok")],
        issues=[
            IssueOut(
                id="iss-1",
                project_id="prj-1",
                task_id=None,
                deliverable_id=None,
                qa_review_id="rev-1",
                issue_number="QA-001",
                title="Synthetic Check",
                description="Synthetic test issue",
                discipline="general",
                severity="low",
                check_category="general",
                reference="SYN-REF",
                corrective_action="Fix synthetically",
                recommended_action="Fix synthetically",
                status="open",
                closure_note=None,
                closed_at=None,
                created_at=now_utc,
                updated_at=now_utc,
            )
        ],
    )
    qa_docx, qa_pdf = tmp_path / "qa.docx", tmp_path / "qa.pdf"
    generate_qa_report_docx(qa_docx, qa_render)
    generate_qa_report_pdf(qa_pdf, qa_render)
    _assert_docx_branded(qa_docx, classification)
    _assert_pdf_branded(qa_pdf, classification)


def test_qa_review_export_endpoint_and_backup_branding_metadata(tmp_path: Path) -> None:
    """Verify POST /api/qa-reviews/{id}/export produces branded DOCX+PDF and backup manifest includes corporate branding."""
    settings = Settings(workspaces_dir=tmp_path / "workspaces", database_url="")
    app = create_app(settings=settings, secret_store=_TestSecretStore())

    with TestClient(app) as client:
        prj_res = client.post(
            "/api/projects",
            json={"name": "Synthetic Step 22 Project", "code": "SYN-BR22", "discipline": "civil"},
        )
        assert prj_res.status_code == 201
        project = prj_res.json()
        pid = project["id"]
        slug = project["workspace_slug"]

        iss_res = client.post(
            f"/api/projects/{pid}/issues",
            json={
                "title": "Synthetic Missing Dimension",
                "description": "Verify synthetic setback note on drawing",
                "discipline": "architecture",
                "severity": "medium",
                "reference": "SYN-A-101",
                "corrective_action": "Add synthetic dimension",
            },
        )
        assert iss_res.status_code == 201

        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={})
        assert qa_res.status_code == 201
        rev_id = qa_res.json()["id"]

        exp_res = client.post(f"/api/qa-reviews/{rev_id}/export", json={"language": "en"})
        assert exp_res.status_code == 201, exp_res.text
        exp_body: dict[str, Any] = exp_res.json()
        assert exp_body["tokens_used"] == 0
        assert exp_body["docx_relative_path"].startswith("08_Reports/")
        assert exp_body["pdf_relative_path"].startswith("08_Reports/")

        docx_disk = settings.workspaces_dir / slug / exp_body["docx_relative_path"]
        pdf_disk = settings.workspaces_dir / slug / exp_body["pdf_relative_path"]
        assert sha256(docx_disk.read_bytes()).hexdigest() == exp_body["docx_sha256"]
        assert sha256(pdf_disk.read_bytes()).hexdigest() == exp_body["pdf_sha256"]
        _assert_docx_branded(docx_disk, exp_body["classification"].upper())
        _assert_pdf_branded(pdf_disk, exp_body["classification"].upper())

        dl_pdf = client.get(f"/api/deliverables/{exp_body['pdf_deliverable_id']}/download")
        assert dl_pdf.status_code == 200
        assert dl_pdf.content == pdf_disk.read_bytes()

        # Backup manifest branding check
        bak_res = client.post("/api/system/backup", json={"label": "branding_check"})
        assert bak_res.status_code == 201
        bak_name = bak_res.json()["backup"]["filename"]
        bak_path = settings.workspaces_dir / "_backups" / bak_name
        with zipfile.ZipFile(bak_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        branding_meta = manifest["branding"]
        assert branding_meta["company_full_en"] == COMPANY_FULL_EN
        assert branding_meta["company_full_ar"] == COMPANY_FULL_AR
        assert branding_meta["logo_sha256"] == logo_sha256()
        assert branding_meta["classification"] == "PRELIMINARY"

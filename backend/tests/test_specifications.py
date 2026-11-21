"""Tests for Step 14 BOQ/drawing-linked technical specifications generator, sourced standards guard, optional AI draft approval, Arabic RTL/English LTR DOCX+PDF export, and QA checks."""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from fastapi.testclient import TestClient
import pymupdf

from app.core.config import Settings
from app.db.models import BoqSheet, Deliverable, ResearchSource, Specification, Task
from app.main import create_app
from app.providers.secrets import SecretStore
from app.schemas.specifications import (
    AI_UNVERIFIED_DRAFT_LABEL_EN,
    NO_VERIFIED_STANDARD_LABEL,
    SPEC_SECTION_PARTS,
    VERIFY_CODE_LABEL,
)
from app.services.calc_export import sha256_file
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


def _seed_clinic_boq_and_drawing(
    client: TestClient,
    app: Any,
    *,
    project_id: str,
    task_id: str | None = None,
) -> tuple[str, str]:
    preset_model = client.get("/api/parametric-drawings/clinic-preset").json()
    dwg_res = client.post(
        f"/api/projects/{project_id}/parametric-drawings",
        json={
            "task_id": task_id,
            "drawing_no": "A-101",
            "title": "مخطط العيادة النموذجي",
            "scale_denominator": 100,
            "paper_size": "A3",
            "classification": "For Review",
            "plan_model": preset_model,
        },
    )
    assert dwg_res.status_code == 201, dwg_res.text
    dwg_data = dwg_res.json()
    door_cnt = sum(r["count"] for r in dwg_data["door_schedule"])
    win_cnt = sum(r["count"] for r in dwg_data["window_schedule"])
    room_area = float(dwg_data["total_area_m2"])

    boq_res = client.post(
        f"/api/projects/{project_id}/boq-sheets",
        json={
            "task_id": task_id,
            "title": "Clinic Synthetic BOQ Schedule",
            "currency": "LYD",
            "classification": "For Review",
            "include_dxf_ifc": False,
            "include_boq_imports": False,
        },
    )
    assert boq_res.status_code == 201, boq_res.text
    boq_id = boq_res.json()["id"]
    seed_items = [
        {
            "item_no": "A-01",
            "description": "Flush HPL timber door set 1000x2100mm",
            "unit": "nos",
            "quantity": float(door_cnt),
            "unit_rate": 450.0,
            "rate_source_kind": "owner_input",
            "rate_source_ref": "Owner clinic quote Rev 01",
            "drawing_reference": "A-101",
            "discipline": "architecture",
            "verification_status": "Manual",
        },
        {
            "item_no": "W-01",
            "description": "Double-glazed thermally broken aluminum window",
            "unit": "nos",
            "quantity": float(win_cnt),
            "unit_rate": 620.0,
            "rate_source_kind": "owner_input",
            "rate_source_ref": "Owner clinic quote Rev 01",
            "drawing_reference": "A-101",
            "discipline": "architecture",
            "verification_status": "Manual",
        },
        {
            "item_no": "F-01",
            "description": "Total floor finish non-slip porcelain tile",
            "unit": "m2",
            "quantity": room_area,
            "unit_rate": 95.0,
            "rate_source_kind": "owner_input",
            "rate_source_ref": "Owner clinic quote Rev 01",
            "drawing_reference": "A-101",
            "discipline": "architecture",
            "verification_status": "Manual",
        },
        {
            "item_no": "E-01",
            "description": "Electrical main distribution panel MDB-CLINIC-01 with MCCB feeders",
            "unit": "nos",
            "quantity": 1.0,
            "unit_rate": 8500.0,
            "rate_source_kind": "owner_input",
            "rate_source_ref": "Owner electrical quote Rev 01",
            "discipline": "electrical",
            "verification_status": "Manual",
        },
        {
            "item_no": "P-01",
            "description": "Plumbing PPR PN20 cold water riser pipe DN63",
            "unit": "m",
            "quantity": 35.0,
            "unit_rate": 42.0,
            "rate_source_kind": "owner_input",
            "rate_source_ref": "Owner plumbing quote Rev 01",
            "discipline": "plumbing",
            "verification_status": "Manual",
        },
    ]
    for item_payload in seed_items:
        add_res = client.post(f"/api/boq-sheets/{boq_id}/items", json=item_payload)
        assert add_res.status_code == 201, add_res.text
    return boq_id, dwg_data["id"]


def test_step14_deterministic_spec_generation_traceability_standards_guard_and_exports(tmp_path: Path) -> None:
    """Verify deterministic specs generation from actual BOQs+drawings, reviewed-only standards fallback, Arabic RTL & English LTR DOCX/PDF SHA-256 exports, and QA pass."""
    settings = _test_settings(tmp_path)
    app = create_app(settings, secret_store=_InMemorySecretStore())

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "مشروع مواصفات العيادة", "code": "SPEC-14", "classification": "For Review"},
        ).json()
        pid = project["id"]
        ws_slug = project["workspace_slug"]

        # 1. Empty project without BOQ or Drawings MUST fail HTTP 422 cleanly
        empty_res = client.post(f"/api/projects/{pid}/specifications", json={"language": "ar"})
        assert empty_res.status_code == 422

        # 2. Seed Task, ParametricDrawing A-101, BOQ Sheet, one reviewed ResearchSource (electrical), and one unreviewed source
        with app.state.session_factory() as db:
            task = Task(
                project_id=pid,
                title="Prepare Clinic Technical Specifications",
                prompt="Generate specifications from clinic BOQ and A-101 drawing",
                task_type="assignment",
                status="completed",
                verification_status="unverified",
                classification="For Review",
                structured_output_json={"expected_deliverables": ["Technical Specifications"]},
            )
            rev_elec = ResearchSource(
                project_id=pid,
                source_name="Reviewed Electrical Installation Reference",
                url="https://standards.example.org/electrical-guide",
                publication_date="2025-04-01",
                accessed_at=datetime.now(timezone.utc),
                relevant_info="Panel distribution wiring and protective coordination baseline",
                reliability_assessment="reputable",
                source_type="web",
                source_priority_tier="standards_bodies",
                priority_rank=2,
                access_status="accessible",
                reviewed=True,
                http_status=200,
                untrusted_neutralized=True,
            )
            unrev_plumb = ResearchSource(
                project_id=pid,
                source_name="Unreviewed Blocked Plumbing Site",
                url="https://blocked.example.invalid/plumbing",
                accessed_at=datetime.now(timezone.utc),
                reliability_assessment="unreviewed",
                source_type="web",
                source_priority_tier="unverified",
                priority_rank=99,
                access_status="inaccessible",
                reviewed=False,
                http_status=403,
                untrusted_neutralized=True,
            )
            db.add_all([task, rev_elec, unrev_plumb])
            db.commit()
            tid = task.id
            rev_elec_id = rev_elec.id
            unrev_plumb_id = unrev_plumb.id

        boq_id, dwg_id = _seed_clinic_boq_and_drawing(client, app, project_id=pid, task_id=tid)

        # Export BOQ cleanly too so QA checks full cross-deliverable consistency
        assert client.post(f"/api/boq-sheets/{boq_id}/export", json={"language": "en"}).status_code == 201

        presets_res = client.get("/api/specifications/presets")
        assert presets_res.status_code == 200
        assert len(presets_res.json()["presets"]) == 2

        # 3. Explicitly requesting an unreviewed ResearchSource MUST be rejected HTTP 422
        bad_src_res = client.post(
            f"/api/projects/{pid}/specifications",
            json={"research_source_ids": [unrev_plumb_id]},
        )
        assert bad_src_res.status_code == 422

        # 4. Generate Arabic RTL deterministic specification (default use_ai=False -> 0 AI tokens)
        gen_ar = client.post(
            f"/api/projects/{pid}/specifications",
            json={
                "task_id": tid,
                "title": "مواصفات مشروع العيادة النموذجي",
                "language": "ar",
                "classification": "For Review",
            },
        )
        assert gen_ar.status_code == 201, gen_ar.text
        spec_ar = gen_ar.json()
        sid = spec_ar["id"]
        assert spec_ar["tokens_used"] == 0
        assert spec_ar["use_ai"] is False
        assert spec_ar["ai_draft_status"] == "not_used"
        assert spec_ar["version"] == 1
        assert spec_ar["export_version"] == 1
        assert boq_id in spec_ar["source_boq_sheet_ids"]
        assert dwg_id in spec_ar["source_drawing_ids"]
        assert rev_elec_id in spec_ar["source_research_ids"]
        assert len(spec_ar["sections"]) >= 5

        # Every section must cover all 8 mandatory parts and trace to BOQ/drawing/source IDs
        elec_sections = [s for s in spec_ar["sections"] if s["discipline"] == "electrical"]
        plumb_sections = [s for s in spec_ar["sections"] if s["discipline"] == "plumbing"]
        assert len(elec_sections) == 1
        assert len(plumb_sections) == 1

        # Electrical cites ONLY reviewed source + verify-code label
        assert elec_sections[0]["standards"][0]["status"] == "verified_source_log"
        assert elec_sections[0]["standards"][0]["research_source_id"] == rev_elec_id
        assert VERIFY_CODE_LABEL in elec_sections[0]["standards"][0]["citation_text"]

        # Plumbing lacks a reviewed source (blocked 403 ignored!) -> must emit explicit no-verified-standard fallback
        assert plumb_sections[0]["standards"][0]["status"] == "no_verified_standard_on_file"
        assert NO_VERIFIED_STANDARD_LABEL in plumb_sections[0]["standards"][0]["citation_text"]

        for sec in spec_ar["sections"]:
            assert sec["mapped_boq_item_ids"] or sec["mapped_drawing_ids"]
            parts_present = {c["part"] for c in sec["clauses"]}
            assert set(SPEC_SECTION_PARTS).issubset(parts_present)
            for cl in sec["clauses"]:
                assert len(cl["trace_refs"]) >= 1
                assert cl["draft_origin"] == "deterministic_template"

        # 5. Check DOCX RTL bidi, PDF RTL & SHA-256 deliverables saved in 07_Technical_Specifications
        assert len(spec_ar["deliverables"]) == 2
        by_fmt = {d["format"]: d for d in spec_ar["deliverables"]}
        assert by_fmt["docx"]["folder_name"] == "07_Technical_Specifications"
        assert by_fmt["pdf"]["folder_name"] == "07_Technical_Specifications"
        assert by_fmt["docx"]["specification_id"] == sid
        assert client.get(by_fmt["docx"]["download_url"]).status_code == 200
        assert client.get(by_fmt["pdf"]["download_url"]).status_code == 200

        docx_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, by_fmt["docx"]["relative_path"])
        pdf_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, by_fmt["pdf"]["relative_path"])
        assert sha256_file(docx_path) == by_fmt["docx"]["sha256"]
        assert sha256_file(pdf_path) == by_fmt["pdf"]["sha256"]

        doc = DocxDocument(str(docx_path))
        assert doc.sections[0]._sectPr.find(qn("w:bidi")) is not None
        assert any(tbl._tbl.tblPr.find(qn("w:bidiVisual")) is not None for tbl in doc.tables)
        docx_text = "\n".join(p.text for p in doc.paragraphs)
        assert "مواصفات مشروع العيادة النموذجي" in docx_text
        assert NO_VERIFIED_STANDARD_LABEL in docx_text

        with pymupdf.open(str(pdf_path)) as pdf_doc:
            pdf_txt = "\n".join(pg.get_text("text") for pg in pdf_doc)
        pdf_norm = " ".join(pdf_txt.replace("\xa0", " ").replace("\xad", "-").split())
        assert NO_VERIFIED_STANDARD_LABEL in pdf_norm
        assert "SPEC-01" in pdf_norm

        # 6. Export English LTR version -> new versioned files preserved cleanly without overwriting AR v1
        exp_en = client.post(f"/api/specifications/{sid}/export", json={"language": "en"})
        assert exp_en.status_code == 201, exp_en.text
        exp_data = exp_en.json()
        assert exp_data["specification"]["export_version"] == 2
        assert len(exp_data["specification"]["deliverables"]) == 4
        assert Path(by_fmt["docx"]["relative_path"]).name != exp_data["docx_deliverable"]["filename"]
        en_pdf_path = resolve_project_file_path(settings.workspaces_dir, ws_slug, exp_data["pdf_deliverable"]["relative_path"])
        with pymupdf.open(str(en_pdf_path)) as en_pdf:
            en_pdf_txt = "\n".join(pg.get_text("text") for pg in en_pdf)
        en_pdf_norm = " ".join(en_pdf_txt.replace("\xa0", " ").replace("\xad", "-").split())
        assert "Technical specifications" in en_pdf_norm or "SPEC-01" in en_pdf_norm

        # 7. Run Step 12 QA Agent -> PASSES at 0 tokens and allows task verification
        qa_res = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid, "classification": "For Review"})
        assert qa_res.status_code == 201, qa_res.text
        qa_data = qa_res.json()
        assert qa_data["status"] == "passed", qa_data["issues"]
        assert qa_data["tokens_used"] == 0
        assert sid in qa_data["qa_context_summary"]["inspected_specification_ids"]

        ver_res = client.post(f"/api/tasks/{tid}/verify", json={"qa_review_id": qa_data["id"], "verifier_note": "Specs QA ok"})
        assert ver_res.status_code == 200
        assert ver_res.json()["verification_status"] == "verified"


def test_step14_ai_draft_unverified_until_owner_approval_and_qa_catches_spec_defects(tmp_path: Path) -> None:
    """Verify optional AI prose draft stays labelled unverified until owner approves, blocks QA verify, and QA catches orphan/missing/unsourced defects."""
    captured_prompts: list[str] = []

    def client_factory(_api_key: str) -> Any:
        class _Models:
            def list(self) -> list[Any]:
                return []

            def generate_content(self, **_kwargs: Any) -> Any:
                prompt_str = "\n".join(str(p) for p in (_kwargs.get("contents") or []))
                captured_prompts.append(prompt_str)
                return SimpleNamespace(
                    text="{}",
                    parsed={
                        "executive_summary": "Clarity-improved AI draft specification summary.",
                        "clause_rewrites": [
                            {
                                "section_code": "SPEC-01",
                                "clause_id": "SPEC-01-SCOPE-01",
                                "drafted_text": "Supply and install flush HPL clinic doors strictly matching BOQ item A-01 and A-101 schedule.",
                            },
                            {
                                "section_code": "SPEC-02",
                                "clause_id": "SPEC-02-SCOPE-01",
                                "drafted_text": "Malicious rewrite attempting to invent unverified code ASTM C150-20 for windows.",
                            },
                        ],
                    },
                    usage_metadata=SimpleNamespace(prompt_token_count=520, candidates_token_count=120, total_token_count=640),
                )

        return SimpleNamespace(models=_Models())

    settings = _test_settings(tmp_path)
    app = create_app(
        settings,
        secret_store=_InMemorySecretStore({"gemini": "test-step14-key"}),
        provider_client_factory=client_factory,
    )

    with TestClient(app) as client:
        project = client.post(
            "/api/projects",
            json={"name": "AI Spec Draft Clinic", "code": "SPEC-AI", "classification": "For Review"},
        ).json()
        pid = project["id"]
        ws_slug = project["workspace_slug"]

        with app.state.session_factory() as db:
            task = Task(
                project_id=pid,
                title="Draft Clinic Specifications",
                prompt="Draft specifications",
                task_type="assignment",
                status="completed",
                verification_status="unverified",
                classification="For Review",
                structured_output_json={"expected_deliverables": ["Specifications", "BOQ"]},
            )
            db.add(task)
            db.commit()
            tid = task.id

        boq_id, _ = _seed_clinic_boq_and_drawing(client, app, project_id=pid, task_id=tid)
        assert client.post(f"/api/boq-sheets/{boq_id}/export", json={"language": "en"}).status_code == 201

        # 1. Generate optional AI draft specification (EN LTR)
        ai_res = client.post(
            f"/api/projects/{pid}/specifications",
            json={
                "task_id": tid,
                "title": "Clinic AI-Drafted Specs",
                "language": "en",
                "classification": "For Review",
                "use_ai": True,
            },
        )
        assert ai_res.status_code == 201, ai_res.text
        spec_ai = ai_res.json()
        sid = spec_ai["id"]
        assert len(captured_prompts) == 1
        assert spec_ai["use_ai"] is True
        assert spec_ai["tokens_used"] == 640
        assert spec_ai["ai_draft_status"] == "unverified_ai_draft"
        assert AI_UNVERIFIED_DRAFT_LABEL_EN in spec_ai["ai_draft_label"]

        # AI rewrite without fabricated standard accepted & badged unverified; rewrite attempting ASTM C150-20 blocked!
        sec1_scope = next(c for c in spec_ai["sections"][0]["clauses"] if c["clause_id"] == "SPEC-01-SCOPE-01")
        assert sec1_scope["draft_origin"] == "ai_unverified_draft"
        assert AI_UNVERIFIED_DRAFT_LABEL_EN in sec1_scope["text"]
        assert not any("ASTM C150-20" in cl["text"] for sec in spec_ai["sections"] for cl in sec["clauses"])

        # Exported PDF also carries UNVERIFIED banner while unapproved
        deliv_pdf = next(d for d in spec_ai["deliverables"] if d["format"] == "pdf")
        pdf_p = resolve_project_file_path(settings.workspaces_dir, ws_slug, deliv_pdf["relative_path"])
        with pymupdf.open(str(pdf_p)) as pdoc:
            ptxt = "\n".join(pg.get_text("text") for pg in pdoc)
        assert AI_UNVERIFIED_DRAFT_LABEL_EN in " ".join(ptxt.split())

        # 2. QA Agent MUST block unapproved AI draft from passing task verification
        qa_unapproved = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid, "classification": "For Review"}).json()
        assert qa_unapproved["status"] == "issues_found"
        assert any(
            "pending owner approval" in (it.get("title") or "").lower()
            or "not yet been approved" in it["description"].lower()
            for it in qa_unapproved["issues"]
        )

        # 3. Owner approves AI draft -> removes unverified status & saves new versioned deliverables
        app_res = client.post(
            f"/api/specifications/{sid}/approve",
            json={"approved_by": "Eng. Owner", "approval_note": "Clauses verified", "export_after_approval": True},
        )
        assert app_res.status_code == 200, app_res.text
        spec_approved = app_res.json()
        assert spec_approved["ai_draft_status"] == "owner_approved"
        assert spec_approved["owner_approved_by"] == "Eng. Owner"
        assert spec_approved["export_version"] == 2
        assert len(spec_approved["deliverables"]) == 4

        # Close prior QA issue with closure note & re-run QA -> now PASSES cleanly!
        for it in qa_unapproved["issues"]:
            if it["status"] != "closed":
                client.patch(
                    f"/api/issues/{it['id']}",
                    json={"status": "closed", "closure_note": "Owner reviewed and approved AI specification draft."},
                )
        qa_ok = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid, "classification": "For Review"}).json()
        assert qa_ok["status"] == "passed", qa_ok["issues"]

        # 4. Seed orphan section, missing sub-sections, unsourced standard code, and corrupt deliverable SHA -> QA catches ALL
        with app.state.session_factory() as db:
            bad_spec = db.get(Specification, sid)
            assert bad_spec is not None
            payload = dict(bad_spec.structured_payload_json)
            sections = list(payload["sections"])
            # Seed orphan/missing section + unsourced standard on section 0
            bad_sec0 = dict(sections[0])
            bad_sec0["mapped_boq_item_ids"] = []
            bad_sec0["mapped_drawing_ids"] = []
            bad_sec0["standards"] = [
                {
                    "research_source_id": "nonexistent-source-999",
                    "source_name": "Invented Spec Code",
                    "url": "https://fake-spec.invalid/std",
                    "publication_date": None,
                    "status": "verified_source_log",
                    "citation_text": "Invented BS 9999 Clause 4.2",
                    "verification_label": VERIFY_CODE_LABEL,
                }
            ]
            # Drop testing and warranty clauses + inject ungrounded ASTM C150 into materials clause
            bad_sec0["clauses"] = [
                {**cl, "text": f"{cl['text']} per ACI 318-19"} if cl["part"] == "materials" else cl
                for cl in bad_sec0["clauses"]
                if cl["part"] not in ("testing", "warranty")
            ]
            sections[0] = bad_sec0
            payload["sections"] = sections
            bad_spec.structured_payload_json = payload

            pdf_deliv = (
                db.query(Deliverable)
                .filter(Deliverable.specification_id == sid, Deliverable.format == "pdf")
                .first()
            )
            assert pdf_deliv is not None and pdf_deliv.relative_path
            corrupt_pdf = resolve_project_file_path(settings.workspaces_dir, ws_slug, pdf_deliv.relative_path)
            corrupt_pdf.write_bytes(b"CORRUPT_SPEC_PDF")
            db.commit()

        qa_bad = client.post(f"/api/projects/{pid}/qa-reviews", json={"task_id": tid, "classification": "For Review"}).json()
        assert qa_bad["status"] == "issues_found"
        cats = {it["check_category"] for it in qa_bad["issues"]}
        titles = " | ".join(it["title"] for it in qa_bad["issues"]).lower()
        assert "schedule_consistency" in cats
        assert "reference" in cats
        assert "integrity" in cats
        assert "orphan" in titles or "unmapped" in titles
        assert "missing mandatory sub-sections" in titles

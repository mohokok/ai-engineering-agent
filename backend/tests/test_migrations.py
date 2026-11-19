"""Tests for Alembic migrations, DELETE RESTRICT integrity, and classification CHECK rules."""

from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.base import CLASSIFICATION_LABELS
from app.db.migrations import downgrade_database, upgrade_database
from app.db.models import (
    AuditLog,
    Calculation,
    Deliverable,
    FileExtraction,
    FileVersion,
    Project,
    ProjectFile,
    Task,
)
from app.db.session import create_db_engine, create_session_factory

EXPECTED_TABLES = {
    "projects",
    "files",
    "file_versions",
    "file_extractions",
    "tasks",
    "task_steps",
    "deliverables",
    "research_sources",
    "issues",
    "calculations",
    "settings",
    "audit_log",
}


def test_alembic_upgrade_and_downgrade_round_trip(tmp_path: Path) -> None:
    """Alembic upgrade creates all 11 tables and downgrade cleanly reverts them."""
    db_path = tmp_path / "nested" / "test_migrations.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    upgrade_database(db_url, "head")
    engine = create_db_engine(db_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert EXPECTED_TABLES.issubset(tables)
        task_columns = {col["name"] for col in inspector.get_columns("tasks")}
        assert {
            "complexity",
            "provider_name",
            "model_name",
            "attached_file_ids_json",
            "structured_output_json",
            "token_usage_json",
        }.issubset(task_columns)

        with engine.connect() as conn:
            fk_enabled = conn.execute(text("PRAGMA foreign_keys")).scalar()
            assert fk_enabled == 1
    finally:
        engine.dispose()

    downgrade_database(db_url, "base")
    engine = create_db_engine(db_url)
    try:
        tables_after_downgrade = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES.isdisjoint(tables_after_downgrade)
    finally:
        engine.dispose()

    upgrade_database(db_url, "head")
    engine = create_db_engine(db_url)
    try:
        assert EXPECTED_TABLES.issubset(set(inspect(engine).get_table_names()))
    finally:
        engine.dispose()


def test_ondelete_restrict_refuses_deleting_project_with_files_and_file_with_versions(
    tmp_path: Path,
) -> None:
    """Deleting a file with versions or a project with files is refused by ON DELETE RESTRICT."""
    db_path = tmp_path / "restrict_check.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    upgrade_database(db_url, "head")
    engine = create_db_engine(db_url)
    SessionLocal = create_session_factory(engine)

    try:
        with SessionLocal() as db:
            project = Project(
                code="RES-01",
                name="مشروع حماية الملفات",
                workspace_slug="restrict_test_01",
            )
            db.add(project)
            db.flush()

            project_file = ProjectFile(
                project_id=project.id,
                folder_name="01_Input_Documents",
                original_filename="brief.pdf",
                stored_relative_path="01_Input_Documents/brief.pdf",
                size_bytes=128,
                sha256="a" * 64,
                is_original=True,
                current_version=1,
            )
            db.add(project_file)
            db.flush()

            version = FileVersion(
                file_id=project_file.id,
                version_number=1,
                stored_relative_path="01_Input_Documents/brief.pdf",
                size_bytes=128,
                sha256="a" * 64,
            )
            db.add(version)
            db.commit()
            project_id = project.id
            file_id = project_file.id

        # 1. ORM delete of file that has versions must fail via DB RESTRICT
        with SessionLocal() as db:
            file_obj = db.get(ProjectFile, file_id)
            assert file_obj is not None
            db.delete(file_obj)
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()

        # 2. Direct SQL delete of file with versions must fail
        with SessionLocal() as db:
            with pytest.raises(IntegrityError):
                db.execute(text("DELETE FROM files WHERE id = :fid"), {"fid": file_id})
            db.rollback()

        # 3. ORM delete of project that has files must fail via DB RESTRICT
        with SessionLocal() as db:
            proj_obj = db.get(Project, project_id)
            assert proj_obj is not None
            db.delete(proj_obj)
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()

        # 4. Direct SQL delete of project with files must fail
        with SessionLocal() as db:
            with pytest.raises(IntegrityError):
                db.execute(text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id})
            db.rollback()

        # Confirm project, file, and version records remain intact
        with SessionLocal() as db:
            assert db.get(Project, project_id) is not None
            assert db.get(ProjectFile, file_id) is not None
            assert db.query(FileVersion).filter_by(file_id=file_id).count() == 1
    finally:
        engine.dispose()


def test_classification_check_constraint_enforces_five_claude_labels(tmp_path: Path) -> None:
    """CHECK constraints accept all five CLAUDE.md classification labels and reject invalid values."""
    db_path = tmp_path / "classification_check.db"
    db_url = f"sqlite:///{db_path.as_posix()}"

    # Also verify upgrading an already-populated 0001 DB through 0002 -> 0003
    upgrade_database(db_url, "0001")
    engine = create_db_engine(db_url)
    SessionLocal = create_session_factory(engine)
    try:
        with SessionLocal() as db:
            seed_project = Project(
                code="CLS-00",
                name="مشروع أساسي",
                workspace_slug="cls_seed_00",
                classification="Preliminary",
            )
            db.add(seed_project)
            db.flush()
            seed_file = ProjectFile(
                project_id=seed_project.id,
                folder_name="01_Input_Documents",
                original_filename="seed.pdf",
                stored_relative_path="01_Input_Documents/seed.pdf",
                classification="Preliminary",
            )
            db.add(seed_file)
            db.flush()
            db.add(
                AuditLog(
                    project_id=seed_project.id,
                    action="project.created",
                    entity_type="project",
                    entity_id=seed_project.id,
                )
            )
            db.commit()
            seed_id = seed_project.id
            seed_file_id = seed_file.id
    finally:
        engine.dispose()

    upgrade_database(db_url, "head")
    engine = create_db_engine(db_url)
    SessionLocal = create_session_factory(engine)
    try:
        # All 5 CLAUDE.md labels succeed
        with SessionLocal() as db:
            for idx, label in enumerate(CLASSIFICATION_LABELS):
                proj = Project(
                    code=f"CLS-{idx + 1}",
                    name=f"مشروع {idx + 1}",
                    workspace_slug=f"cls_slug_{idx + 1}",
                    classification=label,
                )
                db.add(proj)
            db.commit()

        # Invalid labels are rejected by CHECK constraints on every classified table
        for bad_label in ("Draft", "Approved", "Construction-ready", ""):
            with SessionLocal() as db:
                db.add(
                    Project(
                        code="BAD-P",
                        name="Bad Project",
                        workspace_slug="bad_proj_slug",
                        classification=bad_label,
                    )
                )
                with pytest.raises(IntegrityError):
                    db.flush()
                db.rollback()

        with SessionLocal() as db:
            db.add(
                ProjectFile(
                    project_id=seed_id,
                    folder_name="01_Input_Documents",
                    original_filename="spec.pdf",
                    stored_relative_path="01_Input_Documents/spec.pdf",
                    classification="InvalidLabel",
                )
            )
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()

            db.add(
                Task(
                    project_id=seed_id,
                    title="Review",
                    prompt="Review design",
                    classification="InvalidLabel",
                )
            )
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()

            db.add(
                Deliverable(
                    project_id=seed_id,
                    title="Report",
                    deliverable_type="report",
                    format="pdf",
                    classification="InvalidLabel",
                )
            )
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()

            db.add(
                Calculation(
                    project_id=seed_id,
                    title="Load calc",
                    discipline="structural",
                    calculation_type="beam",
                    inputs_json={"span_m": 6},
                    results_json={"moment_knm": 45},
                    classification="InvalidLabel",
                )
            )
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()

            db.add(
                FileExtraction(
                    project_id=seed_id,
                    file_id=seed_file_id,
                    version_number=1,
                    extraction_version=1,
                    source_sha256="a" * 64,
                    counts_json={},
                    warnings_json=[],
                    rendered_images_json=[],
                    payload_json={},
                    classification="InvalidLabel",
                )
            )
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()
    finally:
        engine.dispose()

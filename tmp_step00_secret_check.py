"""Temporary test fixture for Step 00 automated PR review validation (will be closed without merging)."""

API_SECRET_KEY = "FAKE_SECRET_FOR_STEP00_REVIEW_TEST_00000"


def build_auth_header(project_id: str) -> dict[str, str]:
    """Build a mock authorization header using the planted dummy secret."""
    return {
        "X-Project-Id": project_id,
        "Authorization": f"Bearer {API_SECRET_KEY}",
    }

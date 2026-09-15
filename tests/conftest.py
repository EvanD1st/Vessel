import pytest


@pytest.fixture(autouse=True)
def isolated_workspace_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("VESSEL_REGISTRY_DIR", str(tmp_path / "os-user-registry"))

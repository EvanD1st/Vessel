import pytest

from vessel.artifacts import Artifacts
from vessel.companion import WorkspaceWatcher
from vessel.service import Blocked
from vessel.storage import Store


def test_watcher_includes_root_edits_deletion_and_excludes_secrets(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "app.py"
    source.write_text("pass\n")
    store = Store(tmp_path / "state")
    try:
        watcher = WorkspaceWatcher(Artifacts(project, store))
        assert not watcher.poll()
        source.write_text("print('changed')\n")
        assert watcher.poll()
        source.unlink()
        assert watcher.poll()
        (project / ".env").write_text("SECRET=not-an-event")
        assert not watcher.poll()
    finally:
        store.close()


def test_incomplete_scan_is_visible_and_does_not_reset_baseline():
    class FakeArtifacts:
        issue = False

        def _inventory(self):
            return {"app.py": (1,)}, [], ["unreadable"] if self.issue else []

    artifacts = FakeArtifacts()
    watcher = WorkspaceWatcher(artifacts)
    assert not watcher.poll()
    artifacts.issue = True
    with pytest.raises(Blocked):
        watcher.poll()
    assert watcher.previous == {"app.py": (1,)}

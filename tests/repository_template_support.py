"""Process-local, pre-worktree repository templates for lifecycle fixtures."""

from pathlib import Path
import shutil
import subprocess
import tempfile


class RepositoryTemplate:
    """Build once; copy bytes (including the index), never linked worktrees."""

    def __init__(self, build):
        self.temporary = tempfile.TemporaryDirectory(prefix="repository-template-")
        self.project = Path(self.temporary.name) / "project"
        try:
            build(self.project)
            git = self.project / ".git"
            if not git.is_dir() or (git / "worktrees").exists():
                raise ValueError("template must be an ordinary repository without worktree registrations")
            if (git / "commondir").exists():
                raise ValueError("template must not be a linked worktree")
        except BaseException:
            self.cleanup()
            raise

    def copy_to(self, destination):
        shutil.copytree(self.project, destination)
        return destination

    def cleanup(self):
        self.temporary.cleanup()


def authorize_copy(project):
    """Publish fresh fixture receipts for the copy's own paths before prepare.

    Repository bytes remain a faithful copy until this explicit fixture step.
    Product authorization and fixture sealing perform the rebinding; no receipt
    digest or product gate is patched.
    """
    from cardine.lifecycle import receipts
    from task_contract_support import seal_state
    authority = project / ".cardine/receipt-authority.json"
    if not authority.exists():
        return
    receipts.authorize_project(project, accepted=receipts.observed_authority(project))
    paths = [authority]
    for state in sorted((project / ".cardine/tasks").glob("*.json")):
        seal_state(project, state.stem)
        paths.append(state)
    subprocess.run(["git", "add", *[str(p.relative_to(project)) for p in paths]],
                   cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "Authorize fixture copy"],
                   cwd=project, check=True, capture_output=True)

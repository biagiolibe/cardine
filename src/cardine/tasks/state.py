"""Receipt-gated state readers; pure validation remains separately reusable."""
from pathlib import Path
import json
import shlex
from cardine.shared.layout import names
from cardine.tasks.state_core import (
    STATUSES, STATE_MACHINE, SCHEMA_PATH, TaskStateInvalid, _invalid, _validate_schema,
    machine, require_contract_snapshot, review_is_required, dependency_satisfied,
    validate_task_state, state_path, write_state_bytes,
)


def read_task_state(project_root, task_id, workflow, *, spike=False, review_required=None, stop_factory,
                    text=None, require_contract=False, artifacts=False, artifact_ref=None):
    """Verify the consumed state/snapshot, returning state or a registered stop.

    Frozen readers do not consume mutable task prose. Artifact consumers opt in
    to coverage of their files (and specify the matching Git revision).
    """
    try:
        path = state_path(project_root, task_id)
        if text is None:
            from cardine.lifecycle.receipts import safe_path
            from cardine.shared.errors import CardineError
            try:
                safe_path(project_root, path.relative_to(project_root).as_posix())
            except CardineError as error:
                raise TaskStateInvalid(str(error)) from error
            intent = path.with_name(f'.{task_id}.intent.json')
            if intent.exists():
                from cardine.lifecycle.receipts import interrupted_transition, operation_live
                target = None if operation_live(project_root, task_id) else interrupted_transition(project_root, task_id)
                if target is not None:
                    raise stop_factory(
                        "TASK_STATE_INTERRUPTED", "interrupted task transition; replay the identical command",
                        resume=f"cardine task transition {task_id} {target} --project {shlex.quote(str(project_root))} --format json",
                        task_id=task_id, project=project_root)
                raise stop_factory("TASK_STATE_INVALID", "interrupted or active task creation/revision; replay identical command",
                                   task_id=task_id, project=project_root)
            journal = Path(project_root) / names().project_directory / "task-creation.lock"
            if journal.exists():
                raise stop_factory("TASK_STATE_INVALID",
                                   f"interrupted or active task creation: {journal}; retry or use task new --recover",
                                   task_id=task_id, project=project_root)
            try:
                text = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                raise stop_factory("TASK_STATE_MISSING", f"state file: allowed existing {path}; found missing",
                                   task_id=task_id, project=project_root)
            if journal.exists() or intent.exists():
                raise stop_factory("TASK_STATE_INVALID", f"task creation changed during read: {journal}; retry",
                                   task_id=task_id, project=project_root)
        try:
            state = json.loads(text)
        except json.JSONDecodeError as error:
            _invalid("state", "valid JSON", str(error))
        if require_contract and isinstance(state, dict) and "contract" not in state:
            _validate_schema(state, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
            if state["task_id"] != task_id:
                _invalid("task_id", [task_id], state["task_id"])
            require_contract_snapshot(state, project_root)
        validate_task_state(state, task_id, workflow, spike=spike, review_required=review_required)
        from cardine.lifecycle.receipts import verify_receipts
        from cardine.shared.errors import CardineError
        try:
            verify_receipts(project_root, state, artifacts=artifacts, artifact_ref=artifact_ref)
        except CardineError as error:
            raise TaskStateInvalid(str(error)) from error
        return state
    except (OSError, UnicodeError) as error:
        raise stop_factory("TASK_STATE_INVALID", f"state file: allowed readable UTF-8 JSON; found {error}",
                           task_id=task_id, project=project_root) from error
    except TaskStateInvalid as error:
        raise stop_factory("TASK_STATE_INVALID", str(error), task_id=task_id, project=project_root) from error

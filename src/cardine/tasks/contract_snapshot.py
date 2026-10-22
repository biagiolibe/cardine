"""Runtime access to frozen human intent, without record or identity parsing."""
from cardine.tasks.contract_fields import frozen_human_fields


def read_human_contract(project_root, task_id):
    """Read frozen human intent without identity resolution or record access."""
    from cardine.tasks.state import read_task_state, state_path
    from cardine.tasks.identity import resolve_task_identity
    from cardine.stops.render import stop_error
    if not state_path(project_root, task_id).exists():
        task_id = resolve_task_identity(project_root, task_id, "existing").canonical_id
    return frozen_human_fields(read_task_state(project_root, task_id, "single", stop_factory=stop_error))



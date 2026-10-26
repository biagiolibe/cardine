"""Receipt-covered non-run updater effects; no installation authenticity claim."""
from __future__ import annotations

import uuid

from cardine.lifecycle import receipts
from cardine.release.version import read_raw_version
from cardine.shared.errors import CardineError
from cardine.shared.git import canonical_git_common_dir, git_output, _run_git


def owner(root, target_tag):
    return dict(root=str(root), common=str(canonical_git_common_dir(root)),
                kind='self-update', requested=target_tag)


def pending(path, binding):
    if not path.exists():
        return None
    intent = receipts._load_intent(path)
    if not isinstance(intent.get('owner'), dict) or any(
            intent['owner'].get(key) != value for key, value in binding.items() if key != 'requested'):
        raise CardineError('self-update operation owner changed')
    if intent.get('result') is not None:
        return None
    if intent.get('owner') != binding:
        raise CardineError('self-update operation owner or requested inputs changed')
    return intent


def verify(root, intent):
    """Accept only the original source or the exact applied output."""
    if owner(root, intent['owner']['requested']) != intent['owner']:
        raise CardineError('self-update operation owner changed')
    if git_output(root, 'status', '--porcelain', '--untracked-files=all'):
        from cardine.stops.render import stop_error
        raise stop_error('SELF_UPDATE_DIRTY', 'checkout changed during self-update')
    source = intent['source']
    if (git_output(root, 'branch', '--show-current') != source['branch']
            or git_output(root, 'remote', 'get-url', 'origin') != source['remote']):
        raise CardineError('self-update branch or origin changed')
    head = git_output(root, 'rev-parse', 'HEAD')
    expected = intent['version'] if head == intent['target'] else source['version']
    if head not in (source['head'], intent['target']) or read_raw_version(root) != expected:
        raise CardineError('self-update source HEAD/VERSION changed')


def apply_update(root, path, binding, source, version, templates, target, tag, intent):
    if intent is None:
        intent = dict(version=version, templates=templates, target=target, tag=tag,
                      owner=binding, source=source, operation_id=uuid.uuid4().hex,
                      effects={}, result=None)
        receipts._save_intent(path, intent)

    def valid():
        verify(root, intent)

    def fetched():
        result = _run_git(root, 'rev-parse', '--verify', f'refs/tags/{tag}^{{commit}}')
        if result.returncode:
            return False
        if result.stdout.strip() != target:
            raise CardineError('self-update pinned release tag changed')
        if git_output(root, 'show', f'{target}:VERSION') != version:
            raise CardineError('self-update pinned VERSION changed')
        return True

    def fetch():
        # Fetch only the inspected tag. A newer stable/latest cannot widen it.
        git_output(root, 'fetch', '--no-tags', '--', source['remote'],
                   f'refs/tags/{tag}:refs/tags/{tag}')

    def applied():
        return (git_output(root, 'rev-parse', 'HEAD') == target
                and read_raw_version(root) == version)

    def apply():
        if source['branch']:
            git_output(root, 'merge', '--ff-only', target)
        else:
            git_output(root, 'switch', '--detach', target)

    receipts.external_effect(path, intent, 'update_fetch', valid, fetch, fetched)
    receipts.external_effect(path, intent, 'update_apply', valid, apply, applied)
    # Verification is also a boundary: an interrupted observation is repeated,
    # never treated as a successful result just because HEAD moved.
    receipts.external_effect(path, intent, 'update_verify', valid, lambda: None, applied)
    return intent

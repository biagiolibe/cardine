#!/usr/bin/env python3
"""Assemble the hook-free Claude plugin outside the source checkout.

Usage: python3 scripts/build_host_plugin.py DESTINATION [--check]
Publish the resulting directory as the marketplace, rather than the checkout.
Host installation and enablement remain native Claude operations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from cardine.lifecycle import receipts
from cardine.lifecycle.file_operation import operation
from cardine.shared import atomic
from cardine.shared.errors import CardineError

SKILLS = ('cardine-project', 'cardine-delivery')
COMMANDS = ('cardine-adopt', 'cardine-init', 'cardine-audit', 'cardine-upgrade', 'cardine-task')
FILES = ('.claude-plugin/plugin.json', '.claude-plugin/marketplace.json', 'LICENSE',
         *(f'skills/{name}/SKILL.md' for name in SKILLS),
         *(f'commands/{name}.md' for name in COMMANDS))


def payload(root=ROOT):
    files = {}
    for name in FILES:
        source = receipts.safe_path(root, name)
        if not source.is_file():
            raise CardineError(f'missing plugin source: {name}')
        files[name] = source.read_bytes()
    manifest = json.loads(files['.claude-plugin/plugin.json'])
    marketplace = json.loads(files['.claude-plugin/marketplace.json'])
    if (manifest.get('name') != 'cardine' or marketplace.get('name') != 'cardine'
            or len(marketplace.get('plugins', [])) != 1
            or marketplace['plugins'][0].get('name') != 'cardine'
            or marketplace['plugins'][0].get('source') != './'
            or 'hooks' in manifest):
        raise CardineError('expected a hook-free Cardine plugin and local marketplace')
    return files


def inventory(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise CardineError(f'expected a plugin directory: {directory}')
    result = {}
    for path in directory.rglob('*'):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise CardineError(f'foreign plugin path: {path}')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = path.read_bytes()
    return result


def check(destination, root=ROOT):
    """Read-only verification; this does not claim that a host loaded the plugin."""
    if inventory(destination) != payload(root):
        raise CardineError('plugin contents differ from the hook-free distribution')


def build(destination, root=ROOT):
    destination = Path(destination).expanduser().absolute()
    # Check ancestors before resolve: resolving first would hide foreign links.
    receipts.safe_path(Path(destination.anchor), destination.as_posix().lstrip('/'))
    root = Path(root).resolve()
    if destination.is_relative_to(root) or root.is_relative_to(destination):
        raise CardineError('plugin destination must be outside the source checkout')
    if not destination.parent.is_dir():
        raise CardineError('plugin destination parent must already exist')
    files = payload(root)
    binding = dict(kind='host-plugin', source=str(root), target=str(destination),
                   digest=receipts.digest(receipts.encoded(
                       {name: receipts.digest(data) for name, data in files.items()})))
    receipt = receipts.host_path('host-plugin', destination)
    staging = destination.with_name('.' + destination.name + '.cardine-stage')
    with operation(receipt, binding) as active:
        previous = receipts._load_intent(receipt) if receipt.exists() else None
        owned = previous is not None and previous.get('owner') == binding
        if destination.exists():
            if not owned:
                raise CardineError('refusing an unowned plugin destination')
            check(destination, root)
            if previous.get('result') is not None and not (staging.exists() or staging.is_symlink()):
                return destination
        if staging.exists() or staging.is_symlink():
            if not owned or previous.get('result') is not None:
                raise CardineError('refusing an unowned plugin staging directory')
            staged = inventory(staging)
            if any(name not in files or files[name] != data for name, data in staged.items()):
                raise CardineError('plugin staging contents changed')
        published = lambda: destination.is_dir() and inventory(destination) == files
        active.effect('assembly', lambda: staging.mkdir(),
                      lambda: published() or (staging.is_dir() and not staging.is_symlink()))
        for name, data in files.items():
            target = staging / name

            def copy(target=target, data=data):
                receipts.safe_path(staging, target.relative_to(staging).as_posix())
                if target.exists() and (not target.is_file() or target.read_bytes() != data):
                    raise CardineError(f'plugin staging contents changed: {target}')
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic.replace_bytes(target, data, 0o644)

            def copied(target=target, data=data):
                if published():
                    return True
                receipts.safe_path(staging, target.relative_to(staging).as_posix())
                return target.is_file() and target.read_bytes() == data

            active.effect('copy:' + name, copy,
                          copied)

        def publish():
            check(staging, root)
            staging.rename(destination)
            receipts._sync_directory(destination.parent)

        active.effect('publication', publish, published)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--check', action='store_true')
    options = parser.parse_args()
    try:
        if options.check:
            check(options.destination)
        else:
            build(options.destination)
    except (CardineError, OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print('Hook-free Cardine plugin verified.')


if __name__ == '__main__':
    main()

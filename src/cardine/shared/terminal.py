"""Small terminal presentation helpers for human-facing commands."""
from contextlib import contextmanager
import os
import sys
import threading


def enabled():
    return sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb'


def _style(text, code):
    return f'\033[{code}m{text}\033[0m' if enabled() else text


def section(title):
    return _style(title, '1')


def step(index, total, label):
    return f'[{index}/{total}] {label} …'


def done(detail):
    return f'{detail} {_style("✓", "32")}'


def skipped(detail):
    return f'{detail} {_style("–", "33")}'


def failed(detail):
    return f'{detail} {_style("✗", "31")}'


def note(text):
    return f'Note: {text}'


def warn(text):
    return _style(f'Warning: {text}', '33')


def error(text):
    return _style(f'Error: {text}', '31')


def command(text):
    return _style(text, '1')


@contextmanager
def spinner(label):
    if not enabled():
        yield
        return
    stop = threading.Event()
    def animate():
        index = 0
        while not stop.is_set():
            sys.stderr.write(f'\r{label} {"|/-"[index % 3]}')
            sys.stderr.flush()
            index += 1
            stop.wait(0.1)
    thread = threading.Thread(target=animate, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
        sys.stderr.write('\r\033[2K')
        sys.stderr.flush()

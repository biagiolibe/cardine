"""Disposable coordinator channel for lifecycle CLI integration fixtures."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cardine.cli import main
from control_support import adapter

if __name__ == '__main__':
    with patch('cardine.lifecycle.control.host_adapter', return_value=adapter('coordinator')):
        raise SystemExit(main())

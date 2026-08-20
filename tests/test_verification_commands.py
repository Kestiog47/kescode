"""Tests for Windows verification command quoting."""

from __future__ import annotations

import os
import sys

import pytest

from kescode.graph.nodes import _run_verification_command, _use_current_python


@pytest.mark.skipif(os.name != "nt", reason="Windows path quoting only")
def test_use_current_python_quotes_absolute_python_path() -> None:
    for path in (
        sys.executable,
        sys.executable.replace("\\", "/"),
    ):
        command = f"{path} -m py_compile run.py"
        assert _use_current_python(command) == f'"{path}" -m py_compile run.py'

    assert _use_current_python(
        "C:/Program Files/Python313/python.exe -m py_compile run.py"
    ) == '"C:/Program Files/Python313/python.exe" -m py_compile run.py'
    assert _use_current_python(
        r"C:\Program Files\Python313\python.exe -m py_compile run.py"
    ) == r'"C:\Program Files\Python313\python.exe" -m py_compile run.py'


def test_use_current_python_replaces_python_prefix() -> None:
    expected_executable = (
        f'"{sys.executable}"' if os.name == "nt" else sys.executable
    )
    assert _use_current_python("python -m py_compile run.py") == (
        f"{expected_executable} -m py_compile run.py"
    )


def test_run_verification_command_with_unquoted_python_path(tmp_path) -> None:
    command = f'{sys.executable} -c "print(\'ok\')"'
    result = _run_verification_command(command, tmp_path)
    assert result["ok"] is True
    assert "ok" in result["stdout"]

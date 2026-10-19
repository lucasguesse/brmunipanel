"""Tests for the brmunipanel CLI interface."""

from __future__ import annotations

import pytest

from brmunipanel import cli


def test_cli_version_and_help() -> None:
    """Verifies that --version and build --help exit with code 0."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0

    with pytest.raises(SystemExit) as exc:
        cli.main(["build", "--help"])
    assert exc.value.code == 0


def test_cli_missing_required_arguments() -> None:
    """Verifies that missing raw-dir or output-dir results in an argument error."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["build"])
    assert exc.value.code != 0

    with pytest.raises(SystemExit) as exc:
        cli.main(["build", "--raw-dir", "some_dir"])
    assert exc.value.code != 0

    with pytest.raises(SystemExit) as exc:
        cli.main(["build", "--output-dir", "some_dir"])
    assert exc.value.code != 0


def test_cli_finalize_requires_version_and_date(tmp_path) -> None:
    """Verifies that finalize stage requires dataset version and date."""
    with pytest.raises(ValueError, match="--dataset-version and --date are required for the finalize stage"):
        cli.main([
            "build",
            "--raw-dir",
            str(tmp_path / "raw"),
            "--output-dir",
            str(tmp_path / "out"),
            "--stage",
            "finalize",
        ])

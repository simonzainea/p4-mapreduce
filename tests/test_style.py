"""Verify Python linting and formatting with Ruff."""

import subprocess

import utils


def test_ruff_check():
    """Run Ruff with the course-provided lint rules."""
    utils.assert_no_prohibited_terms("noqa")
    subprocess.run(
        [
            "ruff",
            "check",
            "--config",
            str(utils.TESTDATA_DIR / "ruff.toml"),
            "--no-respect-gitignore",
            "mapreduce",
        ],
        check=True,
    )


def test_ruff_format():
    """Run Ruff with the course-provided formatting rules."""
    utils.assert_no_prohibited_terms("fmt:", "yapf:")
    subprocess.run(
        [
            "ruff",
            "format",
            "--check",
            "--config",
            str(utils.TESTDATA_DIR / "ruff.toml"),
            "--no-respect-gitignore",
            "mapreduce",
        ],
        check=True,
    )

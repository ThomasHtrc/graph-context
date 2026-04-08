"""Git operations for change detection and history."""

from __future__ import annotations

import subprocess
from pathlib import Path


def is_git_repo(path: str | Path) -> bool:
    """Check if path is inside a git repository."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(path), capture_output=True, check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_head_hash(repo_path: str | Path) -> str | None:
    """Get the current HEAD commit hash, or None if no commits."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_path), capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_changed_files(repo_path: str | Path, since_hash: str | None = None) -> list[str]:
    """Get files changed since a given commit hash.

    If since_hash is None, returns all tracked + untracked files.
    """
    results: set[str] = set()

    if since_hash:
        # Files changed in commits since that hash
        try:
            r = subprocess.run(
                ["git", "diff", "--name-only", since_hash, "HEAD"],
                cwd=str(repo_path), capture_output=True, text=True, check=True,
            )
            results.update(line for line in r.stdout.strip().splitlines() if line)
        except subprocess.CalledProcessError:
            pass

    # Uncommitted changes (staged + unstaged)
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(repo_path), capture_output=True, text=True, check=True,
        )
        results.update(line for line in r.stdout.strip().splitlines() if line)
    except subprocess.CalledProcessError:
        pass

    # Untracked files
    try:
        r = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(repo_path), capture_output=True, text=True, check=True,
        )
        results.update(line for line in r.stdout.strip().splitlines() if line)
    except subprocess.CalledProcessError:
        pass

    return sorted(results)


def get_all_tracked_files(repo_path: str | Path) -> list[str]:
    """Get all files tracked by git (plus untracked)."""
    results: set[str] = set()
    try:
        r = subprocess.run(
            ["git", "ls-files"],
            cwd=str(repo_path), capture_output=True, text=True, check=True,
        )
        results.update(line for line in r.stdout.strip().splitlines() if line)
    except subprocess.CalledProcessError:
        pass

    # Also include untracked files
    try:
        r = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(repo_path), capture_output=True, text=True, check=True,
        )
        results.update(line for line in r.stdout.strip().splitlines() if line)
    except subprocess.CalledProcessError:
        pass

    return sorted(results)

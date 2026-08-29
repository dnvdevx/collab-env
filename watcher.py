"""
Mission Control - local watcher script.

Run this in your project folder while you work. Every time you save a file,
it computes a git diff and posts a checkpoint to the team dashboard.

Usage:
    python watcher.py --feature-id 1 --backend-url http://localhost:8000 --path .

Requires: the folder must be a git repo (git init / git clone), since we use
`git diff` to compute what changed. It does NOT require you to commit -
uncommitted changes are diffed against the last commit automatically.
"""

import argparse
import subprocess
import time
from pathlib import Path

import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


# Directories/files we never want to watch - editor junk, dependencies, git internals.
# Without this, saving inside node_modules or .git would spam checkpoints constantly.
IGNORED_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIR_NAMES for part in path.parts)


def get_git_diff(repo_path: Path) -> str:
    """Returns the unified diff of uncommitted changes (working dir vs last commit)."""
    result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return result.stdout


def get_diff_stats(repo_path: Path) -> dict:
    """Parses `git diff --stat` to get files-changed / lines-added / lines-removed
    counts, so the dashboard tile can show a quick summary without rendering the
    full diff text."""
    result = subprocess.run(
        ["git", "diff", "HEAD", "--numstat"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    files_changed = 0
    lines_added = 0
    lines_removed = 0
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            added, removed, _ = parts
            files_changed += 1
            # Binary files report "-" instead of a number - skip those safely
            if added.isdigit():
                lines_added += int(added)
            if removed.isdigit():
                lines_removed += int(removed)
    return {
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
    }


def check_run_status(run_command: str | None, repo_path: Path) -> tuple[str, str | None]:
    """If the user configured a run/test command, execute it and report whether
    it exited clean or crashed. Returns (status, output_tail).
    If no command was configured, status stays 'unknown' - we simply don't know."""
    if not run_command:
        return "unknown", None

    try:
        result = subprocess.run(
            run_command,
            shell=True,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,  # don't let a hanging dev server block the watcher forever
        )
        output = (result.stdout + result.stderr)[-2000:]  # keep last 2000 chars only
        status = "clean" if result.returncode == 0 else "crashing"
        return status, output
    except subprocess.TimeoutExpired:
        return "unknown", "Run command timed out after 30s"


class CheckpointHandler(FileSystemEventHandler):
    """Fires on every file save inside the watched folder. Debounces so that
    saving many files quickly (e.g. an editor's 'save all') sends one checkpoint,
    not a burst of them."""

    def __init__(self, repo_path: Path, feature_id: int, backend_url: str,
                 run_command: str | None, debounce_seconds: float = 2.0):
        self.repo_path = repo_path
        self.feature_id = feature_id
        self.backend_url = backend_url
        self.run_command = run_command
        self.debounce_seconds = debounce_seconds
        self._last_event_time = 0.0
        self._pending = False

    def on_modified(self, event):
        if event.is_directory:
            return
        if is_ignored(Path(event.src_path)):
            return
        self._last_event_time = time.time()
        self._pending = True

    def maybe_send_checkpoint(self):
        """Called on a timer from the main loop. Only sends once the debounce
        window has passed since the last save, so rapid saves collapse into one."""
        if not self._pending:
            return
        if time.time() - self._last_event_time < self.debounce_seconds:
            return

        self._pending = False
        self._send_checkpoint()

    def _send_checkpoint(self):
        diff = get_git_diff(self.repo_path)
        if not diff.strip():
            return  # nothing actually changed (e.g. saved with no edits) - skip

        stats = get_diff_stats(self.repo_path)
        run_status, run_output = check_run_status(self.run_command, self.repo_path)

        payload = {
            "feature_id": self.feature_id,
            "diff_content": diff,
            "run_status": run_status,
            "run_output": run_output,
            **stats,
        }

        try:
            resp = requests.post(f"{self.backend_url}/checkpoints", json=payload, timeout=5)
            if resp.status_code == 200:
                print(f"[checkpoint sent] {stats['files_changed']} files, "
                      f"+{stats['lines_added']}/-{stats['lines_removed']}, run={run_status}")
            else:
                print(f"[checkpoint failed] {resp.status_code}: {resp.text}")
        except requests.RequestException as e:
            print(f"[checkpoint failed] could not reach backend: {e}")


def main():
    parser = argparse.ArgumentParser(description="Mission Control local watcher")
    parser.add_argument("--feature-id", type=int, required=True,
                         help="The feature ID this checkpoint stream belongs to (from /features)")
    parser.add_argument("--backend-url", default="http://localhost:8000",
                         help="Base URL of the Mission Control API")
    parser.add_argument("--path", default=".", help="Folder to watch (must be a git repo)")
    parser.add_argument("--run-command", default=None,
                         help="Optional command to run on each checkpoint to check build/test health, "
                              "e.g. 'npm run build' or 'pytest'")
    args = parser.parse_args()

    repo_path = Path(args.path).resolve()
    if not (repo_path / ".git").exists():
        print(f"Error: {repo_path} is not a git repository. Run `git init` first.")
        return

    handler = CheckpointHandler(
        repo_path=repo_path,
        feature_id=args.feature_id,
        backend_url=args.backend_url,
        run_command=args.run_command,
    )

    observer = Observer()
    observer.schedule(handler, str(repo_path), recursive=True)
    observer.start()

    print(f"Watching {repo_path} for changes -> feature #{args.feature_id} at {args.backend_url}")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(0.5)
            handler.maybe_send_checkpoint()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()

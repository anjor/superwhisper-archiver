"""Main orchestrator for the superwhisper archiver."""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .models import ArchiverConfig, ArchiveResult, ArchiveSummary
from .scanner import Scanner
from .markdown_formatter import MarkdownFormatter
from .git_manager import GitManager
from .notifications import notify_macos
from .state_tracker import StateTracker

console = Console()

CONFIG_ENV_VAR = "SUPERWHISPER_ARCHIVER_CONFIG"
USER_CONFIG_RELATIVE = Path(".config") / "superwhisper-archiver" / "config.yaml"

# Number of consecutive failed runs after which a recording is worth alerting on.
ALERT_ATTEMPT_THRESHOLD = 3


def setup_logging(config: ArchiverConfig):
    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)
    log_file = Path(config.logging.file).expanduser()
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True),
            logging.FileHandler(log_file),
        ],
    )


def default_state_db_path() -> Path:
    """Absolute path to the state database.

    Anchored to the installation directory rather than the working directory,
    so running the archiver from elsewhere cannot silently start a second,
    empty database and re-archive everything.
    """
    return Path(__file__).resolve().parent.parent / "state" / "archive_state.db"


def find_config_path(explicit_path: Optional[str] = None) -> Path:
    """Find the config file.

    Search order:
    1. Explicit path from --config
    2. $SUPERWHISPER_ARCHIVER_CONFIG
    3. ~/.config/superwhisper-archiver/config.yaml
    4. ./config.yaml (development)

    Raises:
        FileNotFoundError: If no config file is found.
    """
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {explicit_path}")
        return path

    env_path = os.getenv(CONFIG_ENV_VAR)
    if env_path:
        path = Path(env_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found (from {CONFIG_ENV_VAR}): {env_path}")
        return path

    user_config = Path.home() / USER_CONFIG_RELATIVE
    if user_config.exists():
        return user_config

    local_config = Path("config.yaml")
    if local_config.exists():
        return local_config

    raise FileNotFoundError(
        "No config file found. Looked for "
        f"${CONFIG_ENV_VAR}, {user_config}, and ./config.yaml"
    )


def load_config(config_path: Optional[str] = None) -> ArchiverConfig:
    path = find_config_path(config_path)
    console.print(f"[dim]Using config: {path}[/dim]")
    with open(path, "r") as f:
        config_dict = yaml.safe_load(f)
    return ArchiverConfig(**config_dict)


def recordings_needing_alert(failures, attempt_threshold: int = ALERT_ATTEMPT_THRESHOLD):
    """Failures that have persisted long enough to warrant an alert.

    Args:
        failures: Rows from ``StateTracker.get_failures()``.
        attempt_threshold: Number of failed attempts at which to alert.
    """
    return [f for f in failures if f["attempts"] >= attempt_threshold]


def maybe_alert_failures(
    state_tracker: StateTracker,
    notifier=None,
    attempt_threshold: int = ALERT_ATTEMPT_THRESHOLD,
):
    """Notify when recordings have been failing to archive across several runs.

    Keeps the archiver from failing silently for days.

    Args:
        state_tracker: State tracker holding the failure counts.
        notifier: Callable ``(title, message)``. Defaults to a macOS notification.
        attempt_threshold: Number of failed attempts at which to alert.

    Returns:
        The failures that triggered the alert (possibly empty).
    """
    if notifier is None:
        notifier = notify_macos

    alerting = recordings_needing_alert(state_tracker.get_failures(), attempt_threshold)
    if not alerting:
        return []

    dirs = ", ".join(f["source_dir"] for f in alerting)
    last_error = alerting[0].get("last_error") or "unknown error"
    message = (
        f"{len(alerting)} recording(s) failing to archive (e.g. {dirs}). "
        f"Last error: {last_error}"
    )
    notifier("superwhisper archiver: archiving is failing", message)
    logging.getLogger(__name__).warning(message)
    return alerting


def record_archive_outcome(
    state_tracker: StateTracker,
    source_dir: str,
    result: ArchiveResult,
    dry_run: bool = False,
):
    """Update failure counts based on the outcome of archiving a recording.

    A failed recording needs no explicit retry queue: it stays out of
    ``archived_recordings``, so the next scan picks it up again. The count is
    kept only so that persistent failures can be alerted on. Dry runs never
    mutate state.
    """
    if dry_run:
        return
    if result.success:
        state_tracker.clear_failure(source_dir)
    else:
        state_tracker.record_failure(source_dir, result.error)


def archive_recording(
    recording,
    formatter: MarkdownFormatter,
    git_manager: GitManager,
    state_tracker: StateTracker,
    dry_run: bool = False,
) -> ArchiveResult:
    logger = logging.getLogger(__name__)

    try:
        markdown = formatter.format_recording(recording)
        file_path = formatter.compute_file_path(recording)

        if dry_run:
            console.print(
                f"[yellow]DRY RUN: Would archive {recording.source_dir} to {file_path}[/yellow]"
            )
            return ArchiveResult(
                success=True, source_dir=recording.source_dir, file_path=file_path
            )

        dt = datetime.fromisoformat(recording.datetime)
        commit_message = (
            f"Archive: {recording.modeName} recording {dt.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Source: {recording.source_dir}\n"
            f"Duration: {recording.duration}ms\n"
        )
        commit_sha = git_manager.write_and_commit(file_path, markdown, commit_message)

        if not commit_sha:
            raise Exception("Failed to commit recording")

        state_tracker.mark_archived(
            source_dir=recording.source_dir,
            recording_datetime=recording.datetime,
            mode=recording.modeName,
            duration_ms=recording.duration,
            file_path=file_path,
            commit_sha=commit_sha,
        )

        logger.info(f"Archived {recording.source_dir} to {file_path}")
        return ArchiveResult(
            success=True,
            source_dir=recording.source_dir,
            file_path=file_path,
            commit_sha=commit_sha,
        )

    except Exception as e:
        logger.error(f"Failed to archive {recording.source_dir}: {e}", exc_info=True)
        return ArchiveResult(success=False, source_dir=recording.source_dir, error=str(e))


def run_archiver(
    config: ArchiverConfig,
    dry_run: bool = False,
    since_date: Optional[str] = None,
    modes_override: Optional[str] = None,
) -> ArchiveSummary:
    logger = logging.getLogger(__name__)
    logger.info("Starting archiver run")

    scanner = Scanner(config.superwhisper.recordings_path)
    state_tracker = StateTracker(str(default_state_db_path()))
    git_manager = GitManager(
        config.archive.repo_path,
        config.archive.remote_name,
        config.archive.default_branch,
    )
    formatter = MarkdownFormatter()

    if not dry_run:
        git_manager.ensure_up_to_date()

    filters = config.filters
    if modes_override:
        filters = filters.model_copy(update={"modes": modes_override.split(",")})

    # Every run scans everything. Deduplication is the archived set, never a
    # timestamp watermark: a recording that was mid-flight or that failed to
    # commit must remain visible to later runs.
    scan = scanner.scan(
        filters=filters,
        since=since_date,
        skip_source_dirs=state_tracker.get_archived_source_dirs(),
    )

    if scan.skipped_incomplete:
        logger.info(f"{scan.skipped_incomplete} recording(s) not yet finalised; will retry")

    results = []
    for rec in scan.recordings:
        result = archive_recording(rec, formatter, git_manager, state_tracker, dry_run)
        record_archive_outcome(state_tracker, rec.source_dir, result, dry_run)
        results.append(result)

    if not dry_run and any(r.success for r in results):
        git_manager.push_to_remote()

    archived_count = sum(1 for r in results if r.success)
    failed_count = sum(1 for r in results if not r.success)

    if not dry_run:
        state_tracker.update_last_run(
            recordings_processed=len(scan.recordings),
            recordings_archived=archived_count,
            recordings_failed=failed_count,
        )
        maybe_alert_failures(state_tracker)

    summary = ArchiveSummary(
        total_recordings=len(scan.recordings),
        archived_count=archived_count,
        failed_count=failed_count,
        skipped_count=scan.skipped_archived,
        results=results,
    )

    logger.info(
        f"Run complete: {summary.archived_count} archived, "
        f"{summary.failed_count} failed, {summary.skipped_count} already archived, "
        f"{scan.skipped_incomplete} in progress"
    )
    return summary


def print_summary(summary: ArchiveSummary):
    table = Table(title="Archive Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta")

    table.add_row("Eligible Recordings", str(summary.total_recordings))
    table.add_row("Archived", str(summary.archived_count))
    table.add_row("Failed", str(summary.failed_count))
    table.add_row("Already Archived", str(summary.skipped_count))

    console.print(table)

    if summary.failed_count > 0:
        console.print("\n[red]Failed:[/red]")
        for result in summary.results:
            if not result.success:
                console.print(f"  - {result.source_dir}: {result.error}")


def main():
    parser = argparse.ArgumentParser(
        description="Archive superwhisper recordings to a git repository"
    )
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be archived")
    parser.add_argument(
        "--since", type=str, help="Only consider recordings on or after this date (ISO format)"
    )
    parser.add_argument(
        "--modes", type=str, help="Override mode filter (comma-separated, e.g. meeting,super)"
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Deprecated and ignored: every run already scans all recordings",
    )

    args = parser.parse_args()

    try:
        config = load_config(args.config)
        setup_logging(config)
        if args.backfill:
            logging.getLogger(__name__).warning(
                "--backfill is deprecated and ignored; every run scans all recordings"
            )
        summary = run_archiver(
            config,
            dry_run=args.dry_run,
            since_date=args.since,
            modes_override=args.modes,
        )
        print_summary(summary)
        sys.exit(0 if summary.failed_count == 0 else 1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Fatal error: {e}[/red]")
        logging.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Main orchestrator for the superwhisper archiver."""

import argparse
import logging
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
from .state_tracker import StateTracker

console = Console()


def setup_logging(config: ArchiverConfig):
    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)
    log_file = Path(config.logging.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RichHandler(console=console, rich_tracebacks=True),
            logging.FileHandler(config.logging.file),
        ],
    )


def load_config(config_path: Optional[str] = None) -> ArchiverConfig:
    if config_path:
        path = Path(config_path)
    else:
        path = Path("config.yaml")

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    console.print(f"[dim]Using config: {path}[/dim]")
    with open(path, "r") as f:
        config_dict = yaml.safe_load(f)
    return ArchiverConfig(**config_dict)


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
            console.print(f"[yellow]DRY RUN: Would archive {recording.source_dir} to {file_path}[/yellow]")
            return ArchiveResult(success=True, source_dir=recording.source_dir, file_path=file_path)

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
    backfill: bool = False,
    since_date: Optional[str] = None,
    modes_override: Optional[str] = None,
) -> ArchiveSummary:
    logger = logging.getLogger(__name__)
    logger.info("Starting archiver run")

    scanner = Scanner(config.superwhisper.recordings_path)
    state_tracker = StateTracker("state/archive_state.db")
    git_manager = GitManager(
        config.archive.repo_path,
        config.archive.remote_name,
        config.archive.default_branch,
    )
    formatter = MarkdownFormatter()

    if not dry_run:
        git_manager.ensure_up_to_date()

    # Determine mode filter
    modes = modes_override.split(",") if modes_override else config.filters.modes

    # Determine since filter
    since = None
    if not backfill:
        if since_date:
            since = since_date
        else:
            last_run = state_tracker.get_last_run_timestamp()
            if last_run:
                since = last_run.isoformat()

    # Scan recordings
    recordings = scanner.scan(
        modes=modes if modes else None,
        min_duration_ms=config.filters.min_duration_ms,
        since=since,
    )

    # Filter already-archived
    results = []
    skipped_count = 0

    for rec in recordings:
        if state_tracker.is_archived(rec.source_dir):
            logger.info(f"Skipping {rec.source_dir} — already archived")
            skipped_count += 1
            continue

        result = archive_recording(rec, formatter, git_manager, state_tracker, dry_run)
        results.append(result)

    # Push
    if not dry_run and any(r.success for r in results):
        git_manager.push_to_remote()

    # Update run stats
    if not dry_run:
        archived_count = sum(1 for r in results if r.success)
        failed_count = sum(1 for r in results if not r.success)
        state_tracker.update_last_run(
            recordings_processed=len(recordings),
            recordings_archived=archived_count,
            recordings_failed=failed_count,
        )

    summary = ArchiveSummary(
        total_recordings=len(recordings),
        archived_count=sum(1 for r in results if r.success),
        failed_count=sum(1 for r in results if not r.success),
        skipped_count=skipped_count,
        results=results,
    )

    logger.info(
        f"Run complete: {summary.archived_count} archived, "
        f"{summary.failed_count} failed, {summary.skipped_count} skipped"
    )
    return summary


def print_summary(summary: ArchiveSummary):
    table = Table(title="Archive Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta")

    table.add_row("Total Recordings", str(summary.total_recordings))
    table.add_row("Archived", str(summary.archived_count))
    table.add_row("Failed", str(summary.failed_count))
    table.add_row("Skipped", str(summary.skipped_count))

    console.print(table)

    if summary.failed_count > 0:
        console.print("\n[red]Failed:[/red]")
        for result in summary.results:
            if not result.success:
                console.print(f"  - {result.source_dir}: {result.error}")


def main():
    parser = argparse.ArgumentParser(description="Archive superwhisper recordings to a git repository")
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be archived")
    parser.add_argument("--backfill", action="store_true", help="Archive ALL matching recordings")
    parser.add_argument("--since", type=str, help="Archive recordings since this date (ISO format)")
    parser.add_argument("--modes", type=str, help="Override mode filter (comma-separated, e.g. meeting,super)")

    args = parser.parse_args()

    try:
        config = load_config(args.config)
        setup_logging(config)
        summary = run_archiver(
            config,
            dry_run=args.dry_run,
            backfill=args.backfill,
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

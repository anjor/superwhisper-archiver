"""Formats superwhisper recordings as Markdown."""

from datetime import datetime
import logging

from .models import Recording

logger = logging.getLogger(__name__)


class MarkdownFormatter:
    """Formats superwhisper recordings as Markdown with YAML frontmatter."""

    def format_recording(self, recording: Recording) -> str:
        """Format a recording as Markdown.

        Args:
            recording: The Recording to format.

        Returns:
            Formatted Markdown string.
        """
        frontmatter = self._build_frontmatter(recording)
        body = self._build_body(recording)
        return frontmatter + body

    def _build_frontmatter(self, rec: Recording) -> str:
        parts = [
            "---",
            f'datetime: "{rec.datetime}"',
            f"mode: {rec.modeName}",
            f"duration_ms: {rec.duration}",
            f'model: "{rec.modelName}"',
        ]
        if rec.languageModelName:
            parts.append(f'language_model: "{rec.languageModelName}"')
        parts.extend([
            f"language: {rec.languageSelected}",
            f"system_audio: {str(rec.systemAudioEnabled).lower()}",
            f'app_version: "{rec.appVersion}"',
            f'source_dir: "{rec.source_dir}"',
            f'archived_at: "{datetime.now().isoformat()}"',
            "---",
        ])
        return "\n".join(parts) + "\n"

    def _build_body(self, rec: Recording) -> str:
        dt = datetime.fromisoformat(rec.datetime)
        duration_str = self._format_duration(rec.duration)

        parts = [
            f"\n# Recording — {dt.strftime('%Y-%m-%d %H:%M')}\n",
            f"**Mode**: {rec.modeName} | **Duration**: {duration_str}\n",
        ]

        # Transcription
        transcription = rec.result.strip() if rec.result else rec.rawResult.strip()
        if transcription:
            parts.append(f"## Transcription\n\n{transcription}\n")

        # LLM Summary (if present)
        if rec.llmResult:
            parts.append(f"## Summary\n\n{rec.llmResult}\n")

        # Segments
        if rec.segments:
            lines = []
            for seg in rec.segments:
                start = self._format_timestamp(seg.start)
                end = self._format_timestamp(seg.end)
                lines.append(f"- [{start} → {end}] {seg.text}")
            parts.append("## Segments\n\n" + "\n".join(lines) + "\n")

        # Footer
        parts.append(f"\n---\n*Archived: {datetime.now().strftime('%Y-%m-%d')}*\n")

        return "\n".join(parts)

    def compute_file_path(self, recording: Recording) -> str:
        """Compute the archive file path for a recording.

        Returns:
            Relative path like YYYY/MM/YYYY-MM-DD-HH-MM-SS.md
        """
        dt = datetime.fromisoformat(recording.datetime)
        year = dt.strftime("%Y")
        month = dt.strftime("%m")
        filename = dt.strftime("%Y-%m-%d-%H-%M-%S") + ".md"
        return f"{year}/{month}/{filename}"

    @staticmethod
    def _format_duration(duration_ms: int) -> str:
        total_seconds = duration_ms // 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds as MM:SS.s"""
        mins = int(seconds) // 60
        secs = seconds - (mins * 60)
        return f"{mins:02d}:{secs:04.1f}"

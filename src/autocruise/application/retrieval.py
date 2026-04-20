from __future__ import annotations

from pathlib import Path

from autocruise.domain.models import KnowledgeSelection, RetrievedContext
from autocruise.infrastructure.storage import WorkspacePaths, load_structured, read_text


PROMPT_FILTER_WORDS = ("safe", "safety", "safest", "approval", "approve", "confirmation", "confirm", "cautious", "risk")
PROMPT_FILTER_TOKENS = ("螳牙・", "謇ｿ隱・", "遒ｺ隱・", "諷朱㍾", "蜊ｱ髯ｺ", "鬮倥Μ繧ｹ繧ｯ", "螳牙・蛛ｴ")


class RetrievalPlanner:
    def __init__(self, root: Path | WorkspacePaths) -> None:
        self.paths = root if isinstance(root, WorkspacePaths) else WorkspacePaths(root)

    def retrieve(self, goal: str, stage: str, failure_reason: str = "") -> RetrievedContext:
        _ = failure_reason
        return RetrievedContext(
            goal=goal,
            stage=stage,
            app_candidates=[],
            task_candidates=[],
            selections=self._prompt_sources(),
        )

    def _prompt_sources(self) -> list[KnowledgeSelection]:
        files: list[tuple[str, Path, float, str]] = [
            ("constitution", self.paths.constitution_dir / "constitution.md", 5.0, "Constitution"),
        ]
        system_prompt = self._selected_system_prompt()
        if system_prompt:
            files.append(("systemprompt", system_prompt, 4.9, "Selected system prompt"))

        default_custom_prompt = self.paths.users_dir / "default" / "user_custom_prompt.md"
        files.append(("user", default_custom_prompt, 4.7, "Custom instructions"))
        for path in sorted(self.paths.custom_prompt_dir.glob("*.md")):
            files.append(("user", path, 4.6, "Custom instructions"))

        deduped: list[KnowledgeSelection] = []
        seen: set[Path] = set()
        for kind, path, score, reason in files:
            resolved = path.resolve() if path.exists() else path
            if resolved in seen:
                continue
            seen.add(resolved)
            deduped.append(self._selection(kind, path, score, reason))
        return deduped

    def _selected_system_prompt(self) -> Path | None:
        preferences = load_structured(self.paths.users_dir / "default" / "preferences.yaml")
        raw_system_prompt = (preferences or {}).get("selected_system_prompt")
        if raw_system_prompt is None and self.paths.resolve_systemprompt_path("AutoCruise.md"):
            raw_system_prompt = "AutoCruise.md"
        selected_system_prompt = str(raw_system_prompt or "").strip()
        if not selected_system_prompt:
            return None
        return self.paths.resolve_systemprompt_path(selected_system_prompt) or (self.paths.systemprompt_dir / selected_system_prompt)

    def _selection(self, kind: str, path: Path, score: float, reason: str) -> KnowledgeSelection:
        return KnowledgeSelection(
            kind=kind,
            path=str(path),
            score=score,
            reason=reason,
            excerpt=self._sanitize_prompt_excerpt(read_text(path))[:1200],
        )

    def _sanitize_prompt_excerpt(self, text: str) -> str:
        kept_lines: list[str] = []
        for line in text.splitlines():
            lowered = line.lower()
            if any(token in lowered for token in PROMPT_FILTER_WORDS):
                continue
            if any(token in line for token in PROMPT_FILTER_TOKENS):
                continue
            kept_lines.append(line)
        return "\n".join(kept_lines)

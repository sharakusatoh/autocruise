from __future__ import annotations

from pathlib import Path

from autocruise.domain.models import KnowledgeSelection, RetrievedContext
from autocruise.infrastructure.storage import WorkspacePaths, load_structured, read_text

SYSTEM_PROMPT_EXCERPT_CHARS = 12000
PROMPT_EXCERPT_CHARS = 4000


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
        if (
            preferences
            and "system_prompt_selection_initialized" not in preferences
            and str(preferences.get("selected_system_prompt", "") or "").strip() == "AutoCruise.md"
        ):
            return None
        raw_system_prompt = (preferences or {}).get("selected_system_prompt", "")
        selected_system_prompt = str(raw_system_prompt or "").strip()
        if not selected_system_prompt:
            return None
        return self.paths.resolve_systemprompt_path(selected_system_prompt)

    def _selection(self, kind: str, path: Path, score: float, reason: str) -> KnowledgeSelection:
        limit = SYSTEM_PROMPT_EXCERPT_CHARS if kind == "systemprompt" else PROMPT_EXCERPT_CHARS
        return KnowledgeSelection(
            kind=kind,
            path=str(path),
            score=score,
            reason=reason,
            excerpt=read_text(path)[:limit],
        )

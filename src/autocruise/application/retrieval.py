from __future__ import annotations

from pathlib import Path

from autocruise.domain.models import KnowledgeSelection, RetrievedContext
from autocruise.infrastructure.storage import WorkspacePaths, load_structured, read_jsonl, read_text


APP_KEYWORDS: dict[str, list[str]] = {
    "gimp": ["gimp", "image", "canvas", "layer", "export", "画像", "キャンバス", "ペイント"],
    "paint": ["paint", "mspaint", "drawing", "sketch", "line art", "ペイント", "線画", "スケッチ", "お絵描き"],
    "excel": ["excel", "spreadsheet", "workbook", "sheet", "cell", "filter", "エクセル", "表計算", "売上", "集計"],
    "word": ["word", "document", "docx", "proposal", "quote", "report", "文書", "ワード", "提案書", "見積書", "報告書"],
    "powerpoint": ["powerpoint", "ppt", "slides", "presentation", "deck", "パワポ", "スライド", "資料", "プレゼン"],
    "outlook": ["outlook", "mail", "email", "calendar", "meeting", "follow up", "メール", "予定表", "会議招待", "返信"],
    "teams": ["teams", "meeting", "chat", "call", "share screen", "チームズ", "会議", "チャット", "通話"],
    "chrome": ["chrome", "browser", "web", "tab", "page", "download", "ブラウザ", "web", "検索"],
    "edge": ["edge", "microsoft edge", "browser", "bing", "download", "edge", "ブラウザ"],
    "file_explorer": ["explorer", "file explorer", "folder", "desktop", "downloads", "rename", "zip", "move", "copy", "エクスプローラー", "フォルダ", "デスクトップ", "ダウンロード"],
    "acrobat": ["acrobat", "pdf", "annotation", "comment", "highlight", "merge pdf", "アクロバット", "pdf", "注釈", "コメント", "ハイライト"],
    "photoshop": ["photoshop", "psd", "photo", "retouch", "resize", "crop", "png", "jpeg", "フォトショップ", "画像編集", "写真", "切り抜き"],
    "illustrator": ["illustrator", "ai file", "vector", "artboard", "export asset", "svg", "イラストレーター", "ベクター", "アートボード", "ロゴ"],
    "vscode": ["vscode", "visual studio code", "editor", "source code", "log", "debug", "git diff", "コード", "ログ", "デバッグ"],
    "terminal": ["terminal", "powershell", "cmd", "console", "shell", "build", "test", "ターミナル", "powershell", "コマンド", "ビルド"],
    "codex_desktop": ["codex", "codex desktop", "workspace", "thread"],
    "claude_code_desktop": ["claude", "claude code", "conversation", "composer"],
    "windows_settings": ["settings", "windows setting", "system setting", "control panel", "設定", "windows 設定", "コントロールパネル"],
}

TASK_KEYWORDS: dict[str, list[str]] = {
    "sample_excel_cleanup": ["excel", "spreadsheet", "cleanup", "filter"],
    "paint_simple_line_drawing": ["paint", "mspaint", "draw", "drawing", "sketch", "cat", "line art", "ペイント", "描いて", "線画", "猫", "スケッチ"],
    "excel_sales_pipeline_update": ["excel", "sales", "pipeline", "forecast", "summary", "売上", "案件", "見込み", "集計"],
    "excel_invoice_reconciliation": ["excel", "invoice", "payment", "reconcile", "reconciliation", "billing", "請求", "入金", "照合", "消込"],
    "excel_monthly_chart_update": ["excel", "chart", "graph", "monthly", "trend", "dashboard", "グラフ", "月次", "推移", "ダッシュボード"],
    "word_customer_quote": ["word", "proposal", "quote", "quotation", "document", "見積書", "提案書", "ワード"],
    "word_meeting_minutes_cleanup": ["word", "minutes", "meeting notes", "document", "議事録", "会議メモ", "整形"],
    "word_contract_redline_review": ["word", "contract", "redline", "track changes", "agreement", "契約書", "校正", "コメント", "変更履歴"],
    "powerpoint_weekly_update": ["powerpoint", "slides", "presentation", "deck", "weekly report", "monthly report", "パワポ", "スライド", "資料", "報告"],
    "powerpoint_customer_pitch_update": ["powerpoint", "pitch", "customer presentation", "proposal slides", "営業資料", "提案資料", "パワポ", "スライド"],
    "outlook_follow_up_email": ["outlook", "follow up", "follow-up", "email", "mail", "reply", "メール", "返信", "フォローアップ"],
    "outlook_meeting_invite": ["outlook", "meeting invite", "calendar", "schedule", "appointment", "会議招待", "予定表", "日程調整"],
    "outlook_inbox_triage": ["outlook", "inbox", "triage", "mailbox", "flag", "folder", "受信トレイ", "メール整理", "仕分け", "フラグ"],
    "outlook_meeting_reschedule": ["outlook", "reschedule", "calendar", "meeting", "postpone", "会議変更", "日程変更", "予定変更"],
    "teams_meeting_notes": ["teams", "meeting notes", "minutes", "chat summary", "会議メモ", "議事録", "チームズ"],
    "teams_followup_summary": ["teams", "follow up", "chat summary", "task list", "フォローアップ", "会議要約", "宿題", "teams"],
    "browser_market_research": ["browser", "chrome", "edge", "research", "competitor", "market", "market research", "市場調査", "競合", "web調査"],
    "browser_crm_update": ["browser", "crm", "salesforce", "hubspot", "sfa", "customer note", "顧客管理", "salesforce", "hubspot", "crm更新"],
    "browser_expense_report_submission": ["browser", "expense", "receipt", "submit", "expense system", "経費", "精算", "申請", "領収書"],
    "browser_portal_download_and_archive": ["browser", "portal", "download", "archive", "report download", "ポータル", "ダウンロード", "保存", "アーカイブ"],
    "browser_support_ticket_update": ["browser", "support ticket", "jira", "zendesk", "service desk", "incident", "チケット", "問い合わせ", "障害票", "jira"],
    "file_cleanup_desktop": ["desktop", "downloads", "cleanup", "organize files", "sort files", "デスクトップ整理", "ダウンロード整理", "ファイル整理"],
    "file_rename_and_archive": ["rename files", "archive", "zip", "folder structure", "batch rename", "リネーム", "アーカイブ", "zip", "整理"],
    "file_project_folder_setup": ["folder setup", "project folder", "template folder", "shared folder", "フォルダ作成", "案件フォルダ", "フォルダ構成"],
    "pdf_review_and_annotation": ["pdf", "acrobat", "comment", "highlight", "review", "annotation", "注釈", "コメント", "ハイライト", "pdfレビュー"],
    "pdf_merge_and_bookmark": ["pdf", "merge", "bookmark", "combine", "table of contents", "pdf結合", "しおり", "結合", "ブックマーク"],
    "photoshop_resize_and_export": ["photoshop", "resize", "crop", "export png", "web image", "画像サイズ変更", "切り抜き", "書き出し"],
    "photoshop_banner_text_update": ["photoshop", "banner", "text", "headline", "promo image", "バナー", "テキスト差し替え", "見出し", "画像編集"],
    "illustrator_simple_export": ["illustrator", "export asset", "banner", "vector", "svg", "logo", "アセット書き出し", "バナー", "ロゴ"],
    "vscode_log_triage": ["vscode", "log", "stack trace", "error", "debug", "source code", "ログ調査", "例外", "デバッグ"],
    "vscode_search_replace_review": ["vscode", "search replace", "replace all", "refactor text", "コード置換", "一括置換", "検索置換"],
    "terminal_build_and_diagnostics": ["terminal", "powershell", "cmd", "build", "test", "diagnostic", "logs", "コマンド", "ビルド", "テスト", "診断"],
    "terminal_git_status_and_tests": ["terminal", "git", "status", "tests", "pytest", "build", "git status", "コミット前", "テスト実行"],
}

PROMPT_FILTER_WORDS = ("safe", "safety", "safest", "approval", "approve", "confirmation", "confirm", "cautious", "risk")
PROMPT_FILTER_TOKENS = ("安全", "承認", "確認", "慎重", "危険", "高リスク", "安全側")


class RetrievalPlanner:
    def __init__(self, root: Path | WorkspacePaths) -> None:
        self.paths = root if isinstance(root, WorkspacePaths) else WorkspacePaths(root)

    def retrieve(self, goal: str, stage: str, failure_reason: str = "") -> RetrievedContext:
        normalized = f"{goal} {failure_reason}".lower()
        app_candidates = self._match_candidates(APP_KEYWORDS, normalized)
        task_candidates = self._match_candidates(TASK_KEYWORDS, normalized)

        selections: list[KnowledgeSelection] = []
        selections.extend(self._always_include(stage))

        for app_name in app_candidates:
            selections.extend(self._score_app(app_name, normalized, stage))

        for task_name in task_candidates:
            selections.extend(self._score_task(task_name, normalized, stage))

        if not app_candidates:
            for app_name in ("excel", "chrome"):
                selections.extend(self._score_app(app_name, normalized, stage, base_score=0.8))

        selections.sort(key=lambda item: item.score, reverse=True)
        deduped: list[KnowledgeSelection] = []
        seen: set[str] = set()
        for selection in selections:
            if selection.path in seen:
                continue
            seen.add(selection.path)
            deduped.append(selection)

        return RetrievedContext(
            goal=goal,
            stage=stage,
            app_candidates=app_candidates,
            task_candidates=task_candidates,
            selections=deduped[:12],
        )

    def _match_candidates(self, catalogue: dict[str, list[str]], normalized: str) -> list[str]:
        matches: list[tuple[int, str]] = []
        for name, keywords in catalogue.items():
            score = sum(1 for keyword in keywords if keyword in normalized)
            if score:
                matches.append((score, name))
        matches.sort(reverse=True)
        return [name for _, name in matches]

    def _always_include(self, stage: str) -> list[KnowledgeSelection]:
        files = [
            ("constitution", self.paths.constitution_dir / "constitution.md", 5.0, "Base execution guide"),
            ("user", self.paths.users_dir / "default" / "user_custom_prompt.md", 4.5, "User preference prompt"),
            ("user", self.paths.users_dir / "default" / "preferences.yaml", 4.4, "User preferences"),
        ]
        preferences = load_structured(self.paths.users_dir / "default" / "preferences.yaml")
        selected_system_prompt = str((preferences or {}).get("selected_system_prompt", "")).strip()
        if selected_system_prompt:
            selected_path = self.paths.resolve_systemprompt_path(selected_system_prompt)
            files.append(
                (
                    "systemprompt",
                    selected_path or (self.paths.systemprompt_dir / selected_system_prompt),
                    4.8,
                    "Selected system prompt",
                )
            )
        if stage == "replan":
            files.append(("log", self.paths.logs_dir / "execution_log.jsonl", 4.2, "Recent execution context for replanning"))
        return [self._selection(kind, path, score, reason) for kind, path, score, reason in files]

    def _score_app(
        self,
        app_name: str,
        normalized: str,
        stage: str,
        base_score: float = 3.0,
    ) -> list[KnowledgeSelection]:
        app_dir = self.paths.apps_dir / app_name
        profile = app_dir / "app_profile.md"
        memory = app_dir / "app_memory.jsonl"
        score = base_score + sum(0.3 for keyword in APP_KEYWORDS.get(app_name, []) if keyword in normalized)
        if stage == "replan":
            score += 0.6
        return [
            self._selection("app_profile", profile, score + 0.4, f"Matched app profile for {app_name}"),
            self._selection("app_memory", memory, score, f"Matched app memory for {app_name}"),
        ]

    def _score_task(self, task_name: str, normalized: str, stage: str) -> list[KnowledgeSelection]:
        task_dir = self.paths.tasks_dir / task_name
        recipe = task_dir / "task_recipe.md"
        memory = task_dir / "task_memory.jsonl"
        score = 3.5 + sum(0.4 for keyword in TASK_KEYWORDS.get(task_name, []) if keyword in normalized)
        if stage == "replan":
            score += 0.5
        return [
            self._selection("task_recipe", recipe, score + 0.3, f"Matched task recipe for {task_name}"),
            self._selection("task_memory", memory, score, f"Matched task memory for {task_name}"),
        ]

    def _selection(self, kind: str, path: Path, score: float, reason: str) -> KnowledgeSelection:
        excerpt = ""
        if path.suffix == ".jsonl":
            records = read_jsonl(path, limit=3)
            excerpt = "\n".join(str(record) for record in records)
        else:
            excerpt = self._sanitize_prompt_excerpt(read_text(path))[:1200]
        return KnowledgeSelection(
            kind=kind,
            path=str(path),
            score=score,
            reason=reason,
            excerpt=excerpt,
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

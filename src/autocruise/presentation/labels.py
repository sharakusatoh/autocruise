from __future__ import annotations

from autocruise.domain.models import SessionState


_LOCALE = "en"


TEXTS = {
    "en": {
        "app.tagline": "Autonomous Windows operator",
        "app.home_title": "AutoCruise CE",
        "app.home_subtitle": "Enter a goal to start.",
        "tab.home": "Home",
        "tab.history": "Threads",
        "tab.schedules": "Schedules",
        "tab.knowledge": "Knowledge",
        "tab.settings": "Settings",
        "sidebar.new_thread": "New thread",
        "language.english": "English",
        "language.japanese": "Japanese",
        "status.ready": "Ready",
        "status.loading": "Preparing",
        "status.observing": "Checking screen",
        "status.planning": "Choosing next action",
        "status.precheck": "Checking before action",
        "status.executing": "Running",
        "status.postcheck": "Checking result",
        "status.replanning": "Replanning",
        "status.paused": "Paused",
        "status.stopped": "Stopped",
        "status.failed": "Stopped by issue",
        "status.completed": "Done",
        "flow.loading": "Load context",
        "flow.observing": "Check screen",
        "flow.planning": "Next action",
        "flow.precheck": "Check before action",
        "flow.executing": "Run action",
        "flow.postcheck": "Check result",
        "flow.replanning": "Replan",
        "flow.paused": "Paused",
        "flow.stopped": "Stopped",
        "flow.failed": "Failed",
        "flow.completed": "Completed",
        "result.success": "Success",
        "result.failed": "Failed",
        "result.stopped": "Stopped",
        "result.skipped": "Skipped",
        "knowledge.constitution": "Core rules",
        "knowledge.systemprompt": "System prompt",
        "knowledge.user": "Custom instructions",
        "app.windows_settings": "Windows Settings",
        "app.general": "General",
        "message.provider": "Codex is not ready. Open Settings and sign in with ChatGPT.",
        "message.validation_failed": "The result could not be confirmed.",
        "message.timeout": "The action took too long.",
        "message.transition": "The run stopped because the internal flow became invalid.",
        "message.no_history": "No threads yet. Recent runs will appear here.",
        "message.no_selection": "Select an item to see details.",
        "message.home_empty": "Enter a goal and start. AutoCruise CE continues until it finishes or stops.",
        "message.phase_loading": "Loading the right context for this goal.",
        "message.phase_observing": "Checking what is visible on screen.",
        "message.phase_planning": "Preparing the next action.",
        "message.phase_precheck": "Confirming the target before execution.",
        "message.phase_executing": "Running the next action on the desktop.",
        "message.phase_postcheck": "Checking the result after the action.",
        "message.phase_replanning": "Adjusting the plan after the last step.",
        "message.phase_paused": "The run is paused.",
        "message.phase_stopped": "The run was stopped.",
        "message.phase_failed": "The run stopped because of an issue.",
        "message.phase_completed": "The goal was completed.",
        "message.goal_idle": "Your current goal appears here.",
        "message.background_mode": "After Run, AutoCruise CE moves to the background.",
        "message.tray_running": "AutoCruise CE is running in the background.",
        "message.tray_ready": "AutoCruise CE is ready.",
        "message.connection_ready": "Codex connected",
        "message.connection_fallback": "Codex is not ready yet",
        "message.connection_test_ok": "Connection confirmed. Text and screenshot input are available.",
        "message.running": "AutoCruise CE is working. You can pause or stop at any time.",
        "message.already_running": "A run is already in progress.",
        "message.need_instruction": "Enter a goal first.",
        "message.run_internal_error": "The run stopped because AutoCruise CE encountered an internal error.",
        "message.codex_sign_in_required": "Sign in with ChatGPT in Settings before starting a run.",
        "message.codex_browser_opened": "The ChatGPT sign-in page was opened in your browser. Finish sign-in, then return to AutoCruise CE.",
        "message.codex_signed_out": "Signed out from Codex.",
        "message.codex_refresh_failed": "Codex status could not be refreshed.",
        "message.codex_cli_missing": "Codex App Server is unavailable. Install or update Codex CLI with npm and try again.",
        "message.codex_cached_session": "Stored ChatGPT session detected. AutoCruise CE will confirm the active account when Settings opens.",
        "message.settings_saved": "Settings saved.",
        "message.thread_deleted": "Thread deleted.",
        "message.thread_delete_failed": "The thread could not be deleted.",
        "message.screenshots_purged": "Old screenshots removed: {count}",
        "message.moved_to_tray": "AutoCruise CE moved to the background. Use the floating controls or tray icon to pause or stop.",
        "message.moved_to_tray_shortcuts": "AutoCruise CE moved to the background. Pause: {pause}. Stop: {stop}.",
        "message.manager_subtitle": "Knowledge, threads, settings, and diagnostics.",
        "message.custom_prompt_subtitle": "Custom instructions loaded with the constitution and system prompt.",
        "message.schedule_saved": "Schedule saved.",
        "message.schedule_deleted": "Schedule deleted.",
        "message.schedule_scheduler_error": "Windows Task Scheduler could not be updated.",
        "message.schedule_missing_instruction": "Enter a goal for the scheduled run.",
        "message.schedule_future_required": "Choose a future date and time.",
        "message.schedule_disabled": "The schedule is disabled.",
        "message.schedule_locked": "The screen was locked, so the run was skipped.",
        "message.schedule_queued": "A scheduled run was queued in the current AutoCruise session.",
        "message.schedule_not_found": "The scheduled task could not be found.",
        "message.schedule_stopped_by_user": "The scheduled run was stopped by the user.",
        "message.hotkeys_partial": "Some shortcuts could not be registered because another app is already using them: {shortcuts}",
        "message.fatal_error": "AutoCruise CE encountered an unexpected error. Details were saved to {path}.",
        "button.run": "Run",
        "button.pause": "Pause",
        "button.resume": "Resume",
        "button.stop": "Stop",
        "button.allow": "Allow",
        "button.cancel": "Cancel",
        "button.refresh": "Refresh",
        "button.details": "Details",
        "button.delete_thread": "Delete thread",
        "button.test": "Test connection",
        "button.new": "New",
        "button.edit": "Edit",
        "button.sign_in": "Sign in with ChatGPT",
        "button.sign_out": "Sign out",
        "button.refresh_status": "Refresh status",
        "button.save": "Save",
        "button.cleanup": "Delete screenshots",
        "button.manage": "Manage",
        "button.open": "Open",
        "button.open_folder": "Open folder",
        "button.open_screenshots": "Open screenshots folder",
        "button.close": "Close",
        "schedule.title": "Schedules",
        "schedule.subtitle": "Create one-time or repeating runs.",
        "schedule.editor_title": "Scheduled job",
        "schedule.editor_subtitle": "Windows Task Scheduler starts AutoCruise with the saved task ID.",
        "schedule.new": "New schedule",
        "schedule.enable": "Enable",
        "schedule.disable": "Disable",
        "schedule.delete": "Delete",
        "schedule.recurrence": "Repeat",
        "schedule.date_time": "Date and time",
        "schedule.time": "Time",
        "schedule.weekday": "Weekday",
        "schedule.once": "Once",
        "schedule.daily": "Daily",
        "schedule.weekly": "Weekly",
        "schedule.weekdays": "Weekdays",
        "schedule.interval": "Every fixed interval",
        "schedule.interval_hours": "hours",
        "schedule.interval_minutes": "minutes",
        "schedule.random_hourly": "Once per hour at random",
        "schedule.random_daily": "Random times per day",
        "schedule.random_runs_per_day": "Runs per day",
        "schedule.random_daily_summary": "Random - {count} times per day",
        "schedule.empty": "No recent result",
        "schedule.state.scheduled": "Scheduled",
        "schedule.state.running": "Running",
        "schedule.state.completed": "Completed",
        "schedule.state.failed": "Failed",
        "schedule.state.skipped": "Skipped",
        "weekday.monday": "Monday",
        "weekday.tuesday": "Tuesday",
        "weekday.wednesday": "Wednesday",
        "weekday.thursday": "Thursday",
        "weekday.friday": "Friday",
        "weekday.saturday": "Saturday",
        "weekday.sunday": "Sunday",
        "label.current_state": "Current status",
        "label.current_goal": "Current goal",
        "label.current_activity": "What AutoCruise is doing",
        "label.goal": "Goal",
        "label.history_summary": "Run details",
        "label.saved_captures": "Saved captures",
        "label.knowledge_summary": "Item details",
        "label.language": "Language",
        "label.autonomy": "Autonomy",
        "label.pause_hotkey": "Pause shortcut",
        "label.stop_hotkey": "Stop shortcut",
        "label.general": "General",
        "label.ai_connection": "Codex Connection",
        "label.storage": "Storage",
        "label.provider": "Provider",
        "label.codex_runtime": "Runtime",
        "label.codex_auth_status": "Authentication",
        "label.codex_account": "Account",
        "label.model": "Model",
        "label.reasoning_effort": "Reasoning effort",
        "label.service_tier": "Inference speed",
        "label.max_tokens": "Max output tokens",
        "label.response_size": "Planning response size",
        "label.system_prompt": "System prompt",
        "label.screenshot_ttl": "Screenshot retention (days)",
        "label.keep_important_screenshots": "Important screenshot retention (days)",
        "label.history_limit": "History items",
        "label.execution_time": "Time",
        "label.instruction": "Goal",
        "label.result": "Result",
        "label.steps": "Steps",
        "label.target": "Target",
        "label.kind": "Type",
        "label.enabled": "Status",
        "label.prompt_hint": "Examples: Open Excel and create a new sheet. / Resize an image in GIMP.",
        "value.enabled": "Enabled",
        "value.configured": "Configured",
        "value.not_configured": "Not configured",
        "value.active": "Active",
        "value.none": "None",
        "value.unlimited": "Unlimited",
        "value.chatgpt_signed_in": "Signed in with ChatGPT",
        "value.chatgpt_managed_session": "ChatGPT managed session",
        "value.autonomy_balanced": "Balanced",
        "value.autonomy_autonomous": "Autonomous progress",
        "value.effort_none": "Fastest",
        "value.effort_minimal": "Light",
        "value.effort_low": "Low",
        "value.effort_medium": "Medium",
        "value.effort_high": "High",
        "value.effort_xhigh": "Extra high",
        "value.service_tier_auto": "Standard",
        "value.service_tier_fast": "Fast",
        "value.response_size_compact": "Compact (1024)",
        "value.response_size_standard": "Standard (2048, recommended)",
        "value.response_size_detailed": "Detailed (3072)",
        "value.response_size_max": "Maximum (4096)",
        "value.response_size_custom": "Custom ({value})",
        "value.shortcut_disabled": "Disabled",
        "message.service_tier_hint": "Standard is the normal tier. Fast appears only on supported models and prioritizes lower latency.",
        "message.response_size_hint": "Use Standard (2048) in most cases. Switch to Detailed only if plans are being cut off.",
        "history.flow": "Flow",
        "history.confirmations": "Important notes",
        "history.failure_reason": "Failure reason",
        "history.used_context": "Loaded prompt files",
        "window.details": "Details",
        "window.diagnostics": "Diagnostics",
        "window.management": "Management",
        "settings.general_subtitle": "Language, autonomy, and shortcuts",
        "settings.ai_subtitle": "Use Codex App Server with ChatGPT sign-in.",
        "settings.storage_subtitle": "Control retention and history size",
        "tray.show_main": "Open AutoCruise CE",
        "tray.show_manager": "Open Management",
        "tray.show_controls": "Show controls",
        "tray.pause": "Pause",
        "tray.resume": "Resume",
        "tray.stop": "Stop",
        "tray.quit": "Quit",
        "demo.goal": "Open Excel, create a new sheet, and prepare a clean workspace.",
        "demo.status_hint": "The agent is observing the desktop and preparing the next action.",
        "demo.next_action": "Focus the Excel window and open a blank workbook.",
        "demo.secondary_goal": "Open Settings and check Bluetooth status.",
        "empty.session_title": "No preview yet",
        "empty.session_subtitle": "Saved captures will appear here after AutoCruise completes a run or stores a high-priority checkpoint.",
    },
    "ja": {
        "app.tagline": "Windows を自律操作する AI オペレーター",
        "app.home_title": "AutoCruise CE",
        "app.home_subtitle": "指示を入力して開始します。",
        "tab.home": "ホーム",
        "tab.history": "スレッド",
        "tab.schedules": "スケジュール",
        "tab.knowledge": "ナレッジ",
        "tab.settings": "設定",
        "sidebar.new_thread": "新しいスレッド",
        "language.english": "英語",
        "language.japanese": "日本語",
        "status.ready": "待機中",
        "status.loading": "準備中",
        "status.observing": "画面を確認中",
        "status.planning": "次の操作を検討中",
        "status.precheck": "操作前を確認中",
        "status.executing": "実行中",
        "status.postcheck": "結果を確認中",
        "status.replanning": "再計画中",
        "status.paused": "一時停止中",
        "status.stopped": "停止",
        "status.failed": "問題により停止",
        "status.completed": "完了",
        "flow.loading": "文脈を読み込み",
        "flow.observing": "画面確認",
        "flow.planning": "次の操作",
        "flow.precheck": "実行前確認",
        "flow.executing": "操作実行",
        "flow.postcheck": "結果確認",
        "flow.replanning": "再計画",
        "flow.paused": "一時停止",
        "flow.stopped": "停止",
        "flow.failed": "失敗",
        "flow.completed": "完了",
        "result.success": "成功",
        "result.failed": "失敗",
        "result.stopped": "停止",
        "result.skipped": "スキップ",
        "knowledge.constitution": "基本ルール",
        "knowledge.systemprompt": "システムプロンプト",
        "knowledge.user": "カスタムプロンプト",
        "app.windows_settings": "Windows 設定",
        "app.general": "一般",
        "message.provider": "Codex が利用できません。設定で ChatGPT にサインインしてください。",
        "message.validation_failed": "結果を確認できませんでした。",
        "message.timeout": "操作がタイムアウトしました。",
        "message.transition": "内部状態の遷移に失敗したため停止しました。",
        "message.no_history": "まだ履歴はありません。実行するとここに表示されます。",
        "message.no_selection": "項目を選ぶと詳細を表示します。",
        "message.home_empty": "指示を入力して開始してください。AutoCruise CE は完了するか停止するまで続行します。",
        "message.phase_loading": "この目標に必要な文脈を読み込んでいます。",
        "message.phase_observing": "画面に見えている内容を確認しています。",
        "message.phase_planning": "次の操作を準備しています。",
        "message.phase_precheck": "実行前に対象を確認しています。",
        "message.phase_executing": "次の操作をデスクトップで実行しています。",
        "message.phase_postcheck": "操作後の結果を確認しています。",
        "message.phase_replanning": "直前の結果を踏まえて計画を調整しています。",
        "message.phase_paused": "実行は一時停止中です。",
        "message.phase_stopped": "実行は停止しました。",
        "message.phase_failed": "問題が発生したため実行を停止しました。",
        "message.phase_completed": "目標を完了しました。",
        "message.goal_idle": "現在の指示がここに表示されます。",
        "message.background_mode": "実行後はバックグラウンド動作に移ります。",
        "message.tray_running": "AutoCruise CE はバックグラウンドで動作中です。",
        "message.tray_ready": "AutoCruise CE は待機中です。",
        "message.connection_ready": "Codex に接続済み",
        "message.connection_fallback": "Codex の準備ができていません",
        "message.connection_test_ok": "接続を確認しました。テキストとスクリーンショット入力を利用できます。",
        "message.running": "AutoCruise CE が作業中です。いつでも一時停止または停止できます。",
        "message.already_running": "すでに実行中です。",
        "message.need_instruction": "先に指示を入力してください。",
        "message.run_internal_error": "AutoCruise CE の内部エラーにより停止しました。",
        "message.codex_sign_in_required": "実行前に設定で ChatGPT にサインインしてください。",
        "message.codex_browser_opened": "ブラウザーで ChatGPT のサインイン画面を開きました。サインイン後に AutoCruise CE へ戻ってください。",
        "message.codex_signed_out": "Codex からサインアウトしました。",
        "message.codex_refresh_failed": "Codex の状態を更新できませんでした。",
        "message.codex_cli_missing": "Codex App Server が利用できません。Codex CLI をインストールまたは更新してから再試行してください。",
        "message.codex_cached_session": "保存済みの ChatGPT セッションがあります。設定画面を開くと AutoCruise CE が現在のアカウントを確認します。",
        "message.settings_saved": "設定を保存しました。",
        "message.thread_deleted": "スレッドを削除しました。",
        "message.thread_delete_failed": "スレッドを削除できませんでした。",
        "message.screenshots_purged": "古いスクリーンショットを削除しました: {count}",
        "message.moved_to_tray": "AutoCruise CE をバックグラウンドに移しました。フローティング操作パネルまたはトレイアイコンから一時停止・停止できます。",
        "message.moved_to_tray_shortcuts": "AutoCruise CE をバックグラウンドに移しました。一時停止: {pause}。停止: {stop}。",
        "message.manager_subtitle": "ナレッジ、スレッド、設定、診断を管理します。",
        "message.schedule_saved": "スケジュールを保存しました。",
        "message.schedule_deleted": "スケジュールを削除しました。",
        "message.schedule_scheduler_error": "Windows タスク スケジューラを更新できませんでした。",
        "message.schedule_missing_instruction": "スケジュール実行する指示を入力してください。",
        "message.schedule_future_required": "未来の日時を指定してください。",
        "message.schedule_disabled": "このスケジュールは無効です。",
        "message.schedule_locked": "画面がロックされていたため、この実行はスキップされました。",
        "message.schedule_queued": "現在の AutoCruise セッションにスケジュール実行を追加しました。",
        "message.schedule_not_found": "指定したスケジュールが見つかりませんでした。",
        "message.schedule_stopped_by_user": "ユーザー操作によりスケジュール実行を停止しました。",
        "message.hotkeys_partial": "他のアプリが使用中のため、一部ショートカットを登録できませんでした: {shortcuts}",
        "message.fatal_error": "AutoCruise CE で予期しないエラーが発生しました。詳細は {path} に保存しました。",
        "button.run": "Run",
        "button.pause": "一時停止",
        "button.resume": "再開",
        "button.stop": "停止",
        "button.allow": "許可",
        "button.cancel": "キャンセル",
        "button.refresh": "更新",
        "button.details": "詳細",
        "button.delete_thread": "スレッドを削除",
        "button.test": "接続テスト",
        "button.new": "新規作成",
        "button.edit": "編集",
        "button.sign_in": "ChatGPT でサインイン",
        "button.sign_out": "サインアウト",
        "button.refresh_status": "状態を更新",
        "button.save": "保存",
        "button.cleanup": "スクリーンショットを削除",
        "button.manage": "管理",
        "button.open": "開く",
        "button.open_folder": "フォルダを開く",
        "button.open_screenshots": "スクリーンショットの保存先を開く",
        "button.close": "閉じる",
        "schedule.title": "スケジュール",
        "schedule.subtitle": "単発または繰り返しの実行を作成します。",
        "schedule.editor_title": "スケジュール実行",
        "schedule.editor_subtitle": "Windows タスク スケジューラが保存済みタスク ID で AutoCruise を起動します。",
        "schedule.new": "新規スケジュール",
        "schedule.enable": "有効化",
        "schedule.disable": "無効化",
        "schedule.delete": "削除",
        "schedule.recurrence": "繰り返し",
        "schedule.date_time": "日時",
        "schedule.time": "時刻",
        "schedule.weekday": "曜日",
        "schedule.once": "1回のみ",
        "schedule.daily": "毎日",
        "schedule.weekly": "毎週",
        "schedule.weekdays": "平日",
        "schedule.interval": "一定間隔",
        "schedule.interval_hours": "時間",
        "schedule.interval_minutes": "分",
        "schedule.random_hourly": "1時間に1回ランダム",
        "schedule.random_daily": "ランダム実行",
        "schedule.random_runs_per_day": "1日あたりの実行回数",
        "schedule.random_daily_summary": "ランダム - 1日 {count} 回",
        "schedule.empty": "最近の結果はありません",
        "schedule.state.scheduled": "予定",
        "schedule.state.running": "実行中",
        "schedule.state.completed": "完了",
        "schedule.state.failed": "失敗",
        "schedule.state.skipped": "スキップ",
        "weekday.monday": "月曜",
        "weekday.tuesday": "火曜",
        "weekday.wednesday": "水曜",
        "weekday.thursday": "木曜",
        "weekday.friday": "金曜",
        "weekday.saturday": "土曜",
        "weekday.sunday": "日曜",
        "label.current_state": "現在の状態",
        "label.current_goal": "現在の指示",
        "label.current_activity": "現在の動作",
        "label.goal": "指示",
        "label.history_summary": "実行詳細",
        "label.saved_captures": "保存済みキャプチャ",
        "label.knowledge_summary": "項目詳細",
        "label.language": "表示言語",
        "label.autonomy": "自律実行",
        "label.pause_hotkey": "一時停止ショートカット",
        "label.stop_hotkey": "停止ショートカット",
        "label.general": "一般",
        "label.ai_connection": "Codex 接続",
        "label.storage": "保存領域",
        "label.provider": "プロバイダー",
        "label.codex_runtime": "ランタイム",
        "label.codex_auth_status": "認証",
        "label.codex_account": "アカウント",
        "label.model": "モデル",
        "label.reasoning_effort": "推論強度",
        "label.service_tier": "推論速度",
        "label.max_tokens": "最大出力トークン",
        "label.response_size": "計画応答の長さ",
        "label.system_prompt": "システムプロンプト",
        "label.screenshot_ttl": "スクリーンショット保持日数",
        "label.keep_important_screenshots": "重要スクリーンショット保持日数",
        "label.history_limit": "履歴件数",
        "label.execution_time": "時間",
        "label.instruction": "指示",
        "label.result": "結果",
        "label.steps": "ステップ数",
        "label.target": "対象",
        "label.kind": "種類",
        "label.enabled": "状態",
        "label.prompt_hint": "例: Excel を開いて新しいシートを作成。 / GIMP で画像サイズを変更。",
        "value.enabled": "有効",
        "value.configured": "設定済み",
        "value.not_configured": "未設定",
        "value.active": "有効",
        "value.none": "なし",
        "value.unlimited": "無制限",
        "value.chatgpt_signed_in": "ChatGPT でサインイン済み",
        "value.chatgpt_managed_session": "ChatGPT 管理セッション",
        "value.autonomy_balanced": "標準",
        "value.autonomy_autonomous": "自律進行優先",
        "value.effort_none": "最速",
        "value.effort_minimal": "軽め",
        "value.effort_low": "低",
        "value.effort_medium": "中",
        "value.effort_high": "高",
        "value.effort_xhigh": "最高",
        "value.service_tier_auto": "標準",
        "value.service_tier_fast": "高速",
        "value.response_size_compact": "コンパクト (1024)",
        "value.response_size_standard": "標準 (2048・推奨)",
        "value.response_size_detailed": "詳細 (3072)",
        "value.response_size_max": "最大 (4096)",
        "value.response_size_custom": "カスタム ({value})",
        "value.shortcut_disabled": "無効",
        "message.service_tier_hint": "標準が通常モードです。高速は対応モデルでのみ選べ、待ち時間を短くしやすくなります。",
        "message.response_size_hint": "通常は標準 (2048) を推奨します。計画が途中で切れるときだけ詳細へ上げてください。",
        "history.flow": "フロー",
        "history.confirmations": "重要メモ",
        "history.failure_reason": "失敗理由",
        "history.used_context": "読み込んだプロンプト",
        "window.details": "詳細",
        "window.diagnostics": "診断",
        "window.management": "管理",
        "settings.general_subtitle": "表示言語、自律度、ショートカットを設定します",
        "settings.ai_subtitle": "Codex App Server と ChatGPT サインインを使用します。",
        "settings.storage_subtitle": "保持期間と履歴件数を設定します",
        "tray.show_main": "AutoCruise CE を開く",
        "tray.show_manager": "管理画面を開く",
        "tray.show_controls": "操作パネルを表示",
        "tray.pause": "一時停止",
        "tray.resume": "再開",
        "tray.stop": "停止",
        "tray.quit": "終了",
        "demo.goal": "Excel を開いて新しいシートを作成し、作業しやすい状態に整える。",
        "demo.status_hint": "エージェントが画面を観察し、次の操作を準備しています。",
        "demo.next_action": "Excel ウィンドウを前面に出し、空のブックを開く。",
        "empty.session_title": "まだプレビューはありません",
        "empty.session_subtitle": "実行完了時または高優先度チェックポイント保存時にキャプチャがここへ表示されます。",
    },
}

TEXTS["ja"].update(
    {
        "button.run": "実行",
        "label.current_state": "現在の状態",
        "label.current_goal": "現在の目標",
        "label.goal": "目標",
        "sidebar.new_thread": "新しいスレッド",
    }
)

TEXTS["en"].update(
    {
        "label.current_state": "Current status",
    }
)

TEXTS["ja"]["demo.secondary_goal"] = "設定を開いて Bluetooth の状態を確認する。"


TEXTS["ja"]["history.used_context"] = "読み込んだプロンプト"
TEXTS["ja"]["message.custom_prompt_subtitle"] = "constitution、systemprompt と一緒に読み込むカスタム指示です。"


STATE_KEYS = {
    SessionState.IDLE.value: "status.ready",
    SessionState.LOADING_CONTEXT.value: "status.loading",
    SessionState.OBSERVING.value: "status.observing",
    SessionState.PLANNING.value: "status.planning",
    SessionState.PRECHECK.value: "status.precheck",
    SessionState.EXECUTING.value: "status.executing",
    SessionState.POSTCHECK.value: "status.postcheck",
    SessionState.REPLANNING.value: "status.replanning",
    SessionState.PAUSED.value: "status.paused",
    SessionState.STOPPED.value: "status.stopped",
    SessionState.FAILED.value: "status.failed",
    SessionState.COMPLETED.value: "status.completed",
}


FLOW_KEYS = {
    SessionState.LOADING_CONTEXT.value: "flow.loading",
    SessionState.OBSERVING.value: "flow.observing",
    SessionState.PLANNING.value: "flow.planning",
    SessionState.PRECHECK.value: "flow.precheck",
    SessionState.EXECUTING.value: "flow.executing",
    SessionState.POSTCHECK.value: "flow.postcheck",
    SessionState.REPLANNING.value: "flow.replanning",
    SessionState.PAUSED.value: "flow.paused",
    SessionState.STOPPED.value: "flow.stopped",
    SessionState.FAILED.value: "flow.failed",
    SessionState.COMPLETED.value: "flow.completed",
}


RESULT_KEYS = {
    "success": "result.success",
    "failed": "result.failed",
    "stopped": "result.stopped",
    "skipped": "result.skipped",
}


APP_KEYS = {
    "gimp": "GIMP",
    "paint": "Paint",
    "excel": "Excel",
    "word": "Word",
    "powerpoint": "PowerPoint",
    "outlook": "Outlook",
    "teams": "Microsoft Teams",
    "chrome": "Chrome",
    "edge": "Microsoft Edge",
    "file_explorer": "File Explorer",
    "acrobat": "Adobe Acrobat",
    "photoshop": "Adobe Photoshop",
    "illustrator": "Adobe Illustrator",
    "vscode": "Visual Studio Code",
    "terminal": "Windows Terminal",
    "codex_desktop": "Codex Desktop",
    "claude_code_desktop": "Claude Code Desktop",
    "windows_settings": "app.windows_settings",
    "general": "app.general",
}


KNOWLEDGE_KEYS = {
    "constitution": "knowledge.constitution",
    "systemprompt": "knowledge.systemprompt",
    "user": "knowledge.user",
}


STATE_HINT_KEYS = {
    SessionState.IDLE.value: "message.home_empty",
    SessionState.LOADING_CONTEXT.value: "message.phase_loading",
    SessionState.OBSERVING.value: "message.phase_observing",
    SessionState.PLANNING.value: "message.phase_planning",
    SessionState.PRECHECK.value: "message.phase_precheck",
    SessionState.EXECUTING.value: "message.phase_executing",
    SessionState.POSTCHECK.value: "message.phase_postcheck",
    SessionState.REPLANNING.value: "message.phase_replanning",
    SessionState.PAUSED.value: "message.phase_paused",
    SessionState.STOPPED.value: "message.phase_stopped",
    SessionState.FAILED.value: "message.phase_failed",
    SessionState.COMPLETED.value: "message.phase_completed",
}


_SANITIZED_PATTERNS = (
    (("codex is not signed in with chatgpt", "sign in with chatgpt"), "message.codex_sign_in_required"),
    (("codex app server is unavailable", "install or update codex cli"), "message.codex_cli_missing"),
    (("connection confirmed", "text and screenshot input are available"), "message.connection_test_ok"),
    (("validation failed",), "message.validation_failed"),
    (("timeout", "timed out"), "message.timeout"),
    (("cannot transition", "internal flow became invalid"), "message.transition"),
)


def set_locale(locale: str) -> None:
    global _LOCALE
    _LOCALE = "ja" if locale == "ja" else "en"


def get_locale() -> str:
    return _LOCALE


def tr(key: str, **kwargs) -> str:
    value = TEXTS.get(_LOCALE, TEXTS["en"]).get(key, TEXTS["en"].get(key, key))
    if kwargs:
        return value.format(**kwargs)
    return value


def status_key_from_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "status.ready"
    for key in STATE_KEYS.values():
        if text == TEXTS["en"].get(key, "") or text == TEXTS["ja"].get(key, ""):
            return key
    return "status.ready"


def translation_key_for_text(value: str, *, prefixes: tuple[str, ...] = ()) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for locale in ("en", "ja"):
        table = TEXTS.get(locale, {})
        for key, translated in table.items():
            if prefixes and not any(key.startswith(prefix) for prefix in prefixes):
                continue
            if text == translated:
                return key
    return ""


def friendly_state(value: str) -> str:
    return tr(STATE_KEYS.get(value, "status.ready"))


def friendly_flow(value: str) -> str:
    return tr(FLOW_KEYS.get(value, "flow.completed"))


def friendly_result(value: str) -> str:
    return tr(RESULT_KEYS.get(value, "result.stopped"))


def friendly_job_state(value: str) -> str:
    return tr(f"schedule.state.{value}")


def friendly_app_name(value: str) -> str:
    mapped = APP_KEYS.get(value, value or "app.general")
    if mapped.startswith("app."):
        return tr(mapped)
    return mapped


def friendly_knowledge_kind(value: str) -> str:
    return tr(KNOWLEDGE_KEYS.get(value, "knowledge.user"))


def friendly_state_hint(value: str) -> str:
    return tr(STATE_HINT_KEYS.get(value, "message.home_empty"))


def sanitize_user_message(message: str) -> str:
    if not message:
        return ""
    lowered = message.lower()
    for patterns, key in _SANITIZED_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return tr(key)
    if "provider" in lowered or "api" in lowered:
        return tr("message.provider")
    return message


def api_key_status(has_key: bool) -> str:
    return tr("value.configured" if has_key else "value.not_configured")

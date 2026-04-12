# Task Recipe: VS Code Log Triage

Inspect logs or source files in VS Code and collect the most relevant technical findings without making unnecessary edits.

## Best Used When

- A developer wants to inspect stack traces
- A log file must be searched for a failure point
- A config or source file needs a small targeted change

## Inputs

- Workspace path
- File or folder scope
- Search keyword
- Read-only or editable intent

## Success Conditions

- The correct workspace or file is open
- Relevant log lines or code locations are found
- Findings are copied, summarized, or edited as requested

## Prompt Examples

- `VS Codeでこのプロジェクトのログから直近の例外箇所を探して、原因候補をメモ帳に整理して。`
- `設定ファイルのポート番号だけ修正して保存して。ほかは触らないで。`

## Tips

- Say whether the task is inspect-only or may modify files
- Give a keyword, error text, or file name to narrow the search
- For edits, mention exactly which value should change

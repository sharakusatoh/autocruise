# Task Recipe: VS Code Search and Replace Review

Use Visual Studio Code search and replace carefully, reviewing the match scope before changes are applied.

## Best Used When

- Repeated text or identifiers must be updated across files
- A config rename is needed but should be inspected first
- An engineer wants replacement candidates gathered before editing

## Inputs

- Workspace or folder
- Search text
- Replacement text
- Review-only or apply-change instruction

## Success Conditions

- The correct workspace search panel was opened
- Match scope is visible and understandable
- Replacements are either reviewed or applied as instructed

## Prompt Examples

- `VS Codeでold_service_nameを検索して、置換候補を一覧で確認できるところまで進めて。`
- `ワークスペース全体でAPI_URLを検索し、src配下だけnew URLに置換して。変更前に一度止めて。`

## Tips

- Tell it whether the scope is the whole repo, a folder, or one file
- For broad replacements, use "search only" or "review matches first" when the goal asks for review
- Give exact casing and whether regex should be off or on

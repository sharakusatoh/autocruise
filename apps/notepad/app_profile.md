# Notepad App Profile

## Purpose

Simple plain-text writing, scratch notes, and short draft creation in a standard Windows editor.

## Main Screens

- Blank document editor
- Title bar with file state
- Standard File and Edit menus

## Typical Tasks

- Write a sentence or paragraph
- Paste prepared text
- Save a note to a file
- Replace existing text

## UI Structure

- Main document editor
- Menu bar
- Window title showing file state

## Important Shortcuts

- `Ctrl+V`
- `Ctrl+A`
- `Ctrl+S`
- `Enter` to confirm Save dialogs
- `Ctrl+N`

## Common Pitfalls

- The editor may be visible before the text caret is actually active
- Validation by OCR can lag behind successful input
- Untitled windows can be localized and should be recognized by class as well as title
- The window title can change after the first edit, so title-only completion checks are unreliable

## Operational Notes

- Prefer direct process launch when available
- After launch, focus the editor and click inside the document area before typing if focus is unclear
- Prefer paste for longer text blocks or non-ASCII text
- When the goal requires saving, prefer `Ctrl+S`, then handle the Save dialog directly instead of navigating menus

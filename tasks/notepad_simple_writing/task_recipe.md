# Notepad Simple Writing

## Goal

Open Notepad, place the caret in the document editor, enter the requested text, and stop when the requested work is complete.

## Recommended Flow

1. Launch Notepad directly when possible
2. Wait for the Notepad window to appear
3. Focus the Notepad window
4. Activate the document editor with a click if caret state is unclear
5. Type or paste the requested text
6. If the goal asks to save, use `Ctrl+S`
7. If a Save dialog appears, enter the file path or file name and confirm with `Enter`
8. Stop only after the text entry succeeds and any requested save step is complete

## Text Entry Rules

- Use paste for Japanese text, multi-line text, or longer sentences
- Use direct typing for short ASCII-only text when the editor clearly has focus
- Do not reopen Notepad if it is already visible and ready
- Do not type the same text twice after a successful text entry
- If no file path is specified, choose a deterministic `.txt` path and finish the save flow

## Completion Signal

- The editor content changes, or the input action succeeded while the focused element is the editor/document area
- When saving is requested, the Save dialog closes and the editor returns to the saved document

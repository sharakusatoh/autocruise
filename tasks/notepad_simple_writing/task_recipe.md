# Notepad Simple Writing

## Goal

Open Notepad, place the caret in the document editor, enter the requested text, and stop when the text is present.

## Recommended Flow

1. Launch Notepad directly when possible
2. Wait for the Notepad window to appear
3. Focus the Notepad window
4. Activate the document editor with a click if caret state is unclear
5. Type or paste the requested text
6. Stop after the text entry succeeds

## Text Entry Rules

- Use paste for Japanese text, multi-line text, or longer sentences
- Use direct typing for short ASCII-only text when the editor clearly has focus
- Do not reopen Notepad if it is already visible and ready

## Completion Signal

- The editor content changes, or the input action succeeded while the focused element is the editor/document area

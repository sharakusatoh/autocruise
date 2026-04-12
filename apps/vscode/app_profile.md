# Visual Studio Code App Profile

Inspect and edit code, logs, and configuration with caution around terminals, saves, and mass replacements.

## Purpose

VS Code is best for log triage, small code changes, config edits, search and replace, and reading project files.

## Main Screens

- Editor tabs
- Explorer pane
- Search pane
- Integrated terminal
- Problems panel

## Typical Tasks

- Open a workspace or file
- Search logs or code
- Update a config value
- Copy diagnostic snippets

## Important Shortcuts

- `Ctrl+P`
- `Ctrl+Shift+F`
- `Ctrl+```
- `Ctrl+S`
- `F12`
- `Alt+Left`

## Common Pitfalls

- Editing the wrong file in a similarly named tab
- Replacing more than intended with global search
- Running commands in the wrong terminal
- Saving config changes without checking the environment

## Operational Notes

- Confirm workspace root, file tab, and search scope before edits
- Prefer targeted changes over broad replace-all actions
- Run terminal commands and config writes when they are part of the requested development task
- For investigation tasks, copy findings first and edit second

## Prompt Tips

- Mention workspace path, file name, keyword, and whether the task is read-only or should modify files
- For troubleshooting, specify what signal matters: stack trace, failing test, config value, or log entry
- If commands should not be executed, say “inspect only”

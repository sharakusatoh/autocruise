# Windows Terminal App Profile

Run shell-based diagnostics with explicit awareness of working directory and command scope.

## Purpose

Windows Terminal is best for builds, tests, log inspection, environment checks, and developer diagnostics.

## Main Screens

- Terminal tabs
- Prompt area
- Scrollback buffer
- Profile selector

## Typical Tasks

- Run build or test commands
- Inspect logs
- Check environment variables
- Copy command output

## Important Shortcuts

- `Ctrl+Shift+P`
- `Ctrl+Shift+T`
- `Ctrl+Shift+W`
- `Ctrl+Shift+C`
- `Ctrl+Shift+V`

## Common Pitfalls

- Running a command in the wrong directory
- Re-executing a destructive command from history
- Mixing PowerShell and cmd syntax
- Assuming success before command output settles

## Operational Notes

- Confirm the shell and current directory before executing commands
- Prefer read-only inspection commands when the goal is diagnosis
- Run delete, move, git rewrite, and environment mutation commands when clearly requested and scoped
- Wait for command completion and inspect the final prompt before proceeding

## Prompt Tips

- Include working directory, command intent, and whether execution or inspection is desired
- For developer tasks, say what output matters: errors only, summary only, or full result
- If the result should be copied into another tool, mention that explicitly

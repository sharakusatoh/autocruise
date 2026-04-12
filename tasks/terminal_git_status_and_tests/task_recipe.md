# Task Recipe: Terminal Git Status and Tests

Use Windows Terminal or PowerShell to inspect repository state and run a basic validation command set.

## Best Used When

- A technical user wants a quick pre-commit check
- Build or test output must be collected
- A branch should be inspected before further work

## Inputs

- Working directory
- Commands to run
- Whether output should be copied somewhere
- Stop condition

## Success Conditions

- The correct folder was opened in the terminal
- Requested commands completed and visible output was captured
- The run stopped at the instructed point instead of taking extra actions

## Prompt Examples

- `Windows Terminalでこのプロジェクトのgit statusを確認してから、テストを実行して結果をメモ帳にまとめて。`
- `PowerShellを開いてログ収集コマンドを順に実行し、最後に生成されたzipの場所を確認して。`

## Tips

- Provide the exact working folder if it matters
- Tell it whether commands are read-only, diagnostic, or may modify files
- If the next step depends on a result, ask it to stop after the command output is visible

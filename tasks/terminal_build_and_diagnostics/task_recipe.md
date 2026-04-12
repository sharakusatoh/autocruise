# Task Recipe: Terminal Build And Diagnostics

Run terminal commands for build, test, or diagnostics with strict working-directory and output awareness.

## Best Used When

- A developer wants to run build or test commands
- Logs should be inspected from command output
- Environment state must be checked quickly

## Inputs

- Working directory
- Command to run
- Expected output or failure signal
- Whether the task is read-only or mutating

## Success Conditions

- The terminal is in the correct directory
- The command completes or fails visibly
- The relevant output is captured or summarized

## Prompt Examples

- `Windows Terminalでこのフォルダに移動してテストを実行し、失敗した箇所だけメモして。`
- `PowerShellでビルドを走らせて、最後のエラー行をVS Codeに貼れる形でまとめて。`

## Tips

- Include the working directory every time
- Say whether the command may change files or should be inspect-only
- If only the final status matters, say “summarize errors only”

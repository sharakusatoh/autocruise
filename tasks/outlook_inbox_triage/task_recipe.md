# Task Recipe: Outlook Inbox Triage

Sort and prioritize Outlook mail with folders, flags, and draft preparation while keeping send behavior under control.

## Best Used When

- A user wants to clear an overloaded inbox
- Important customers must be identified quickly
- Follow-up drafts should be prepared from unread mail

## Inputs

- Mailbox or folder name
- Priority rule
- Triage action
- Draft or send policy

## Success Conditions

- The correct mailbox or folder was processed
- Messages were moved, flagged, or categorized as requested
- Any reply drafts stop at draft unless explicit send was requested

## Prompt Examples

- `Outlookの受信トレイを整理して、重要メールはフラグを付け、不要な通知は専用フォルダへ移して。`
- `未読メールのうち顧客名が入っているものだけ見て、返信が必要そうなものは下書きまで作って。`

## Tips

- Give a clear rule such as sender, subject keyword, unread status, or date range
- If deletion is not desired, say "move or flag only"
- Draft creation works better when you name the target sender or mail pattern

# Task Recipe: Browser Support Ticket Update

Update a browser-based support ticket with a clean status note while avoiding accidental submission to the wrong case.

## Best Used When

- An engineer needs to post progress to Jira, Zendesk, or another service desk
- Status, assignee, or resolution notes must be updated
- A customer-visible note should be prepared carefully

## Inputs

- Ticket system name
- Ticket number or search term
- Update text or bullet points
- Draft-only or submit-now instruction

## Success Conditions

- The correct ticket was opened
- Status fields and comments match the request
- The note is saved or submitted exactly as instructed

## Prompt Examples

- `ブラウザでJiraのABC-123を開いて、調査中コメントを追記して保存して。`
- `Zendeskの問い合わせ票を検索して、顧客向け返信文を下書きして。送信はしないで。`

## Tips

- Always include the ticket ID when available
- Distinguish internal notes from customer-visible replies
- If multiple tickets match, ask it to stop on the result list rather than guessing

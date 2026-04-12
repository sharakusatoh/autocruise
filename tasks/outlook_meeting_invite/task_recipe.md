# Task Recipe: Outlook Meeting Invite

Create a calendar invite in Outlook with careful validation of date, time, attendees, and send intent.

## Best Used When

- A meeting needs to be scheduled
- Existing details from chat or email must be turned into an invite
- A draft invite should be prepared for final review

## Inputs

- Meeting title
- Date and time
- Duration
- Attendees
- Location or Teams flag
- Draft-only or send-now instruction

## Success Conditions

- Meeting title, date, and time are correct
- Attendees are accurate
- Invite is drafted or sent as requested

## Prompt Examples

- `Outlookで来週火曜15時から30分の定例会議招待を作って。送信前で止めて。`
- `営業レビュー会議をOutlookで作成し、Teams会議付きで招待を送って。`

## Tips

- Specify timezone-sensitive times clearly
- Mention whether the meeting should include a Teams link
- If attendee names are ambiguous, include email addresses

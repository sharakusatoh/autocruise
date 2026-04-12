# Task Recipe: Browser CRM Update

Update a browser-based CRM or SFA record while preserving field accuracy and avoiding accidental submission.

## Best Used When

- A sales record needs new notes
- Opportunity stage or next action must be updated
- Contact details should be added or corrected

## Inputs

- CRM site name
- Record name
- Fields to update
- Save or submit instruction

## Success Conditions

- The correct customer or opportunity record is open
- Requested fields show the new values
- The task stops at draft, saved record, or reviewed form as requested

## Prompt Examples

- `ChromeでSalesforceのA社案件を開き、次回アクションと商談メモを更新して保存して。`
- `HubSpotの顧客レコードに面談結果を入力して、送信前で止めて。`

## Tips

- Mention record name and exact fields to update
- If multiple similar records exist, include company and owner
- Explicitly say whether the agent may click Save

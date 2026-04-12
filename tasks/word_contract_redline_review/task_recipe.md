# Task Recipe: Word Contract Redline Review

Review a contract in Word with Track Changes or comments while avoiding silent overwrites and accidental wording drift.

## Best Used When

- A legal or sales document needs limited clause edits
- Contract comments must be inserted without finalizing the document
- A draft requires wording cleanup under change tracking

## Inputs

- Contract file path
- Clauses or headings to review
- Whether to use comments or Track Changes
- Save-in-place or save-as-copy instruction

## Success Conditions

- Only the requested clauses were edited
- Change tracking or comments are visible as requested
- The output file behavior matches the instruction

## Prompt Examples

- `Wordで契約書の支払条件条項だけ見直して、変更履歴を残して。元ファイルは上書きしないで。`
- `秘密保持契約の第3条にコメントを入れて、送信はせず保存前で止めて。`

## Tips

- Name the clause or heading, not just "the contract"
- If legal wording is sensitive, ask for comments first instead of direct rewrites
- Say whether the final state should be a draft, tracked edit, or comment-only review

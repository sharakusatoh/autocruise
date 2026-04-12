# Task Recipe: Excel Sales Pipeline Update

Update a sales spreadsheet while preserving workbook structure and explicit save intent.

## Best Used When

- A sales team needs a pipeline table refreshed
- Forecast, stage, owner, or next-action columns must be updated
- A summary tab or dashboard should be checked after edits

## Inputs

- Workbook path or open workbook name
- Sheet name
- Rows or account names to update
- Save behavior

## Success Conditions

- The correct workbook and sheet were edited
- Requested rows and columns show the updated values
- Filters or sorting remain usable
- Save behavior matches the instruction

## Prompt Examples

- `Excelで営業パイプライン表を開き、A社とB社の案件ステージを更新して、保存前で止めて。`
- `Excelの売上見込みシートで今月分の数値を更新し、集計タブを確認してから上書き保存して。`

## Tips

- Specify account names or row labels, not only “update the table”
- Mention whether the task ends at visible edits or at saved completion
- Ask for one sheet at a time if the workbook is large

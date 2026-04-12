# Task Recipe: Excel Invoice Reconciliation

Check invoice and payment rows in Excel and reconcile mismatches without losing the original ledger structure.

## Best Used When

- Sales operations must compare billed amounts and received payments
- Accounting support needs a quick mismatch list
- A workbook has overdue or missing payment marks

## Inputs

- Workbook name or path
- Target sheet name
- Reconciliation rule
- Output style

## Success Conditions

- The correct workbook and sheet were opened
- Unmatched or suspicious rows were identified
- Notes, colors, or a summary sheet were added as requested

## Prompt Examples

- `Excelで請求一覧と入金一覧を照合して、不一致の行だけ黄色にして。保存前で止めて。`
- `売掛金管理ブックを開いて、未入金の顧客を抽出し、別シートに一覧を作って。`

## Tips

- Tell it which columns contain invoice number, customer, amount, and date
- If formulas must not change, explicitly say "do not rewrite formulas"
- If the workbook is sensitive, ask for a summary sheet or color marking instead of destructive edits

# Task Recipe: PDF Review And Annotation

Open a PDF, inspect specific pages, and add comments or highlights without altering the source beyond the requested review marks.

## Best Used When

- A contract, brochure, or manual needs review comments
- Technical PDFs need highlight-based feedback
- A reviewed copy should be saved separately

## Inputs

- PDF path
- Page numbers or sections
- Annotation style
- Save behavior

## Success Conditions

- Target pages were reviewed
- Requested comments or highlights were added
- The reviewed file is saved or left unsaved as instructed

## Prompt Examples

- `PDFを開いて3ページ目と5ページ目にコメントを入れて、別名保存して。`
- `見積PDFの金額と納期だけチェックして、気になる箇所をハイライトして。`

## Tips

- Mention page range and what to look for
- Say whether comments should be short labels or full reviewer sentences
- If the source file must remain untouched, say “save a reviewed copy”

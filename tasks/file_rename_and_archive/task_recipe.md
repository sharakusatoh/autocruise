# Task Recipe: File Rename And Archive

Rename and archive files in a controlled pattern without moving the wrong items or overwriting existing files.

## Best Used When

- A batch of files needs a naming convention
- Old files must be compressed or moved into archive folders
- A project handoff requires cleaner filenames

## Inputs

- Target folder
- Naming rule
- Archive folder or ZIP name
- Overwrite handling

## Success Conditions

- Selected files follow the new naming rule
- Archive output exists in the intended location
- Existing files are not overwritten unexpectedly

## Prompt Examples

- `フォルダ内のPDFを日付_顧客名_連番の形式にリネームして、元ファイルは残して。`
- `完了済み資料をArchiveフォルダへ移動してZIP化して。上書きはしないで。`

## Tips

- Specify whether numbering starts at 1 and whether extensions must stay unchanged
- If both rename and ZIP are required, mention the order explicitly
- For broad renames, stop at preview or final confirmation when the goal requests review first

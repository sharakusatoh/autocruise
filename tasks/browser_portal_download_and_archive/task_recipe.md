# Task Recipe: Browser Portal Download and Archive

Download reports from a web portal and store them into the correct local folder with predictable names.

## Best Used When

- Periodic sales or operations reports must be downloaded
- A portal produces CSV, XLSX, or PDF exports
- The downloaded file should be renamed and archived locally

## Inputs

- Portal name and report page
- Date range
- Destination folder
- Rename rule

## Success Conditions

- The right portal page was opened
- The expected file was downloaded
- The file was moved or renamed into the requested archive folder

## Prompt Examples

- `Edgeでポータルから先月の売上CSVをダウンロードして、営業共有フォルダへ移動して。`
- `管理画面から月次PDFを取得して、日付付きの名前に変えて保存して。`

## Tips

- Mention the expected file format so the agent knows what completion looks like
- If several downloads can happen, ask it to verify the latest file name before moving
- Give an explicit rename pattern if your archive has naming rules

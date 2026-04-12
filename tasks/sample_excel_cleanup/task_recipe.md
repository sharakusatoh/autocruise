# Task Recipe: Sample Excel Cleanup

## Purpose

Apply a repeatable cleanup pattern to a spreadsheet while preserving user control over save actions.

## Preconditions

- Excel is installed
- The target workbook is open or path is known

## Inputs

- Workbook identity
- Target sheet
- Cleanup intent

## Outputs

- Cleaned workbook state
- Optional saved copy

## Success Conditions

- Correct workbook and sheet were modified
- Intended cleanup actions completed
- Save or overwrite behavior matched the requested output
- Each change was validated on screen before moving to the next step

## Stage Breakdown

1. Identify workbook and sheet
2. Confirm current selection and visible headers
3. Execute one cleanup action
4. Re-observe and validate
5. Repeat by stage until objective is complete

## Branch Conditions

- If the workbook is not active, focus it first
- If Excel is not open, launch it with the shortest reliable Windows path
- If a sheet is loading or recalculating, wait and re-observe before typing or clicking
- If a save confirmation appears, proceed when the requested output already covers it; otherwise stop with the dialog visible

## Exception Handling

- On selection ambiguity, stop and re-observe
- On unexpected dialog, identify the dialog purpose and replan

## Confirmation Points

- Overwrite
- Delete rows or columns
- External export or sharing

## Reusable Action Patterns

- Focus workbook
- Find header row
- Apply filter
- Validate changed cell region
- Prefer keyboard shortcuts for ribbon actions when they are stable
- Recheck workbook title and sheet tab after each major edit

## Semantic Steps

- Confirm context
- Make one reversible change
- Validate result

## Low-level Mapping

- Focus window
- Use ribbon or shortcut
- Re-observe
- Validate

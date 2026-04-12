# Task Recipe: Paint Simple Line Drawing

Open Paint, choose a basic drawing tool, and make a recognizable line sketch in a few visible strokes.

## Best Used When

- A user wants a quick cat sketch, diagram, or doodle
- Paint should be opened from Windows and used immediately
- The result can be rough as long as it is clearly recognizable

## Inputs

- Subject to draw
- Roughness or detail level
- Whether to stop before save

## Success Conditions

- Paint is open and the canvas is visible
- A simple recognizable sketch appears on the canvas
- The run stops at the requested point

## Prompt Examples

- `ペイントを開いて簡単な猫の線画を描いて下さい。`
- `Paintでラフな猫のイラストを描いて、保存せず止めて。`

## Tips

- Paint tasks work best when the app is launched first, then the canvas is confirmed, then short planned strokes are used
- Curves should be planned as several points on a canvas-relative coordinate plane rather than a single straight drag
- For a cat sketch, ask for head, ears, eyes, whiskers, body, and tail in that order
- If you only want the drawing and not file output, say `保存しないで止めて`

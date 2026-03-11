---
name: computer-use
description: Control the Windows desktop — take screenshots, click, type, press keys, manage apps and files. Use for any task requiring GUI interaction, reading the screen, or automating desktop workflows.
metadata: {"ker":{"emoji":"🖥️","requires":{"bins":["uvx"]}}}
---

# Computer Use (Windows-MCP)

Control the Windows desktop via the `computer_use` MCP tools. These tools are
prefixed with `mcp_computer_use_*` in the tool list.

Powered by [Windows-MCP](https://github.com/CursorTouch/Windows-MCP) — uses
native Windows UI Automation for reliable element detection.

## Available Tools

| MCP Tool | Purpose |
|----------|---------|
| `mcp_computer_use_Snapshot` | Capture desktop state: windows, UI elements with labels, optional screenshot |
| `mcp_computer_use_Click` | Click at coordinates or labeled element |
| `mcp_computer_use_Type` | Type text into a field (with optional clear) |
| `mcp_computer_use_Scroll` | Scroll up/down/left/right |
| `mcp_computer_use_Move` | Move cursor or drag-and-drop |
| `mcp_computer_use_Shortcut` | Press key combo (e.g. "ctrl+c", "alt+tab", "win+r") |
| `mcp_computer_use_Wait` | Pause for N seconds |
| `mcp_computer_use_App` | Launch, resize, or switch to an application |
| `mcp_computer_use_PowerShell` | Execute a PowerShell command |
| `mcp_computer_use_FileSystem` | Read/write/copy/move/delete/list/search files |
| `mcp_computer_use_Scrape` | Fetch URL content or extract from active browser tab |
| `mcp_computer_use_MultiSelect` | Select multiple UI elements |
| `mcp_computer_use_MultiEdit` | Edit multiple fields in one call |
| `mcp_computer_use_Clipboard` | Get or set clipboard content |
| `mcp_computer_use_Process` | List or kill processes |
| `mcp_computer_use_Notification` | Show a desktop notification |

## Workflow Pattern

1. **Snapshot first** — always take a Snapshot before acting. It returns the
   list of interactive elements with label IDs and coordinates.
2. **Target by label or coordinates** — use the `label` ID from Snapshot for
   reliable targeting, or raw `[x, y]` coordinates.
3. **Act** — Click, Type, Shortcut, Scroll, etc.
4. **Verify** — take another Snapshot to confirm the action worked.

```
Snapshot → identify target → act → Snapshot → verify → repeat
```

## Key Parameters

### Snapshot
```json
{
  "use_vision": true,       // include screenshot image
  "use_ui_tree": true,      // extract interactive elements (default)
  "use_annotation": true,   // draw bounding boxes on elements
  "use_dom": false           // get browser DOM instead of UI chrome
}
```

### Click
```json
{
  "label": 42,              // element label from Snapshot (preferred)
  "loc": [500, 300],        // OR raw [x, y] coordinates
  "button": "left",         // left | right | middle
  "clicks": 1               // 0=hover, 1=single, 2=double
}
```

### Type
```json
{
  "text": "hello world",
  "label": 42,              // target field
  "clear": true,            // clear existing text first
  "press_enter": false
}
```

### App
```json
{
  "mode": "launch",         // launch | resize | switch
  "name": "notepad"
}
```

## Best Practices

- **Always Snapshot first.** The UI tree gives you labeled elements — use labels
  instead of guessing coordinates.
- **Use `label` targeting** over raw coordinates when possible. Labels are
  identified from the UI Automation tree and are more reliable than pixel coords.
- **Use Shortcut** for keyboard combos — more reliable than clicking menus
  (e.g. `ctrl+s` to save, `alt+f4` to close, `win+r` for Run dialog).
- **Use `use_vision: true`** on Snapshot when you need to see what's on screen
  (e.g. reading text, verifying visual state). Omit it when you only need the
  element tree (faster).
- **Use App tool** to launch/switch apps instead of clicking taskbar buttons.
- **Use PowerShell** for system tasks that don't need GUI interaction.
- **Use FileSystem** for file operations instead of clicking through Explorer.
- **Write temporary scripts** to `.ker/tmp_code/`, never to the project root.

## Common Patterns

### Open an app and interact
```
1. App(mode="launch", name="notepad")
2. Wait(duration=2)
3. Snapshot() → find text area label
4. Type(label=<id>, text="Hello from Ker!")
5. Shortcut(shortcut="ctrl+s")
```

### Read content from a window
```
1. App(mode="switch", name="Chrome")
2. Snapshot(use_vision=true) → read visible text
```

### Fill a web form
```
1. Snapshot(use_dom=true) → get form field labels
2. Type(label=<field1>, text="value1", press_enter=false)
3. Type(label=<field2>, text="value2")
4. Click(label=<submit_button>)
```

### Copy text from one app to another
```
1. App(mode="switch", name="source app")
2. Shortcut(shortcut="ctrl+a")
3. Shortcut(shortcut="ctrl+c")
4. Clipboard(mode="get") → verify content
5. App(mode="switch", name="target app")
6. Shortcut(shortcut="ctrl+v")
```

## Safety

- The model has **full control** of mouse, keyboard, and system. Supervise carefully.
- Prefer reversible actions. Avoid destructive operations without user confirmation.
- If something goes wrong, take a Snapshot and describe the current state.
- Disable telemetry if needed: set env var `ANONYMIZED_TELEMETRY=false`.

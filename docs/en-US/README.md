# Icon Conversion Tool

This is a small Windows desktop utility for applying custom icons to folders, shortcuts, and EXE-derived shortcuts.

## Supported Targets and Sources

- Supported targets:
  - Folders
  - `.lnk` shortcuts
  - `exe` programs
- Supported icon sources:
  - `.png`
  - `.jpg`
  - `.jpeg`
  - `.ico`
  - `.exe`

## Behavior

- When the target is a folder:
  - The app writes `desktop.ini`
  - The folder is marked with system and read-only attributes
  - Existing folder contents are not modified
- When the target is a `.lnk` file:
  - The shortcut's icon field is updated directly
  - The original target behind the shortcut is not modified
- When the target is an `exe` file:
  - The EXE itself is not modified
  - A new shortcut named `Original Name - Custom Icon.lnk` is created in the same directory

## Icon Processing

- Image sources are center-cropped to a square and exported as multi-size `.ico`
- Existing `.ico` files are normalized to standard sizes
- EXE sources are parsed for resources and the best icon is extracted
- All generated icons are stored in `%LOCALAPPDATA%\IconConversionTool\icons`

## Run

```powershell
pip install -r requirements.txt
python app.py
```

## Bilingual Support

- UI language files live in `lang/`
- Built-in languages:
  - `lang/zh-CN.json`
  - `lang/en-US.json`
- The app lets you switch languages from the top-right corner
- The selected language is saved to `.icon-tool-settings.json` in the project root

## Extension Notes

- To add another language, create a new JSON file with the same key structure
- The current layout is ready for expanding prompts, errors, and button labels further

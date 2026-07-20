# Icon Conversion Tool / 图标替换工具

[简体中文说明](./docs/zh-CN/README.md) | [English Guide](./docs/en-US/README.md)

A small Windows desktop utility for applying custom icons to folders, shortcuts, and EXE-derived shortcuts.

一个面向 Windows 的桌面小工具，用来给文件夹、快捷方式和 EXE 派生快捷方式应用自定义图标。

## Features / 功能

- Supports folder targets, `.lnk` shortcuts, and `.exe` files.
- Supports icon sources from `.png`, `.jpg`, `.jpeg`, `.ico`, and `.exe`.
- Extracts native icon resources from EXE files when an EXE is used as the source.
- Stores generated `.ico` files under `%LOCALAPPDATA%\IconConversionTool\icons`.
- Includes a bilingual UI powered by files in [`lang`](./lang).

- 支持文件夹、`.lnk` 快捷方式和 `.exe` 文件作为目标。
- 支持 `.png`、`.jpg`、`.jpeg`、`.ico`、`.exe` 作为图标来源。
- 当图标来源是 EXE 时，会直接提取其原生图标资源。
- 生成后的 `.ico` 会统一保存到 `%LOCALAPPDATA%\IconConversionTool\icons`。
- 现在已经支持双语界面，文案来自 [`lang`](./lang) 目录。

## Quick Start / 快速开始

```powershell
pip install -r requirements.txt
python app.py
```

If `tkinterdnd2` is unavailable, the app still works, but drag and drop is disabled.

如果没有安装 `tkinterdnd2`，程序仍然可以运行，只是不能使用拖拽。

## Project Structure / 项目结构

```text
.
├─ app.py
├─ lang/
│  ├─ zh-CN.json
│  └─ en-US.json
├─ docs/
│  ├─ zh-CN/README.md
│  └─ en-US/README.md
└─ requirements.txt
```

## Localization / 双语方案

- Add more UI languages by placing JSON files in `lang/`.
- Each language file contains `meta` and `messages`.
- Markdown documentation is separated into `docs/zh-CN` and `docs/en-US`.

- 后续如果要扩展更多界面语言，只要继续往 `lang/` 目录添加 JSON 文件即可。
- 每个语言文件包含 `meta` 和 `messages` 两部分。
- Markdown 文档则按语言拆分到 `docs/zh-CN` 和 `docs/en-US`。

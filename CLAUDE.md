# Asset Library — Project Brief for Claude Code

## What this is

A **Prism 2 plugin** that replaces Prism's built-in library UI with a custom asset browser. Prism handles the backend (versioning, file paths, project context). This plugin owns everything the artist sees and touches.

---

## Studio context

- ~20 person medical animation studio, 8 artists
- DCCs: **Houdini** and **Maya**
- Renderer: **Redshift**
- Pipeline: **Prism 2** + **Kitsu**
- Asset storage: **local NAS**
- Team roles: TD (publish/write), Artists (browse/read)

---

## Architecture decisions

### Backend
- Prism 2 handles versioning, file paths, and project context — do not replace this
- A **SQLite database** (`library.db`) lives at the NAS root alongside the Prism folder structure
- `library.db` stores all metadata that Prism doesn't: tags, favorites, custom categories, DCC exclusivity flags
- Each asset also gets a **sidecar thumbnail** (`.png`) next to its Prism files

### Plugin structure
```
Plugins/
└── AssetLibraryPro/
    ├── AssetLibraryPro.py      # Main Prism 2 plugin class
    ├── ui/
    │   ├── library_browser.py  # Main Qt panel (PySide2)
    │   └── publish_dialog.py   # Publish/ingest dialog
    ├── core/
    │   ├── db.py               # SQLite read/write layer
    │   └── dcc_bridge.py       # Houdini / Maya specific import/export logic
    └── icons/
```

### Key principle
Assets are **universal by default** (work in both Houdini and Maya). DCC-exclusive assets are the exception and are flagged in the DB, not assumed.

---

## UI design decisions (finalized in mockup)

### Layout
- **Split panel**: sidebar tree on left (185px), thumbnail grid on right
- **Toolbar**: title | search | sort dropdown | size slider | filters dropdown | + Publish button
- **Status bar**: asset count + active filters | drag hint

### Sidebar tree structure
```
Quick access
  ★ Favorites
  ◷ Recent
─────────────
Library
  All assets
─────────────
Models
  Anatomy
  Props
  Environments
─────────────
Shaders
  Skin
  Metal
  Glass
  Fabric
  Organic
─────────────
HDAs
  Rigging
  FX
  Modeling
─────────────
Textures        ← separate from Shaders, same subcategory names
  Skin
  Metal
  Glass
  Fabric
  Organic
─────────────
Lighting        ← separate from Textures
  HDRIs
  Light rigs
```

### Asset cards
- Thumbnail area (height scales with size slider)
- Asset name + type subtitle
- Bottom controls row: **version dropdown** | **file type dropdown** | **★ favorite toggle**
- Hover reveals tooltip: name, type, author, tags — no click needed
- Draggable into DCC viewport (auto import/reference)

### Tag row
- Shows active tags + inactive tags inline
- Collapsed by default beyond ~6 tags — "+N more" dashed pill expands the rest
- "+ tag" button at end to add new tags

### Filters dropdown (toolbar)
Groups: DCC (All / Houdini exclusive / Maya exclusive), Type (Materials / Models / HDAs / HDRIs+Light rigs / Textures), Author

### Publish dialog
Triggered by **+ Publish** button (green, top-right toolbar).
Fields:
- **Source**: From disk | From DCC scene | From Prism publish (3-option selector)
- Asset name + version
- Category (hierarchical: e.g. "Shaders / Skin")
- File type (`.rs`, `.mtlx`, `.abc`, `.hda`, `.exr`, `.hdr`, `.hip`, `.ma`)
- Tags (pill-style, click to remove, type to add)

"From DCC scene" is the default source — this is the primary workflow for artists publishing directly from Houdini or Maya via the Prism plugin.

---

## File types per asset category

| Category | File types |
|---|---|
| Shaders (RS materials) | `.rs`, `.mtlx` |
| Models | `.abc`, `.usd`, `.fbx` |
| HDAs | `.hda`, `.otl` |
| Textures | `.exr`, `.tx`, `.png`, `.tif` |
| HDRIs | `.exr`, `.hdr` |
| Light rigs | `.hip` (Houdini), `.ma` (Maya) |

---

## Interaction behaviors

- **Drag and drop**: drag card into DCC viewport → auto import/reference. Works for both Houdini and Maya viewports.
- **Favorites**: star toggle on card, persisted in `library.db`, surfaced in sidebar "Favorites" section
- **Version picker**: dropdown on card shows all available versions (pulled from Prism versioning). Selecting a version changes what gets imported on drag.
- **Thumbnail size**: slider in toolbar resizes grid columns and thumbnail height proportionally (min ~90px, max ~170px)
- **Tags**: stored in `library.db`, many-to-many relationship with assets

---

## Visual design reference

A finalized HTML mockup (`asset_library_mockup.html`) exists and should be used as the visual spec. Key design tokens:

- Font: IBM Plex Sans (UI) + IBM Plex Mono (metadata, counts, version strings)
- Borders: 0.5px, very subtle
- Radius: 6px (components), 10px (panels/cards)
- Colors: neutral warm grays, blue accent for active/selected states, green for publish actions
- Supports light and dark mode
- No gradients, no heavy shadows — flat and clean

---

## What still needs to be built

1. **Prism 2 plugin scaffold** — plugin class, hooks into Prism's library tab
2. **SQLite schema** — assets, tags, asset_tags, favorites, recently_used tables
3. **PySide2 panel** — port the HTML mockup to Qt widgets inside Prism
4. **DCC bridge** — Houdini Python API for drag-import, Maya cmds equivalent
5. **Publish pipeline** — validation, thumbnail generation, DB write, Prism publish hook
6. **Thumbnail generation** — auto-render or manual screenshot on publish

---

## Environment variables

- `$ASSET_LIB` — points to NAS library root, baked into Houdini/Maya startup scripts
- All asset paths stored relative to `$ASSET_LIB`

---

## Open questions / deferred decisions

- Thumbnail generation strategy (auto-render vs manual screenshot on publish)
- Whether to use Prism's existing publish hooks or intercept earlier in the pipeline
- USD/USDZ support for future Solaris adoption (currently evaluating)
- Permission enforcement — currently planned at filesystem level (NAS), not in the plugin itself

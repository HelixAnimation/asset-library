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

### USD as the primary format (long-term goal)
The target is for every asset to be a single **USD file** that bundles everything relevant to its type:
- **Models** → geometry + materials + rig in one USD
- **Shaders** → material network as USD/MaterialX
- **Lighting** → lights + materials in one USD
- **HDAs** → output as USD where possible

A single USD file works across both Houdini (Solaris) and Maya (Maya USD plugin) without DCC-specific variants. Legacy formats (`.rs`, `.abc`, `.hip`, `.ma`) remain supported for assets not yet migrated. New assets should target USD first.

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
  Organs
  Props
  Environments
─────────────
Materials
  Skin
  Metal
  Glass
  Fabric
  Organic
  Fluid
  GPU Open
─────────────
HDAs
  Rigging
  FX
  Modeling
─────────────
Textures
  Skin
  Metal
  Glass
  Fabric
  Organic
─────────────
Lighting
  HDRIs
  Light rigs
  Poly Haven
```

### Asset cards
- Thumbnail area (height scales with size slider)
- Thumbnail gallery: render type dots (material / clay / wire) switch render view; arrows cycle images within that type
- **★ favorite** in top-left corner of thumbnail
- Asset name + type · filetype subtitle
- No bottom controls — version and file type are changed via **right-click context menu**
- Hover reveals tooltip: name, type, author, renderer, DCC, includes (rig/tex/mat), tags
- Draggable into DCC viewport (auto import/reference)

### Right-click context menu
- **Version** — radio list of all available versions
- **File type** — radio list of available file types for that asset
- **USD** section (only shown if `.usd` is available) — **View USD** | **View USD via Prism**
- **Edit asset…** — opens the import dialog pre-filled with current asset data

### Tag row
- Shows active tags + inactive tags inline
- Collapsed by default beyond ~6 tags — "+N more" dashed pill expands the rest
- "+ tag" button at end to add new tags

### Filters dropdown (toolbar)
Tabbed panel with horizontal tab bar (DCC | TYPE | FILE | INC | AUTH). Fixed 220x280 popup anchored below the Filters button. Checkboxes laid out in 2 columns per tab. One tab visible at a time — no resizing or overflow issues. Tabs:
- **DCC**: All DCCs / Houdini exclusive / Maya exclusive
- **Type**: Materials / Models / HDAs / HDRIs+Light rigs / Textures
- **File**: .usd / .rs / .mtlx / .abc / .hda / .exr / .hdr / .hip / .ma
- **Includes**: Rig / Textures / Materials
- **Author**: dynamic list from DB
All filters are additive across tabs.

### Import dialog
Triggered by **Import** button (toolbar).
Fields:
- **Source**: From disk | From Prism publish
- Asset name + version
- **Category** dropdown (Materials / Models / HDAs / Textures / Lighting)
- **Subcategory** dropdown — options change based on category; last option is **+ Custom…** which swaps to a text input
- File type (`.usd`, `.rs`, `.mtlx`, `.abc`, `.hda`, `.exr`, `.hdr`, `.hip`, `.ma`)
- Renderer (Any / Redshift / Arnold / V-Ray)
- DCC (Universal / Houdini only / Maya only)
- Includes: Rig / Textures / Materials (checkboxes)
- Tags (pill-style, click to remove, type to add)

---

## File types per asset category

| Category | File types |
|---|---|
| Materials | `.usd`, `.rs`, `.mtlx` |
| Models | `.usd`, `.abc`, `.fbx` |
| HDAs | `.usd`, `.hda`, `.otl` |
| Textures | `.exr`, `.tx`, `.png`, `.tif` |
| HDRIs | `.exr`, `.hdr` |
| Light rigs | `.usd`, `.hip` (Houdini), `.ma` (Maya) |

---

## Interaction behaviors

- **Drag and drop**: drag card into DCC viewport → auto import/reference at the selected version and file type. Works for Houdini and Maya.
- **Right-click menu**: change version, change file type, view USD, view USD via Prism, edit asset metadata
- **View USD**: opens the asset's `.usd` file in usdview (or DCC equivalent)
- **View USD via Prism**: opens/references the asset through Prism's version browser
- **Favorites**: star in thumbnail corner, persisted in `library.db`, surfaced in sidebar "Favorites" section
- **Version picker**: right-click → Version. Selected version is what gets imported on drag.
- **File type picker**: right-click → File type. Tooltip updates to reflect metadata for the selected type.
- **Thumbnail gallery**: render type dots switch between material/clay/wire renders; arrows cycle images within the active type
- **Thumbnail size**: slider in toolbar resizes grid columns proportionally (min ~90px, max ~170px)
- **Tags**: stored in `library.db`, many-to-many with assets; filterable from toolbar filters
- **Sidebar navigation**: clicking a category or subcategory filters the grid to that scope
- **Search**: filters grid by asset name in real time
- **Filters dropdown**: stacks DCC + Type + File type + Includes + Author filters; all additive

---

## Visual design reference

A finalized HTML mockup (`index.html`) exists and should be used as the visual spec. Key design tokens:

- Font: IBM Plex Sans (UI) + IBM Plex Mono (metadata, counts, version strings)
- Borders: 0.5px, very subtle
- Radius: 6px (components), 10px (panels/cards)
- Colors: neutral warm grays, blue accent for active/selected states, green for publish actions
- Supports light and dark mode
- No gradients, no heavy shadows — flat and clean

---

## Build status

### Phase 1 — Foundation ✅
1. ✅ **Prism 2 plugin scaffold** — plugin class registers with Prism, hooks the library tab
2. ✅ **SQLite schema** — `assets`, `categories`, `tags`, `asset_tags`, `favorites`, `recently_used`

### Phase 2 — Data layer ✅
3. ✅ **DB read/write layer** (`core/db.py`) — full CRUD, batch queries for tags/versions/filetypes/favorites
4. ✅ **Asset discovery** (`core/scanner.py`) — NAS scan, version walking, category/DCC inference, stale cleanup

### Phase 3 — UI panel ✅
5. ✅ **Main Qt panel** (`ui/library_browser.py`) — sidebar + grid + inspector split layout
6. ✅ **Sidebar tree** — category/subcategory tree, live counts, Favorites/Recent; clicking filters the grid; subcategory click no longer collapses parent; hover uses 300ms text-color fade (no bg flash)
7. ✅ **Asset cards** — thumbnail, name/subtitle, star toggle, 2D/3D view mode toggle, draggable
8. ✅ **Toolbar** — search with inline tag pills + autocomplete, sort dropdown, size slider, filters dropdown, Import button
9. ✅ **Filters dropdown** — DCC / TYPE / FILE / INC / AUTH / PROJECT tabs, all additive
10. ✅ **Right-click context menu** — version picker, file type picker, View USD, View USD via Prism, Edit asset
11. ✅ **Inspector panel** (`ui/inspector.py`) — fullscreen preview, zoom/pan, asset metadata, version dropdown, ⋮ menu
12. ✅ **Import dialog** (`ui/publish_dialog.py`) — source, name, version, category + subcategory, file type, renderer, DCC, includes, tags

### Phase 4 — Asset ingestion ✅
13. ✅ **Import pipeline** (`core/importer.py`) — validate, copy to NAS, write DB, placeholder thumbnail, ImportThread
14. ✅ **Thumbnail generation** — manual browse in publish dialog + auto placeholder (colored + first letter)
15. ✅ **Edit asset** — pre-fill import dialog from DB, update metadata, right-click → Edit asset…

### Phase 5 — 3D view ⬜
16. ⬜ **3D asset preview** — inline 3D viewer for asset cards (rotate, zoom, pan)
17. ⬜ **3D view toggle** — switch between 2D thumbnail and 3D preview on cards

### Phase 6 — DCC integration ⬜
18. ⬜ **Drag and drop** — drag card into Houdini or Maya viewport via `core/dcc_bridge.py`
19. ⬜ **View USD** — launch usdview (or Houdini/Maya USD viewer)
20. ⬜ **View USD via Prism** — open through Prism's version browser
21. ⬜ **Houdini bridge** — Python API calls for import, reference, usdview
22. ⬜ **Maya bridge** — `maya.cmds` equivalent

---

## Qt / Windows rendering notes

Hard-won fixes to avoid re-breaking:

- **QMenu two-tone background** — always set `background: transparent` on `QMenu::item`; without it Windows paints item backgrounds natively at a different color than the menu frame.
- **QComboBox popup missing right border** — don't style `QAbstractItemView` with a border; instead override `showPopup`, find `self.view().parentWidget()` (the `QComboBoxPrivateContainer`), give it an object name, and style it with `#name { border: ... }`. Also set `QAbstractItemView { border: none }` and `QScrollBar { width: 0 }` in the same stylesheet.
- **QComboBox popup auto-scroll on first open** — call `self.view().setAutoScroll(False)` and `self.view().scrollToTop()` in `showPopup`.
- **Grid card sizing** — use `math.ceil((avail + GAP) / (card_w + GAP))` for column count so cards snap to a new column exactly when they reach `_card_width`, never exceeding it. For partial rows (fewer cards than `fit_cols`), skip the stretch and use `_card_width` directly.

---

## Environment variables

- `$ASSET_LIB` — points to NAS library root, baked into Houdini/Maya startup scripts
- All asset paths stored relative to `$ASSET_LIB`

---

## Open questions / deferred decisions

- Thumbnail generation strategy (auto-render vs manual screenshot on publish)
- Whether to use Prism's existing publish hooks or intercept earlier in the pipeline
- Permission enforcement — currently planned at filesystem level (NAS), not in the plugin itself

# TODO

## Asset Cards

- [x] **Right-click → Refresh asset** — re-scan and reload only that single asset card (thumbnail, metadata, versions) without triggering a full library refresh
- [x] **Wireframe overlay on thumbnail** — `#` toggle button composites the wire render on top of Material/Clay view using multiply blend; works on asset cards, inspector panel, and fullscreen preview; frame index stays in sync while scrubbing

## UI / UX

- [x] **Prism project browser UI is wrong** — fixed: was replacing Prism's corner widget (evicting the project selector); now wraps our button and the existing corner widget in a container so both sit at the top-right; button styled to match Prism's flat toolbar look
- [x] **Tray asset library should be on top** — moved to just below Prism's "Project Browser" entry; removed the Scan/Sync submenu; now a single direct "Asset Library" action
- [ ] **Changing between thumbnail types should keep the same frame** — when switching between Material / Clay / Wire render views on a card, the frame index should stay the same instead of resetting to 0

## Setup / Onboarding

- [ ] **Default library root path should be set before adding the plugin** — on first launch the library root is empty; need a first-run prompt or a fallback that guides the user to set `$ASSET_LIB` / root path before the browser tries to load
- [ ] **HDA `library_root` parameter should default automatically** — the Asset Publisher HDA's `library_root` parm is blank on creation; it should default to the configured library root path (from Prism config / `$ASSET_LIB`) so artists don't have to set it manually each time
- [x] **HDA Deadline submission — add priority and frames-per-task parameters** — Python wiring done & live from disk: `publish_action` → `submit_turntable_to_deadline` → `_submit_via_prism_deadline` → `submitHoudiniJob(jobPrio=priority, jobFramesPerTask=frames_per_task)`. **Remaining (direct on live HDA, via MCP or Type Properties):** add `deadline_priority` (default **5**, 0–100) + `deadline_frames_per_task` (default **6**, 1–72) in a "Deadline" folder on `Houdini/otls/object_AssetPublisher.2.0.hda`. (Templates also in `build_hda.py` as reference only.)

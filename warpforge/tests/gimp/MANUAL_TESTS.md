# Manual tests in GIMP

Automated part: `python tools/run_gimp_smoke.py` runs inside headless GIMP:
layer read/write, preview size, selection, mask, parasites (8-bit and 32-bit
float), the full Mesh Warp commit (new layer and in place, with a selection,
8-bit and 16-bit half float, native backend), the Puppet Warp commit, stored
effects (edit, show/hide, remove, XCF round trip) and calling the procedures
via the PDB.

The following need a person. Record GIMP version, OS and result.

| # | Scenario | Expected |
|---|---|---|
| 1 | RGB 8-bit layer → `Filters › Distorts › WarpForge…` | Dialog opens in Puppet mode, preview matches the layer, status line says "native renderer" |
| 2 | RGB 16-bit float image (`Image › Precision › 16 bit floating point`) | Same as 1; after Apply no banding (float commit) |
| 3 | Layer with a layer mask; also with the mask thumbnail active | Dialog opens for the owning layer; after Apply the mask is still there (not warped) |
| 4 | Rectangular selection, *Limit to selection* ticked → Apply | Only pixels inside the selection change |
| 5 | Same selection, *Limit to selection* unticked → Apply | Whole layer warped; selection still there afterwards |
| 6 | No image open / group selected / two layers selected | Greyed out / clear error, no crash |
| 7 | Right-click layer → `WarpForge: Puppet/Mesh Warp` | Same dialog |
| 8 | Scroll, middle-drag, Space+drag, Fit view | Zoom around pointer, pan, reset |
| 9 | Drag vertices quickly for a few seconds on a 4000×4000 layer | UI stays responsive; preview follows without piling up |
| 10 | Drag a vertex far across its neighbours | It stops before the mesh folds; corners never move; border vertices stay on the border |
| 11 | Ctrl+Z / Ctrl+Shift+Z in the dialog | Undo/redo whole drags, density changes and Reset |
| 12 | 4×4 → edit → choose 8×8 | Asks before discarding edits |
| 13 | Apply with *Output to a new layer* | New layer `<name> (WarpForge)` above, original hidden; **one** Edit › Undo restores everything |
| 14 | Apply in place | Layer warped; one Edit › Undo restores it |
| 15 | Esc / Cancel after edits | Image unchanged, nothing on the undo stack |
| 16 | 8000×8000 layer → Apply | Progress bar advances; finishes in seconds, memory stays reasonable |
| 17 | Remove `lib/warpforge/native/*.dll` (or `.so`) → run | Works with the Python renderer (320 px preview), status says "python renderer" |
| 18 | Apply → save XCF → close → reopen → select the WarpForge layer → WarpForge | Title says "Edit Effect", pins/mesh as left, preview built from the original |
| 19 | Flatpak GIMP on Linux | Plug-in appears after `tools/install.py --flatpak` |
| 20 | Puppet: click 3+ pins, drag one | Image deforms smoothly around it; the pin stays under the cursor; beyond the dashed circle nothing moves |
| 21 | Puppet: click on an already warped area | New pin appears, image does not jump |
| 22 | Stiffness 0% vs 100% with two pins pulled apart | 0%: region between stretches; 100%: it keeps its size |
| 23 | Select a pin, move *Pin radius* | Dashed circle and preview follow; one Ctrl+Z undoes the whole slider move |
| 24 | Double-click a pin | Popover: radius, weight, Restore position, Remove; edits show live; one Ctrl+Z undoes them |
| 25 | Shift+click two pins → Link pins (Ctrl+L), drag one | Both move together, cyan segment stays straight and same length; Unlink restores independence |
| 26 | Delete / Ctrl+A / Reset twice | Removes selected; selects all; first Reset restores positions, second removes all pins |
| 27 | Typing in the popover's spin buttons | Delete/Backspace/Space edit the number, they do not remove pins or show the original |
| 28 | Puppet → Apply (new layer and in place) | Same as 13/14: one undo step, original untouched by default |
| 29 | Switch Puppet ↔ Mesh with edits in both | Each mode keeps its edits and its own undo history; Apply uses the visible mode |
| 30 | Edit an effect, move a pin, Apply | Same WarpForge layer updated (no third layer); one Edit › Undo restores the previous warp |
| 31 | Layers menu › WarpForge: Show/Hide Effect on the result, then on the original | Swaps which of the two is visible; each is one undo step |
| 32 | Layers menu › WarpForge: Remove Effect | WarpForge layer gone, original visible; Edit › Undo brings it back |
| 33 | WarpForge: Edit Effect… on a normal layer | Clear message, nothing changes |
| 34 | Effect applied in place, open WarpForge on it | Note says it cannot be edited; a new warp applies on top |
| 35 | Save preset… then Load preset… on another layer of a different size | Asks to scale; result matches proportionally; Ctrl+Z undoes the load |
| 36 | Load a broken JSON / a file from a newer WarpForge | Clear error dialog, dialog stays usable |
| 37 | Scale the original layer (Layer › Scale) then edit its effect | Note about scaling; Apply rebuilds the WarpForge layer at the new size |

# MHUR VFX Color Swapper v2.3.0

A Windows tool for recoloring My Hero Ultra Rumble character effects, adjusting
particle amount, and exporting `.pak` mods. Includes native character cards,
two-color mode, saved themes, and game update checks.

## What's new in 2.3.0

- **Exact color mode is the default.** The picked color is applied at full strength (picked hue *and* saturation); "Shift hue" is still available for keeping color variety. Target brightness is now applied in linear light, so a picked grey/dark color comes out as that color in game instead of lighter.
- **Skill levels.** Effects named `_L1/_L2/_L3` (and `Gasha_` max-level variants) are handled per level: max level (L3, level 9 in game) gets exactly your color, lower levels get a slightly different shade. Adjust with *Lower-level difference* (0% = identical).
- **Two-color fixes.** Part detection now matches whole words (`White` is no longer "hit", `Lightning` is no longer a light). The preview shows how many color fields go to the main and second color and warns about very dark second colors, empty splits and shared materials.
- **Several overrides touching the same file** no longer overwrite or remove each other's changes.
- **Second color effect amount.** Two-color mode has its own particle-amount slider for the parts you assign to the second color; the main *Effect amount* slider then controls the rest.
- **Reworked interface.** Numbered, collapsible sidebar steps; color presets and recent colors; before/after palette preview; segmented color-mode switch and toggle switches; breadcrumb navigation; in-app dialogs instead of browser pop-ups; keyboard support (Enter on cards, Esc to go back/close, `/` to search, arrow keys in the color picker); a slide-in control drawer on narrow windows; light-theme contrast fixes.
- **Error log.** Unexpected errors are written to `logs/errors.log` in the data folder (the windowed EXE has no console), so bug reports can include details.
- Server hardening for rename and groups requests; new regression tests.

[Download the latest Windows release](https://github.com/ASTRO45366/MHUR-VFX-Color-Swapper/releases/latest).

## Run the standalone EXE

1. Extract the release ZIP into a writable folder, or put the EXE in its own folder.
2. Run `MHUR_VFX_Color_Swapper.exe`. It opens a local interface in your browser.
3. Select **Set up from installed game**. Confirm the detected MHUR installation,
   or paste your game or `HerovsGame/Content/Paks` folder.
4. Click **Update from game files**. The first import takes a few minutes and
   needs temporary extraction space. The app stores a compressed local cache.

The EXE contains the app, Python runtime, and the two game-reading tools. You
need the installed game to import its assets. There is no Python installation,
installer, or separate asset download for normal use. The game is read only.
The first import replaces any incompatible cache from an older edition; your
settings, custom loose imports, and saved exports are kept. Future archive or
key changes may require a reader update or a current local key in Settings.

## Use the app

- Choose a character, variation, and effect group. Set colors and effect amount.
- Add selected effect overrides, or apply the current settings to all included
  characters. The export dialog reports unsupported or shared effect fields.
- Exported mods go in `exports/` beside the EXE. ASTRO attribution is stored in
  `ModCredits/ASTRO/.../credits.json` inside each generated `.pak`.
- **Settings → Game updates** can check for changed game files on startup and
  discover complete new characters. Unchanged files reuse the local cache.
- The palette is a color preview. At amount 0, supported particle spawns stop;
  not every game-driven visual can be hidden. Test exported mods in-game.

The app serves its UI on loopback (`127.0.0.1`), reads local game archives, and
writes local settings, caches and exports. The app does not upload game files.
The release and source ZIPs contain no game PAKs, character artwork, extracted
particle assets, settings, or user-generated mods.

## Read the source

| Path | What it does |
| --- | --- |
| `MHUR_VFX_Recolor.py` | Launches the local server and opens the browser window. |
| `web/index.html` | Character gallery, effect controls, preview, and settings UI. |
| `server.py` | Loopback HTTP endpoints and background jobs. |
| `core/game_update.py` | Reads installed game archives and builds a local asset cache. |
| `core/library.py` | Reads the bundled-format cache and optional loose assets. |
| `core/engine.py` | Maps the selected characters and settings to asset changes. |
| `core/uasset.py`, `recolor.py`, `parts.py`, `amount.py` | Parse and modify effect data. |
| `core/pak.py`, `credits.py` | Write mod PAKs and embed attribution. |
| `MHUR_VFX_Recolor.spec`, `BUILD_EXE.bat` | Build one Windows EXE with `converter.ico`. |
| `tools/`, `licenses/` | Exact reader binaries used in the build and their notices. |

Optional custom game keys are stored locally in `settings.json`. The game reader
also contains a built-in default for supported game archives. The ZIP contains
no local settings or custom keys. See `THIRD_PARTY.md` for binary provenance,
versions, upstream source links, and the distinction between the app's license
and third-party components.

## Run and rebuild from source

Use Windows x64 and [Python 3.12](https://www.python.org/downloads/). From the
extracted source folder, `py -3.12 MHUR_VFX_Recolor.py` runs the source directly.
The app uses Python's standard library; the requirements below are for building.

```powershell
py -3.12 -m pip install -r requirements-build.txt
.\BUILD_EXE.bat
```

The output is `dist/MHUR_VFX_Color_Swapper.exe`. The build spec packages the
exact reader binaries from `tools/` and embeds the icon and version metadata.
This release was built with CPython 3.12.14 and the pinned PyInstaller toolchain.
Rebuilds can have different file hashes because the build environment and
Windows executable metadata can differ. No signing certificate is included.

## Tests and release checksum

```powershell
py -3.12 -m unittest discover -v
```

Tests that require real effects skip until you supply a local cache. To run all
checks after a first import, set `MHUR_VFX_TEST_DATA` to the folder containing
`game-update.json` and `game-updates/`, then run the same command. The tests copy
the fixture cache to a temporary directory and don't edit the original cache.

```powershell
$env:MHUR_VFX_TEST_DATA = 'C:\Path\To\Your\VFXApp'
py -3.12 -m unittest discover -v
```

The release ZIP includes `SHA256.txt` for the EXE. To compare it on Windows:

```powershell
Get-FileHash -Algorithm SHA256 .\MHUR_VFX_Color_Swapper.exe
```

## License

The original app code, documentation, tests, and build files are provided under
[the MIT license](LICENSE), copyright 2026 ASTRO. The project icon is included
for the build. Third-party components retain their own licenses. Locally
extracted MHUR game content is outside the app's code license.

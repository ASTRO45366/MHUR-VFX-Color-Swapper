# MHUR VFX Color Swapper v2.2.0

A Windows tool for recoloring My Hero Ultra Rumble character effects, adjusting
particle amount, and exporting `.pak` mods. Includes native character cards,
two-color mode, saved themes, and game update checks.

[Download the latest Windows release](https://github.com/ASTRO45366/MHUR-VFX-Color-Swapper/releases/latest).
Choose the standalone EXE or the release ZIP with instructions and licenses.
The release page also provides the source ZIP and download checksums.

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

## Antivirus review

The Windows EXE is unsigned. Its initial VirusTotal scan on November 3, 2026
reported detections from Arctic Wolf, Bkav Pro, CrowdStrike Falcon, and SecureAge.
Suspected false-positive reports were submitted to all four vendors. Review is
pending. The release page includes checksums for the EXE and download archives.

The published EXE has SHA-256
`becbbad84c5bb1c81a7c2990d7254c13478f26b65b3b2f0b4e03b1e4a2823b06`.
[View the VirusTotal report](https://www.virustotal.com/gui/file/becbbad84c5bb1c81a7c2990d7254c13478f26b65b3b2f0b4e03b1e4a2823b06/detection).

## Gameplay scope

An audit of this EXE and 9,932 locally imported effect/material assets found
changes limited to particle colors, lighting, and particle spawning. A sample
export contained effect/material assets and attribution metadata. No hitbox,
damage, range, cooldown, movement, or targeting changes were found.

Brighter colors and optional enemy/friend area indicator recoloring can make
attacks or danger zones easier to notice. Live gameplay behavior was not tested.

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

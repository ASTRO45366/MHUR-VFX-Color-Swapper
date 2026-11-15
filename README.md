# MHUR VFX Color Swapper v2.6.3

A Windows tool for recoloring My Hero Ultra Rumble character effects, adjusting
particle amount, and exporting `.pak` mods. Includes native character cards,
two-color mode, saved themes, and game update checks.

[Download the latest Windows release](https://github.com/ASTRO45366/MHUR-VFX-Color-Swapper/releases/latest).

## What's new in 2.6.3

- **Better in-game performance.** Paks are now written **uncompressed** by default, so the game reads effects and textures directly instead of decompressing them during a match (texture streaming especially). Files are larger (an all-characters two-colour pak is roughly 60 MB instead of 8 MB) but look exactly the same. *Compress exported paks* in ⚙ Settings brings back small files.
- Tips for even more FPS without changing the look much: untick *Included in pak* for characters you never see, and lower *Effect amount* a little (80–90 % fades the extra particles proportionally).

## What's new in 2.6.2

- **Fixed for good: "Safety check stopped the export … not an effect asset".** Particle systems are always treated as effects, effect-named materials/textures (`MI_ef_…`, `T_ef_…`) count wherever the game stores them, and if a character model / outfit / prop material is ever reached through an effect it is simply left out of the pak instead of stopping the export. The check still stops an export if anything other than colours or particle amounts would change.

## What's new in 2.6.1

- **Fixed: "Safety check stopped the export … not an effect asset"** for effects that are not stored in an `Effect` folder (e.g. Shigaraki's third variation). Effect files are now recognised by name and folder (`PS_…`, `…_ef_…`, Effect/VFX/Particle folders), while character model, outfit, costume, prop and master materials are still never touched.
- **Removed the outline recolor option.**

## What's new in 2.6.0

- **Fixed: characters turning green (or any picked colour).** Some effects reuse a character's model materials, and those inherit from the shared character master material. Recoloring them tinted the character itself and, through the master material, every character. Now only files inside a character's `Effect` folders are ever recolored (materials and textures); model, outfit, prop and master materials are skipped, and the export safety check refuses them. **Re-export and reinstall your mods** (and remove old paks made with 2.5.x) to get rid of the green.
- **Blueprint-spawned effects are recolored too.** Ground decals, post-process overlays and gate meshes that no particle system references (e.g. Shigaraki's decay cracks, Kurogiri's warp gate) are now part of the library and assigned to their skill by name or material family (else *Other* / *All Effects*). Run **Update from game files** once so the library picks them up.
- **Two colours on solid objects.** With a second colour, ice/stone keeps the main colour on its body and blends to the second colour on its highlights (along the colour wheel, so there is no grey band).

## What's new in 2.5.1

- **Solid objects match the picked colour.** Texture recolor is calibrated: the texture's typical colour becomes exactly the chosen colour (brightness included), while highlights and shadows keep their detail. Ice and rock no longer come out lighter than the picked colour.
- **Glowing cracks.** Emissive (glow) colour textures and glow/crack/lava colour settings are now recolored with solid objects (e.g. the glowing lines in Shigaraki's cracks).
- **Diagnostic report.** *Colors not changing? Save a report for the developer…* (under 2 · Effect) saves a text file listing the skill's materials, colour settings and textures and what the app recolors, so missing parts can be fixed quickly.

## What's new in 2.5.0

- **Install into game** now puts mods in `HerovsGame\Content\Paks\Mods\MHUR VFX Color Swapper` (created if needed). A copy an older version put in `Paks\~mods` is removed so the mod is not loaded twice, and an empty `~mods` folder is deleted.
- **Recolor solid objects (ice, stone, cracks, spikes).** These moves get their look from textures, so a normal effect recolor left them in their original colours. The app can now recolor a move's own colour textures (DXT1/DXT5/BC7, in place, same size): every texel keeps its brightness and detail, only the colour changes. Normal maps, masks and packed data textures are never touched.
  - **On by default** for Shigaraki's alpha/beta/gamma (the decay cracks), every variation.
  - **Off by default** everywhere else: switch on *Recolor solid objects* in **4 · Style** for the skill you want (e.g. Strike Kirishima gamma, Shoto's ice, both Overhaul sets, Cementoss alpha/beta/gamma/special). Your choice is remembered per skill and used by *Generate pak for ALL characters* too.
  - Textures are read from your installed game when needed (set the game folder in ⚙ Settings) and cached in `MHUR VFX Swapper Data/texture-cache`; the cache refreshes automatically after a game update.
  - The cosmetic-only safety check covers textures as well: only pixel data may change.

## What's new in 2.4.0

- **App no longer quits on its own.** It used to close itself when the window had been in the background for a few minutes (browsers slow down hidden windows), e.g. while playing. It now closes only when you close its window.
- **Game update never hangs on a loading screen.** Live file progress and elapsed time while extracting, a **Cancel game update** button (also for the automatic update at start-up), and a reader that stops making progress is stopped after 10 minutes with a clear message. The previous library is always kept.
- **Own data folder.** The EXE keeps everything it writes (exports, settings, game data, caches, logs) in `MHUR VFX Swapper Data` beside it; files from older versions are moved there automatically.
- **Pak names** always start with `ZZZ` (loads after the game's own paks) and end with `-WindowsNoEditor_P.pak`; the sidebar shows the final file name as you type.
- **No accidental all-character exports.** *Generate pak for ALL characters…* is now a small button that asks for confirmation; *Add override* / *Export overrides* are the main actions.
- **Friendlier export result.** One-click **Install into game** (copies the pak to `Paks\Mods\MHUR VFX Color Swapper`; clear message if the game is running and locks it). Missing-material lists and other technical notes moved into a collapsed *Details* section; a short tip appears only when updating from game files would actually help.
- **BUILD_EXE.bat** installs the build tools itself and opens the finished EXE's folder.

## What's new in 2.3.0

- **Exact color mode is the default.** The picked color is applied at full strength (picked hue *and* saturation); "Shift hue" is still available for keeping color variety. Target brightness is now applied in linear light, so a picked grey/dark color comes out as that color in game instead of lighter.
- **Skill levels.** Effects named `_L1/_L2/_L3` (and `Gasha_` max-level variants) are handled per level: max level (L3, level 9 in game) gets exactly your color, lower levels get a slightly different shade. Adjust with *Lower-level difference* (0% = identical).
- **Two-color fixes.** Part detection now matches whole words (`White` is no longer "hit", `Lightning` is no longer a light). The preview shows how many color fields go to the main and second color and warns about very dark second colors, empty splits and shared materials.
- **Several overrides touching the same file** no longer overwrite or remove each other's changes.
- **Second color effect amount.** Two-color mode has its own particle-amount slider for the parts you assign to the second color; the main *Effect amount* slider then controls the rest.
- **Exact colors on more effects.** GPU particle emitters (colors baked into the emitter's GPU data, ignored by the old particle-color edit) are now recolored, and more material color parameters are recognised (`C1`/`C2`, `EM_magma`, `Fresnel_*`, `Screen_EM`, generic `Param` colors). Skill levels named `_LVL1/_LVL4/_LVL9` and `_L01–_L03` are handled like `_L1–_L3`.
- **Particle amount is proportional.** Single-particle effects (flame meshes, beams, slashes) used to vanish below 50 %; they now keep one particle and fade by the missing share, so 40 % looks like 40 %. Only 0 % makes an effect invisible.
- **Walking dust kept original by default.** Walk/run/landing/jump dust in the *Other* group is skipped unless *Recolor walking dust* is on.
- **Cosmetic-only guarantee.** Every export is checked byte by byte: only colour values and particle spawn amounts of effect assets may change (no hitbox, collision, animation, size, speed or lifetime data), otherwise no pak is written. Enemy/ally indicator colours inside effect materials also follow the *Recolor area indicators* switch.
- **Reworked interface.** Numbered, collapsible sidebar steps; color presets and recent colors; before/after palette preview; segmented color-mode switch and toggle switches; breadcrumb navigation; in-app dialogs instead of browser pop-ups; keyboard support (Enter on cards, Esc to go back/close, `/` to search, arrow keys in the color picker); a slide-in control drawer on narrow windows; light-theme contrast fixes.
- **Error log.** Unexpected errors are written to `MHUR VFX Swapper Data/logs/errors.log` (the windowed EXE has no console), so bug reports can include details.
- Server hardening for rename and groups requests; new regression tests.

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
- Exported mods go in `MHUR VFX Swapper Data/exports/` beside the EXE. ASTRO attribution is stored in
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

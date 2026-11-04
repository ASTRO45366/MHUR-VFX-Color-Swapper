# Third-party components

The source ZIP includes the exact reader binaries that the EXE packages. These
are separate from the MIT-licensed app code. See `licenses/` for notices.

| Component | Version | Upstream | Notice |
| --- | --- | --- | --- |
| repak CLI | 0.2.3 | [trumank/repak](https://github.com/trumank/repak) | `licenses/repak-MIT.txt` |
| UE Viewer / UModel | build 1590 | [UModel](https://www.gildor.org/en/projects/umodel), [source](https://github.com/gildor2/UEViewer) | `licenses/UModel-MIT.txt` |
| SDL2 | 2.0.10 | [SDL source](https://github.com/libsdl-org/SDL) | `licenses/SDL2.txt` |
| CPython runtime | 3.12.14 in this build | [CPython](https://github.com/python/cpython) | `licenses/Python.txt` |
| PyInstaller bootloader | 6.22.3 | [PyInstaller](https://github.com/pyinstaller/pyinstaller) | `licenses/PyInstaller.txt` |

The Windows readers were taken from the existing local modding toolchain;
`READER_SHA256.txt` records the exact files included. PyInstaller also carries
required Windows runtime DLLs from the build environment. The source archive
includes the app's own code and build recipe; the external tools' upstream
source is available at the links above.

No game PAK, native character picture, or extracted gameplay/effect asset is
included. Portraits, effects and game caches are created locally from the
user's installation. The app is an independent modding tool.

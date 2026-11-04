# Public one-file build. Game assets are imported locally and never bundled here.
a = Analysis(
 ['MHUR_VFX_Recolor.py'], pathex=[], binaries=[],
 datas=[('web', 'web'), ('converter.ico', 'web'), ('tools', 'tools'), ('licenses', 'licenses'), ('LICENSE', '.')],
 hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
 excludes=['tkinter', 'unittest', 'pydoc', 'doctest'], noarchive=False, optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
 pyz, a.scripts, a.binaries, a.datas, [], name='MHUR_VFX_Color_Swapper',
 debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
 console=False, disable_windowed_traceback=False, icon='converter.ico',
 version='version_info.txt',
)

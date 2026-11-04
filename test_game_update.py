"""Character roster and update safety checks, including a future unknown ID."""
import json,os,tempfile,unittest,zipfile
from pathlib import Path
from core.game_update import discover,original_paks,read_manifest,write_bundle,GameUpdater
from core.engine import Engine
from core.library import Library
from test_fixture import open_test_engine

ROOT=Path(__file__).resolve().parent

class GameUpdateTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.engine=open_test_engine(cls)
 def test_all_current_cards_have_native_portraits_and_names(self):
  characters=self.engine.characters()
  if not characters:self.skipTest('Set MHUR_VFX_TEST_DATA to a locally imported game library')
  self.assertIn('Ch001',{c['id'] for c in characters})
  self.assertNotIn('Ch093',{c['id'] for c in characters})
  self.assertTrue(all(c['portrait'] for c in characters))
 def test_future_complete_character_is_discovered_but_npc_is_not(self):
  root='HerovsGame/Content/Character/'
  entries={root+'Ch999/'+name:'base.pak' for name in (
   'PA_Ch999.uasset','Blueprints/BP_Ch999Default.uasset',
   'Effect/Effect/PS_Ch999_skill01.uasset','GUI/Costume/L/T_ui_Thumb_4_999000000_L.uasset')}
  entries[root+'Ch093/PA_Ch093.uasset']='base.pak'
  entries[root+'Ch093/GUI/FaceIcon/T_ui_com_cahraface_Ch093.uasset']='base.pak'
  active,assets,portraits=discover(entries)
  self.assertEqual(active,['Ch999']);self.assertIn('Ch999',portraits)
 def test_only_original_archives_are_scanned(self):
  with tempfile.TemporaryDirectory() as folder:
   for name in ('HerovsGame-WindowsNoEditor.pak','HerovsGame-WindowsNoEditor_1_P.pak','UserMod_P.pak'):
    (Path(folder)/name).write_bytes(b'')
   (Path(folder)/'Mods').mkdir();(Path(folder)/'Mods/HerovsGame-WindowsNoEditor.pak').write_bytes(b'')
   self.assertEqual(len(original_paks(folder)),2)
 def test_invalid_manifest_cannot_escape_data_directory(self):
  with tempfile.TemporaryDirectory() as folder:
   (Path(folder)/'game-update.json').write_text(json.dumps({'generation':'../../escape','characters':['Ch001']}))
   self.assertIsNone(read_manifest(folder)[1])
 def test_overlay_loads_new_character_assets_without_loose_files(self):
  if 'Ch001' not in self.engine.lib.characters():self.skipTest('Set MHUR_VFX_TEST_DATA to a locally imported game library')
  original=next(r for r in self.engine.lib.recs.values() if r.kind=='ps' and r.char=='Ch001')
  asset=self.engine.lib.read(original)
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'staging';source.mkdir()
   stem=original.name.replace('Ch001','Ch999')
   ua,ux=source/(stem+'.uasset'),source/(stem+'.uexp')
   ua.write_bytes(asset.ua.replace(b'Ch001',b'Ch999'));ux.write_bytes(asset.ux)
   record=Library(source)._parse(ua,ux);self.assertIsNotNone(record)
   generation=root/'game-updates/new';generation.mkdir(parents=True)
   write_bundle(generation/'library.zip',[record]);(generation/'portraits').mkdir()
   (generation/'portraits/Ch999.png').write_bytes(b'portrait-test')
   (root/'game-update.json').write_text(json.dumps({'generation':'new','characters':['Ch001','Ch999'],'library_base':'local-only'}))
   engine=Engine(root,ROOT/'library.zip');engine.load()
   self.assertIn('Ch999',{c['id'] for c in engine.characters()})
   loaded=engine.lib.read(engine.lib.recs[record.pkg]);self.assertEqual(loaded.ua,ua.read_bytes())
   self.assertTrue(all(not isinstance(r.ua,Path) for r in engine.lib.recs.values()))
   self.assertEqual(engine.portrait_path('Ch999').name,'Ch999.png')
   if engine.lib._update_reader:engine.lib._update_reader.archive.close()
   if engine.lib.archive:engine.lib.archive.close()
 def test_previous_delta_without_its_base_is_not_loaded(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);generation=root/'game-updates/previous';generation.mkdir(parents=True)
   write_bundle(generation/'library.zip',[])
   (root/'game-update.json').write_text(json.dumps({'generation':'previous','characters':['Ch001']}))
   engine=Engine(root);engine.load()
   self.assertIsNone(engine.lib.update_archive)
   self.assertEqual(engine.characters(),[])
 def test_failed_game_path_keeps_previous_library(self):
  with tempfile.TemporaryDirectory() as folder:
   engine=Engine(Path(folder),ROOT/'library.zip');engine.load();before=set(engine.lib.recs)
   with self.assertRaises(ValueError):GameUpdater(engine,ROOT/'tools').run(str(Path(folder)/'missing'))
   self.assertEqual(before,set(engine.lib.recs));self.assertFalse((Path(folder)/'game-update.json').exists())
   if engine.lib.archive:engine.lib.archive.close()

if __name__=='__main__':unittest.main(verbosity=2)

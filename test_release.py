"""Release checks for embedded credits, portable preferences and atomic pak output."""
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from preferences import Preferences, THEMES
from core.pak import read_pak, write_pak
from server import App, serve
from test_fixture import open_test_engine

class ReleaseTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.eng=open_test_engine(cls)
 def test_credit_is_inside_real_mod_and_matches_asset_digest(self):
  eng=self.eng
  if 'Ch017' not in eng.lib.characters():self.skipTest('Set MHUR_VFX_TEST_DATA to a locally imported game library')
  a=dict(char='Ch017',var='base',group='alpha',hex='#44AAFF',mode='unify',amount=50)
  out,rep=eng.build([a],'TEST_credit')
  self.addCleanup(lambda:out.unlink(missing_ok=True))
  _,files=read_pak(out)
  paths=[n for n in files if n.startswith('ModCredits/ASTRO/')]
  self.assertEqual(len(paths),1)
  credit=json.loads(files.pop(paths[0]))
  self.assertEqual(credit['watermark'],'ASTRO')
  digest=hashlib.sha256()
  for name in sorted(files):
   digest.update(name.encode()+b'\0');digest.update(hashlib.sha256(files[name]).digest())
  self.assertEqual(credit['content_sha256'],digest.hexdigest())
  self.assertEqual(rep['assets'],len(files)//2)
  self.assertNotIn(str(Path.home()),json.dumps(credit))
 def test_preferences_persist_all_themes_and_reject_invalid_values(self):
  with tempfile.TemporaryDirectory() as folder:
   for theme in THEMES:
    settings=Preferences(folder);settings.update({'theme':theme,'compact':True,'reduce_motion':True})
    self.assertEqual(Preferences(folder).read()['theme'],theme)
   before=(Path(folder)/'settings.json').read_bytes()
   for invalid in ({'theme':'no-such-theme'},{'compact':'false'},{'unexpected':1}):
    with self.assertRaises(ValueError):settings.update(invalid)
    self.assertEqual((Path(folder)/'settings.json').read_bytes(),before)
 def test_damaged_preferences_recover(self):
  with tempfile.TemporaryDirectory() as folder:
   (Path(folder)/'settings.json').write_text('{bad')
   self.assertEqual(Preferences(folder).read()['theme'],'midnight')
 def test_streaming_pak_roundtrip_and_atomic_failure(self):
  with tempfile.TemporaryDirectory() as folder:
   out=Path(folder)/'test.pak'
   payload={'large.bin':bytes(range(256))*1024,'empty.txt':b'','credits.txt':b'ASTRO'}
   write_pak(out,'../../../HerovsGame/Content/',payload)
   self.assertEqual(read_pak(out)[1],payload)
   before=out.read_bytes()
   with self.assertRaises(TypeError):write_pak(out,'/',{'ok':b'ok','broken':object()})
   self.assertEqual(out.read_bytes(),before)
   self.assertEqual(list(Path(folder).iterdir()),[out])
 def test_local_http_settings_and_origin_check(self):
  with tempfile.TemporaryDirectory() as folder:
   app=App(folder);srv=serve(app);worker=threading.Thread(target=srv.serve_forever,daemon=True);worker.start()
   base=f'http://127.0.0.1:{srv.server_port}'
   try:
    req=urllib.request.Request(base+'/api/settings',data=b'{"theme":"ocean"}',method='POST')
    with urllib.request.urlopen(req) as r:self.assertEqual(json.load(r)['theme'],'ocean')
    self.assertEqual(Preferences(folder).read()['theme'],'ocean')
    for headers in ({'Origin':'https://example.invalid'},{'Host':'example.invalid'}):
     with self.assertRaises(urllib.error.HTTPError) as caught:
      urllib.request.urlopen(urllib.request.Request(base+'/api/settings',headers=headers))
     self.assertEqual(caught.exception.code,403)
   finally:
    srv.shutdown();srv.server_close();worker.join()

if __name__=='__main__':unittest.main(verbosity=2)

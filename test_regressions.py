"""Regression tests; set MHUR_VFX_TEST_DATA for real-asset coverage."""
import json
import struct
import unittest
from pathlib import Path
from core.engine import Engine, MOUNT
from core.recolor import Swap
from core.amount import apply_amount
from core.pak import read_pak
from test_fixture import open_test_engine

ROOT=Path(__file__).resolve().parent

class RegressionTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.eng=open_test_engine(cls)
 def assignment(self,**kw):
  return dict(dict(char='Ch017',var='base',group='alpha',hex='#FF0000',mode='unify',intensity=1,amount=100,tint_white=True,indicators=False),**kw)
 def test_original_amount_100_is_noop_for_all_characters(self):
  if 'Ch001' not in self.eng.lib.characters():self.skipTest('Set MHUR_VFX_TEST_DATA to a locally imported game library')
  out,report=self.eng.build([], 'TEST_noop',global_cfg=dict(hex='#FF0000',mode='original',amount=100,intensity=1))
  self.assertIsNone(out);self.assertEqual(report['assets'],0)
 def test_two_color_fields_and_preview(self):
  if 'Ch017' not in self.eng.lib.characters():self.skipTest('Set MHUR_VFX_TEST_DATA to a locally imported game library')
  a=self.assignment(secondary=dict(hex='#00FF00',parts=['trail','smoke','impact']))
  selected,_=self.eng._selection(a)
  p,s=self.eng._selected_entries(selected)
  self.assertTrue(p);self.assertTrue(s)
  colors=self.eng.preview(a)
  self.assertIn('#00FF00',colors)
  self.assertTrue(any(c.startswith('#FF') for c in colors))
 def test_export_pak_matches_two_color_and_amount_patches(self):
  if 'Ch017' not in self.eng.lib.characters():self.skipTest('Set MHUR_VFX_TEST_DATA to a locally imported game library')
  a=self.assignment(amount=50,secondary=dict(hex='#00FF00',parts=['trail','smoke','impact']))
  out,report=self.eng.build([a],'TEST_two_color_amount')
  self.addCleanup(lambda:out.unlink(missing_ok=True))
  mount,files=read_pak(out)
  self.assertEqual(mount,MOUNT)
  self.assertGreater(report['secondary_fields'],0);self.assertGreater(report['amount_assets'],0)
  selected,_=self.eng._selection(a)
  sp,ss=self.eng._swaps(a,*self.eng._selected_entries(selected))
  for r,asset,fs in selected:
   expected=bytearray(asset.ux)
   for f in fs:f.apply(expected,ss if f.secondary else sp)
   if r.kind=='ps':apply_amount(asset,expected,50)
   rel=r.pkg.replace('/Game/','',1)
   if expected!=asset.ux:
    self.assertEqual(files[rel+'.uexp'],bytes(expected))
    self.assertEqual(files[rel+'.uasset'],asset.ua)
   else:self.assertNotIn(rel+'.uexp',files)
 def test_exclusion_also_removes_queued_override(self):
  out,report=self.eng.build([self.assignment()],'TEST_exclude',exclude={'Ch017'})
  self.assertIsNone(out);self.assertEqual(report['assignments'],0)
 def test_invalid_amount_rejected(self):
  for v in (-1,101,float('nan'),float('inf')):
   with self.assertRaisesRegex(ValueError,'amount'):self.eng.preview(self.assignment(amount=v))
 def test_secondary_brightness_and_white(self):
  self.assertEqual(Swap('#FFFFFF','unify',None,.5,True)((1,1,1)),(.5,.5,.5))
  self.assertEqual(Swap('#000000','unify',None,1,True)((1,0,0)),(0,0,0))
  self.assertEqual(Swap('#FF0000','unify',None,.5,False)((1,1,1)),(.5,.5,.5))
 def test_amount_zero_and_half_spawn_counts(self):
  if 'Ch001' not in self.eng.lib.characters():self.skipTest('Set MHUR_VFX_TEST_DATA to a locally imported game library')
  r=next(r for r in self.eng.lib.recs.values() if r.kind=='ps' and r.char=='Ch001')
  asset=self.eng.lib.read(r)
  zero,half=bytearray(asset.ux),bytearray(asset.ux)
  apply_amount(asset,zero,0);apply_amount(asset,half,50)
  counts=0
  for i,e in enumerate(asset.exports):
   if e['class']!='ParticleModuleSpawn':continue
   for p in asset.export_props(i):
    if p.name!='BurstList':continue
    for burst in p.children or []:
     for c in burst.children or []:
      if c.name in ('Count','CountLow'):
       old=struct.unpack_from('<i',asset.ux,c.vpos)[0]
       z=struct.unpack_from('<i',zero,c.vpos)[0]
       h=struct.unpack_from('<i',half,c.vpos)[0]
       self.assertEqual(z,0 if old>=0 else old)
       self.assertEqual(h,int(old*.5+.5) if old>=0 else old)
       counts+=1
  self.assertGreater(counts,0)

if __name__=='__main__':unittest.main(verbosity=2)

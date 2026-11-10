"""Regression tests; set MHUR_VFX_TEST_DATA for real-asset coverage."""
import json
import struct
import unittest
from pathlib import Path
from core.engine import Engine, MOUNT, part_of, level_steps
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
   for f in fs:f.apply(expected,self.eng.field_swap(a,f,sp,ss))
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


 def test_part_names_use_whole_words(self):
  for name,part in (('PS_Ch115_SignArea_White_00','main'),('PS_Ch115_SP_Lightning_00','main'),
    ('PS_Ch001_attack01_trail_00','trail'),('PS_Ch001_skill_debri_00','smoke'),
    ('PS_Ch001_Attack_light','light'),('PS_Ch115_Attack2Light_00','light'),('PS_Ch017V1_skill02_Body_00_L1','aura')):
   self.assertEqual(part_of(name),part,name)
 def test_level_steps(self):
  self.assertEqual([level_steps(n) for n in ('PS_x_L3','PS_x_L2_BP','PS_Gasha_x_L4','MI_x_L1_00','PS_x_Impact_00')],[0,1,0,2,None])
 def test_unify_is_exact_and_lower_levels_differ(self):
  import colorsys
  from core.recolor import analyse,hex_to_rgb
  sw=Swap('#8A2BE2','unify',(0.05,0.9),1.0,True)
  th=colorsys.rgb_to_hsv(*hex_to_rgb('#8A2BE2'))
  for src in ((1,.2,.02),(.1,.5,.9),(3,3,3)):
   out=sw(src);_,h,s=analyse(out)
   self.assertAlmostEqual(h,th[0],places=3)
   if src!=(3,3,3):self.assertAlmostEqual(s,th[1],places=3)
  hi=analyse(sw((1,.2,.02)))
  lo=analyse(sw.variant(2,.6)((1,.2,.02)))
  self.assertNotAlmostEqual(hi[1],lo[1],places=2)
  self.assertIs(sw.variant(0,.6),sw);self.assertIs(sw.variant(2,0),sw)
 def test_linear_brightness_of_target(self):
  from core.recolor import s2l
  out=Swap('#808080','unify',None,1.0,True)((1,1,1))
  self.assertAlmostEqual(max(out),s2l(128/255),places=3)
 def test_assignments_keep_each_others_patches(self):
  if 'Ch017' not in self.eng.lib.characters():self.skipTest('Set MHUR_VFX_TEST_DATA to a locally imported game library')
  a=self.assignment(group='all');b=self.assignment(group='alpha',mode='original')
  out,_=self.eng.build([a,b],'TEST_overlap');self.assertIsNotNone(out)
  self.addCleanup(lambda:out.unlink(missing_ok=True))
  out2,_=self.eng.build([a],'TEST_overlap_ref');self.addCleanup(lambda:out2.unlink(missing_ok=True))
  assets=lambda path:{k:v for k,v in read_pak(path)[1].items() if k.endswith(('.uasset','.uexp'))}
  got,want=assets(out),assets(out2)
  self.assertTrue(want);self.assertEqual(got.keys(),want.keys())
  self.assertTrue(all(got[k]==want[k] for k in want))
 def test_invalid_level_spread_rejected(self):
  for v in (-1,101,float('nan')):
   with self.assertRaisesRegex(ValueError,'level_spread'):self.eng.preview(self.assignment(level_spread=v))

 def test_second_color_amount_only_touches_second_color_emitters(self):
  if 'Ch017' not in self.eng.lib.characters():self.skipTest('Set MHUR_VFX_TEST_DATA to a locally imported game library')
  from core.parts import emitter_parts
  from core.engine import part_of
  a=self.assignment(group='all',mode='original',amount=100,secondary=dict(hex='#00FF00',parts=['trail','smoke'],amount=0))
  out,rep=self.eng.build([a],'TEST_second_amount');self.assertIsNotNone(out)
  self.addCleanup(lambda:out.unlink(missing_ok=True))
  files=read_pak(out)[1];zeroed=kept=0
  for r in self.eng.lib.recs.values():
   if r.kind!='ps' or (r.char,r.var)!=('Ch017','base'):continue
   rel=r.pkg.replace('/Game/','',1)+'.uexp'
   asset=self.eng.lib.read(r);new=files.get(rel,asset.ux)
   mp,_=emitter_parts(asset,part_of);default=part_of(r.name)
   for i,e in enumerate(asset.exports):
    if e['class']!='ParticleModuleSpawn':continue
    second=({default if p=='main' else p for p in mp.get(i,{default})}<={'trail','smoke'})
    for p in asset.export_props(i):
     if p.name!='BurstList':continue
     for burst in p.children or []:
      for c in burst.children or []:
       if c.name in ('Count','CountLow'):
        old=struct.unpack_from('<i',asset.ux,c.vpos)[0];now=struct.unpack_from('<i',new,c.vpos)[0]
        if old<0:continue
        if second:self.assertEqual(now,0);zeroed+=1
        else:self.assertEqual(now,old);kept+=1
  self.assertGreater(zeroed,0);self.assertGreater(kept,0)
 def test_invalid_second_amount_rejected(self):
  for v in (-1,101,float('nan')):
   with self.assertRaisesRegex(ValueError,'amount'):self.eng.preview(self.assignment(secondary=dict(hex='#00FF00',parts=['trail'],amount=v)))

if __name__=='__main__':unittest.main(verbosity=2)

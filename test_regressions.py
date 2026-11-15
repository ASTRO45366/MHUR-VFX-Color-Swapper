"""Regression tests; set MHUR_VFX_TEST_DATA for real-asset coverage."""
import json
import struct
import unittest
from pathlib import Path
from core.engine import Engine, MOUNT, part_of, level_steps, is_effect_asset
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
       self.assertEqual(h,max(1,int(old*.5+.5)) if old>0 else old)
       counts+=1
  self.assertGreater(counts,0)


 def test_part_names_use_whole_words(self):
  for name,part in (('PS_Ch115_SignArea_White_00','main'),('PS_Ch115_SP_Lightning_00','main'),
    ('PS_Ch001_attack01_trail_00','trail'),('PS_Ch001_skill_debri_00','smoke'),
    ('PS_Ch001_Attack_light','light'),('PS_Ch115_Attack2Light_00','light'),('PS_Ch017V1_skill02_Body_00_L1','aura')):
   self.assertEqual(part_of(name),part,name)
 def test_level_steps(self):
  self.assertEqual([level_steps(n) for n in ('PS_x_L3','PS_x_L2_BP','PS_Gasha_x_L4','MI_x_L1_00','PS_x_Impact_00')],[0,1,0,2,None])
  self.assertEqual([level_steps(n) for n in ('PS_Ch007_skill02_Ground_LVL9','MI_ef_Ch007_LightningGround_LVL4','PS_Ch010_skill01_Groundwave_LVL1','PS_Ch111_Skill03_trail_L01','PS_Ch111_Skill03_trail_L03')],[0,1,2,2,0])
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

 # ---- v2.3: exact colours on GPU emitters / extra material params
 def test_gpu_emitters_get_exact_hue(self):
  import colorsys
  from core.recolor import find_fields,GpuColorField,analyse,hex_to_rgb
  recs=[r for r in self.eng.lib.recs.values() if r.kind=='ps' and r.char=='Ch043']
  if not recs:self.skipTest('needs the Ch043 fixture')
  sw=Swap('#FF26C0','unify',None,1,True);th=colorsys.rgb_to_hsv(*hex_to_rgb('#FF26C0'))[0];n=0
  for r in recs:
   asset=self.eng.lib.read(r)
   for f in find_fields(asset):
    if isinstance(f,GpuColorField):
     buf=bytearray(asset.ux);f.apply(buf,sw);self.assertEqual(len(buf),len(asset.ux))
     for c in f.entries(buf):
      if max(c)>0.01:self.assertAlmostEqual(analyse(c)[1],th,delta=0.01);n+=1
  self.assertGreater(n,0)
 def test_more_material_color_names(self):
  from core.recolor import is_color_param
  for name in ('C1','C2','EM_magma','Fresnel_Inside','Screen_EM','Main_color_01','LineColorFriend'):self.assertTrue(is_color_param(name),name)
  for name in ('World Normal','Z','axis','UV_Scale'):self.assertFalse(is_color_param(name,(0,0,1)),name)
  self.assertTrue(is_color_param('Param',(0.15,0,2)));self.assertFalse(is_color_param('Param',(0,0,1)))
 # ---- v2.3: proportional particle amount
 def test_single_particle_bursts_fade_instead_of_vanishing(self):
  from core.amount import _lod_groups
  for r in self.eng.lib.recs.values():
   if r.kind!='ps':continue
   asset=self.eng.lib.read(r);buf=bytearray(asset.ux);touched=set()
   apply_amount(asset,buf,40,touched=touched)
   for i,e in enumerate(asset.exports):
    if e['class']!='ParticleModuleSpawn':continue
    for p in asset.export_props(i):
     if p.name!='BurstList':continue
     for burst in p.children or []:
      for c in burst.children or []:
       if c.name=='Count':
        old=struct.unpack_from('<i',asset.ux,c.vpos)[0];new=struct.unpack_from('<i',buf,c.vpos)[0]
        if old>0:self.assertGreaterEqual(new,1)
   zero=bytearray(asset.ux);apply_amount(asset,zero,0)
   for lod,_ in _lod_groups(asset):
    for p in asset.export_props(lod):
     if p.name=='bEnabled':self.assertEqual(zero[p.bool_pos],0)
 # ---- v2.3: walking dust, outline, cosmetic-only safety
 def test_walking_dust_skipped_by_default(self):
  from core.engine import is_movement
  if 'Ch100' not in self.eng.lib.characters():self.skipTest('needs the Ch100 fixture')
  walk=[r for r in self.eng.lib.recs.values() if r.char=='Ch100' and r.kind=='ps' and is_movement(r)]
  self.assertTrue(any('Walk' in r.name for r in walk))
  a=self.assignment(char='Ch100',group='all')
  names={r.name for r,_,_ in self.eng._selection(a)[0]}
  self.assertFalse(names&{r.name for r in walk})
  names={r.name for r,_,_ in self.eng._selection(dict(a,movement=True))[0]}
  self.assertTrue({r.name for r in walk}<=names)
  self.assertFalse(is_movement(next(r for r in self.eng.lib.recs.values() if r.name=='PS_Ch115_SP_Airwalk_00')))
 def test_safety_check_blocks_non_color_edits(self):
  r=next(r for r in self.eng.lib.recs.values() if r.kind=='ps')
  asset=self.eng.lib.read(r);buf=bytearray(asset.ux);buf[len(buf)//2]^=0xFF
  with self.assertRaisesRegex(RuntimeError,'Safety check'):self.eng._check_cosmetic(r,asset.ua,bytes(buf),set())
  with self.assertRaisesRegex(RuntimeError,'size changed'):self.eng._check_cosmetic(r,asset.ua,bytes(asset.ux)+b'\0',set())
 def test_exports_only_touch_effect_assets(self):
  out,_=self.eng.build([],'TEST_cosmetic',global_cfg=dict(hex='#00FF88',mode='unify',amount=35,intensity=1,secondary=None));self.addCleanup(lambda:out.unlink(missing_ok=True))
  for name in read_pak(out)[1]:
   stem=Path(name).stem
   self.assertTrue(stem.startswith(('PS_','MI_','MII_','M_','PP_','PPI_','T_'))or name.startswith('Credits') or 'credit' in name.lower(),name)

 def test_team_indicator_params_need_indicator_toggle(self):
  from core.engine import color_fields
  r=next((r for r in self.eng.lib.recs.values() if r.name=='MI_ef_Ch115_MeshOutline_00'),None)
  if not r:self.skipTest('needs the Ch115 fixture')
  asset=self.eng.lib.read(r)
  self.assertIn('EM_color_ally',[f.label for f in color_fields(asset,True)])
  self.assertNotIn('EM_color_ally',[f.label for f in color_fields(asset,False)])

 def test_pak_names_start_with_zzz(self):
  from core.engine import pak_filename
  self.assertEqual(pak_filename('Red VFX'),'ZZZ_Red_VFX-WindowsNoEditor_P.pak')
  self.assertEqual(pak_filename('zzzRed-WindowsNoEditor_P.pak'),'ZZZRed-WindowsNoEditor_P.pak')
  self.assertEqual(pak_filename(''),'ZZZ_MHUR_VFX_Recolor-WindowsNoEditor_P.pak')
  self.assertEqual(pak_filename('../../evil'),'ZZZ_evil-WindowsNoEditor_P.pak')

 # ---- v2.5: solid objects (textures)
 def _store(self):
  from core.textures import TextureStore
  root=Path(self.eng.base)
  if not (root/'texture-cache').is_dir():self.skipTest('needs cached fixture textures')
  self.eng.texture_store=TextureStore(root,root/'no-tools',lambda:{})
  self.addCleanup(lambda:setattr(self.eng,'texture_store',None))
 def test_texture_rules(self):
  from core.texture import texture_kind
  self.assertEqual(texture_kind('T_ef_Ch004_ice_D'),'color')
  self.assertEqual(texture_kind('T_ef_Ch015_crack_00'),'object')
  self.assertEqual(texture_kind('T_ef_Ch015_crack_E'),'object')
  for n in ('T_ef_Ch004_ice_N','T_ef_Ch004_ice_M','T_ef_Ch004_Ice_RGBA','T_ef_Ch004_Ice_Base_ARMA','T_ef_glow_08','T_ef_Ch017_fire_00'):self.assertIsNone(texture_kind(n),n)
 def test_texture_identity_is_lossless_and_tint_keeps_highlights(self):
  import colorsys
  from core.texture import parse_texture,recolor_texture,TextureTint
  from core.uasset import Asset
  root=Path(self.eng.base)/'texture-cache'
  files=sorted(root.rglob('T_*.uexp'))[:40] if root.is_dir() else []
  if not files:self.skipTest('needs cached fixture textures')
  n=0
  for ux_p in files:
   ua=ux_p.with_suffix('.uasset').read_bytes();ux=ux_p.read_bytes();ub_p=ux_p.with_suffix('.ubulk');ub=ub_p.read_bytes() if ub_p.exists() else b''
   info=parse_texture(Asset(ua,ux),ux,len(ub))
   if not info:continue
   a,b,_,_=recolor_texture(info,ux,ub,lambda c:c);self.assertEqual((a,b),(ux,ub));n+=1
  self.assertGreater(n,0)
  from core.recolor import s2l,l2s,hex_to_rgb
  typical=(60,120,240)
  for target in ('#3E1266','#FF2A2A','#16022C'):
   t=TextureTint(target,'unify',1,[typical]*10)
   got=[l2s(c) for c in t(tuple(s2l(c/255) for c in typical))]
   want=hex_to_rgb(target)
   for g,w in zip(got,want):self.assertAlmostEqual(g,w,delta=0.02)   # typical texel == picked colour
   hi=[l2s(c) for c in t((1.0,1.0,1.0))]
   self.assertGreaterEqual(max(hi),max(want)-1e-6)                   # highlights stay lighter
   self.assertLess(colorsys.rgb_to_hsv(*hi)[1],colorsys.rgb_to_hsv(*want)[1]+1e-6)
 def test_solid_objects_default_off_except_shigaraki(self):
  from core.engine import objects_default
  self.assertTrue(objects_default('Ch015','alpha'));self.assertTrue(objects_default('Ch015','gamma'))
  self.assertFalse(objects_default('Ch015','special'));self.assertFalse(objects_default('Ch101','alpha'));self.assertFalse(objects_default('Ch004','beta'))
 def test_solid_object_textures_only_when_enabled(self):
  if 'Ch004' not in self.eng.lib.characters():self.skipTest('needs the Ch004 fixture')
  self._store()
  a=self.assignment(char='Ch004',var='base',group='beta')
  out,rep=self.eng.build([a],'TEST_objects_off');self.addCleanup(out.unlink,missing_ok=True)
  self.assertFalse(any('/T_' in f for f in read_pak(out)[1]));self.assertEqual(rep['textures'],0)
  out2,rep=self.eng.build([dict(a,objects=True)],'TEST_objects_on');self.addCleanup(out2.unlink,missing_ok=True)
  tex=[f for f in read_pak(out2)[1] if '/T_' in f and f.endswith('.uasset')]
  self.assertEqual(rep['textures'],len(tex));self.assertGreater(len(tex),0)
  out3,rep=self.eng.build([],'TEST_objects_choice',global_cfg=dict(hex='#FF0000',mode='unify',amount=100,intensity=1),objects={'Ch004:base:beta':True})
  self.addCleanup(out3.unlink,missing_ok=True);self.assertGreater(rep['textures'],0)
 def test_texture_safety_check(self):
  from core.engine import check_spans
  old=bytes(100);new=bytearray(old);new[50]=1
  check_spans('t',old,bytes(new),[(40,60)])
  with self.assertRaisesRegex(RuntimeError,'non-pixel'):check_spans('t',old,bytes(new),[(0,10)])
  with self.assertRaisesRegex(RuntimeError,'size'):check_spans('t',old,old+b'x',[])

 def test_diagnostic_report(self):
  if 'Ch004' not in self.eng.lib.characters():self.skipTest('needs the Ch004 fixture')
  text=self.eng.diagnose('Ch004','base','beta')
  self.assertIn('PS_Ch004_skill02IceUnit',text);self.assertIn('Solid-object textures for this skill: 3',text)

 # ---- v2.6: never recolor character models / shared master materials
 def test_character_models_and_master_materials_are_never_recolored(self):
  import copy
  from core.library import Rec
  from core.engine import is_effect_asset
  lib=self.eng.lib
  ps=next(r for r in lib.recs.values() if r.kind=='ps' and r.char=='Ch017' and r.refs and any(p in lib.recs for p in r.refs))
  src=lib.recs[next(p for p in ps.refs if p in lib.recs)]
  fakes=[]
  for path in ('/Game/Character/Ch017/Model/Default/Mat/MII_Ch017_Default_00_body_D',
               '/Game/Character/Ch000/Model/Default/Mat/Master_Material/M_Chara_Master'):
   r=copy.copy(src);r.pkg=path;r.name=path.rsplit('/',1)[1];r.refs=set();r.groups={ps.group};r.orphan=False
   lib.recs[path]=r;fakes.append(path)
  old=set(ps.refs);ps.refs=set(ps.refs)|set(fakes)
  def restore():
   ps.refs=old
   for p in fakes:lib.recs.pop(p,None)
  self.addCleanup(restore)
  self.assertFalse(any(is_effect_asset(p) for p in fakes))
  sel,_=self.eng._selection(self.assignment(group='all',hex='#00FF00'))
  self.assertFalse({r.pkg for r,_,_ in sel}&set(fakes))
  out,_=self.eng.build([self.assignment(group='all',hex='#00FF00')],'TEST_no_models');self.addCleanup(out.unlink,missing_ok=True)
  files=read_pak(out)[1]
  self.assertFalse([f for f in files if '/Model/' in f or 'Master_Material' in f])
  self.assertTrue(all(is_effect_asset('/Game/'+f.rsplit('.',1)[0]) for f in files if f.startswith('Character/')))
 def test_blueprint_spawned_effect_materials_are_included(self):
  if 'Ch103' not in self.eng.lib.characters():self.skipTest('needs the Ch103 fixture')
  names={m.name for m in self.eng.lib.scope_recs('Ch103','base','beta',False)[1]}
  self.assertIn('MI_ef_Ch103_gate_mask_03',names)
  if 'Ch015' in self.eng.lib.characters():
   names={m.name for m in self.eng.lib.scope_recs('Ch015','Var01','alpha',False)[1]}
   self.assertIn('MI_ef_Ch015V1_decal_skill01_LV1',names)
   self.assertNotIn('MI_ef_Ch015V1_decal_skill02_LV1',names)
 def test_two_color_textures_put_second_color_on_highlights(self):
  import colorsys
  from core.texture import TextureTint
  from core.recolor import s2l,l2s,hex_to_rgb
  samples=[(60,120,240)]*20+[(250,250,255)]*4
  t=TextureTint('#18E01A','unify',1,samples,True,'#1A6BFF')
  body=[l2s(c) for c in t(tuple(s2l(c/255) for c in (60,120,240)))]
  hi=[l2s(c) for c in t(tuple(s2l(c/255) for c in (250,250,255)))]
  hb=colorsys.rgb_to_hsv(*body)[0];hh=colorsys.rgb_to_hsv(*hi)[0]
  self.assertAlmostEqual(hb,colorsys.rgb_to_hsv(*hex_to_rgb('#18E01A'))[0],delta=0.02)
  self.assertAlmostEqual(hh,colorsys.rgb_to_hsv(*hex_to_rgb('#1A6BFF'))[0],delta=0.03)

 def test_effect_rule_allows_effects_outside_effect_folders_but_never_models(self):
  from core.engine import is_effect_asset
  ok=('/Game/Character/Ch015/Variation/Var02/Particle/PS_Ch015V2_skill01_jump_Smoke_00',
      '/Game/Character/Ch015/Variation/Var02/Mat/MI_ef_Ch015V2_smoke_00',
      '/Game/Character/Ch004/Effect/Tex/T_ef_Ch004_ice_D','/Game/Character/Ch017/Effect/Mat/MI_ef_Ch017_fire_00')
  bad=('/Game/Character/Ch115/Model/Default/Mat/MII_Ch115_Default_00_skin_D','/Game/Character/Ch100/Option/Truck/MI_Ch100_truck',
       '/Game/Character/Ch000/Model/Default/Mat/Master_Material/M_Chara_Master','/Game/Character/Ch001/Costume/MI_Ch001_suit',
       '/Game/Character/Ch015/Variation/Var02/Mat/MI_Ch015V2_body')
  ok+=('/Game/Character/Ch015/Variation/Var02/Model/Effect/PS_Ch015V2_skill01_jump_Smoke_00',
       '/Game/Character/Ch015/Variation/Var02/Option/PS_Ch015V2_skill01_jump_Smoke_00',
       '/Game/Character/Ch015/Variation/Var02/Model/Mat/MI_ef_Ch015V2_smoke_00')
  for p in ok:self.assertTrue(is_effect_asset(p),p)
  for p in bad:self.assertFalse(is_effect_asset(p),p)
 def test_particle_systems_outside_effect_folders_pass_the_safety_check(self):
  import copy
  lib=self.eng.lib
  src=next(r for r in lib.recs.values() if r.kind=='ps' and r.char=='Ch017')
  r=copy.copy(src);r.pkg='/Game/Character/Ch017/Variation/Var02/Particle/'+src.name
  a=lib.read(src);buf=bytearray(a.ux);spans=set()
  from core.recolor import find_fields
  for f in find_fields(a):f.apply(buf,Swap('#00FF00','unify',None,1,True));spans.update(f.spans(a.ux))
  r.ua,r.ux=src.ua,src.ux
  self.eng._check_cosmetic(r,a.ua,bytes(buf),spans)   # must not raise

 def test_non_effect_files_are_left_out_instead_of_blocking_the_export(self):
  import copy
  lib=self.eng.lib
  ps=next(r for r in lib.recs.values() if r.kind=='ps' and r.char=='Ch017' and any(p in lib.recs for p in r.refs))
  src=lib.recs[next(p for p in ps.refs if p in lib.recs)]
  path='/Game/Character/Ch017/Model/Default/Mat/MII_Ch017_Default_00_body_D'
  fake=copy.copy(src);fake.pkg=path;fake.name=path.rsplit('/',1)[1];fake.refs=set();fake.orphan=False
  lib.recs[path]=fake;self.addCleanup(lambda:lib.recs.pop(path,None))
  orig=lib.scope_recs
  def scope(*a,**k):
   p,m=orig(*a,**k);return p,m+[fake]
  lib.scope_recs=scope;self.addCleanup(lambda:setattr(lib,'scope_recs',orig))
  import core.engine as E
  real=E.is_effect_asset
  # let the fake slip past the selection filter, as an unexpected folder layout would
  E.is_effect_asset=lambda p:True if p==path and getattr(self,'_selecting',True) else real(p)
  self.addCleanup(lambda:setattr(E,'is_effect_asset',real))
  self._selecting=True
  sel,_=self.eng._selection(self.assignment(group='all'))
  self._selecting=False
  self.assertIn(path,{r.pkg for r,_,_ in sel})
  E.is_effect_asset=real
  out,rep=self.eng.build([self.assignment(group='all')],'TEST_skip_model');self.addCleanup(out.unlink,missing_ok=True)
  self.assertNotIn(path.replace('/Game/','',1)+'.uexp',read_pak(out)[1])

 def test_paks_are_uncompressed_by_default_and_readable_both_ways(self):
  import struct,tempfile,os
  from core.pak import write_pak
  files={'Character/Ch000/Effect/A.uexp':os.urandom(70000),'Character/Ch000/Effect/A.uasset':b'abc'*10}
  with tempfile.TemporaryDirectory() as d:
   for comp,method in ((False,0),(True,1)):
    p=Path(d)/f'x{comp}.pak';write_pak(p,MOUNT,files,comp)
    mount,got=read_pak(p);self.assertEqual(mount,MOUNT);self.assertEqual(got,files)
    self.assertEqual(struct.unpack_from('<I',p.read_bytes(),24)[0],method)
  from preferences import DEFAULTS
  self.assertIs(DEFAULTS['compress_paks'],False)

if __name__=='__main__':unittest.main(verbosity=2)

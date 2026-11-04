"""Convert a v1 per-file library into lossless, indexed LZMA blocks."""
import json,lzma,zipfile,time,sys
from pathlib import Path
from collections import defaultdict
source,target=map(Path,sys.argv[1:3]);start=time.monotonic()
with zipfile.ZipFile(source) as old, zipfile.ZipFile(target,'w') as new:
 records=json.loads(old.read('catalog.json')); groups=defaultdict(list)
 for record in records:
  rel=record['pkg'].replace('/Game/','',1)
  for ext in ('.uasset','.uexp'):groups[record['char']].append(rel+ext)
 members={};blockno=0
 for char,names in sorted(groups.items()):
  pending=[];payload=bytearray()
  def flush():
   global blockno,payload,pending
   if not pending:return
   block=f'blocks/{char}-{blockno:03d}.xz'
   for name,offset,size in pending:members[name]=[block,offset,size]
   new.writestr(block,lzma.compress(payload,preset=6))
   blockno+=1;pending=[];payload=bytearray()
  # Keep headers together and exports together to maximize shared compression.
  for name in sorted(names,key=lambda n:(n.rsplit('.',1)[-1],n)):
   data=old.read(name)
   if payload and len(payload)+len(data)>16*1024*1024:flush()
   pending.append((name,len(payload),len(data)));payload.extend(data)
  flush()
  print(char,'packed',flush=True)
 new.writestr('catalog.json',json.dumps({'format':2,'records':records,'members':members},separators=(',',':')),compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
print(json.dumps({'old_bytes':source.stat().st_size,'new_bytes':target.stat().st_size,'seconds':round(time.monotonic()-start,2)}))

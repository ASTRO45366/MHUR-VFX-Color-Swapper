"""Minimal UE4 (unversioned-header, tagged-property) uasset/uexp reader/patcher."""
import struct

class Prop:
    __slots__=('name','type','size','idx','sname','inner','enum','vpos','value','children','path','bool_pos')
    def __repr__(s): return f'<{s.name}:{s.type}/{s.sname} @{s.vpos}+{s.size}>'

class Asset:
    def __init__(self, uasset: bytes, uexp: bytes):
        self.ua=uasset; self.ux=uexp; self.failed=set()
        p=0
        tag,leg=struct.unpack_from('<Ii',uasset,0); p=8
        if tag!=0x9E2A83C1:
            raise ValueError('not a uasset')
        p+=4 # ue3
        p+=4 # ue4
        if leg<=-8: p+=4
        p+=4 # licensee
        cc=struct.unpack_from('<i',uasset,p)[0]; p+=4
        for _ in range(cc):
            p+=16+4
        self.header_size=struct.unpack_from('<i',uasset,p)[0]; p+=4
        n=struct.unpack_from('<i',uasset,p)[0]; p+=4; p+=abs(n)*(2 if n<0 else 1)
        self.flags=struct.unpack_from('<I',uasset,p)[0]; p+=4
        self.name_count,self.name_off=struct.unpack_from('<ii',uasset,p); p+=8
        if not (self.flags & 0x80000000):
            n=struct.unpack_from('<i',uasset,p)[0]; p+=4+abs(n)*(2 if n<0 else 1)
        p+=8
        self.export_count,self.export_off,self.import_count,self.import_off=struct.unpack_from('<iiii',uasset,p)
        self.names=[]
        o=self.name_off
        for _ in range(self.name_count):
            n=struct.unpack_from('<i',uasset,o)[0]; o+=4
            if n<0:
                n=-n; s=uasset[o:o+n*2-2].decode('utf-16le'); o+=n*2
            else:
                s=uasset[o:o+n-1].decode('latin-1'); o+=n
            o+=4
            self.names.append(s)
        self.imports=[]
        o=self.import_off
        for _ in range(self.import_count):
            cp,cpn,cn,cnn,outer,on,onn=struct.unpack_from('<iiiiiii',uasset,o); o+=28
            self.imports.append((self.names[cp],self.names[cn],outer,self.names[on]))
        self.exports=[]
        o=self.export_off
        for _ in range(self.export_count):
            cls,sup,tmpl,outer,on,onn,flags,ssize,soff=struct.unpack_from('<iiiiiiIqq',uasset,o); o+=104
            self.exports.append(dict(cls=cls,outer=outer,name=self.names[on],ssize=ssize,soff=soff-self.header_size))
        for e in self.exports:
            e['class']=self.cls_name(e['cls'])

    def object_path(self,idx):
        """Package path of an import/export reference (negative = import)."""
        if idx>=0: return None
        cur=self.imports[-idx-1]
        outer=cur[2]
        while outer<0:
            nxt=self.imports[-outer-1]
            if nxt[1]=='Package': return nxt[3]
            outer=nxt[2]
        return None
    def cls_name(self,idx):
        if idx<0: return self.imports[-idx-1][3]
        if idx>0: return self.exports[idx-1]['name']
        return 'None'
    def fname(self,buf,p):
        i,n=struct.unpack_from('<ii',buf,p)
        s=self.names[i]
        return s if n==0 else f'{s}_{n-1}'
    def read_props(self,buf,p,end,path=''):
        props=[]
        while p<end:
            name=self.fname(buf,p); p+=8
            if name=='None': break
            t=self.fname(buf,p); p+=8
            size,idx=struct.unpack_from('<ii',buf,p); p+=8
            pr=Prop(); pr.name=name; pr.type=t; pr.size=size; pr.idx=idx; pr.sname=None; pr.inner=None; pr.enum=None
            pr.children=None; pr.value=None; pr.path=path+'/'+name
            if t=='StructProperty':
                pr.sname=self.fname(buf,p); p+=8+16
            elif t=='BoolProperty':
                pr.bool_pos=p; pr.value=buf[p]; p+=1
            elif t in('ByteProperty','EnumProperty'):
                pr.enum=self.fname(buf,p); p+=8
            elif t=='ArrayProperty' or t=='SetProperty':
                pr.inner=self.fname(buf,p); p+=8
            elif t=='MapProperty':
                p+=16
            if buf[p]: p+=1+16
            else: p+=1
            pr.vpos=p
            self.fill(buf,pr)
            p+=size
            props.append(pr)
        return props
    def fill(self,buf,pr):
        p=pr.vpos; t=pr.type
        if t=='StructProperty':
            s=pr.sname
            if s in('Vector','LinearColor','Color','Vector4','Rotator','Vector2D','Quat','Guid'):
                pass
            else:
                try: pr.children=self.read_props(buf,p,p+pr.size,pr.path)
                except Exception: pr.children=None; self.failed.add(s)
        elif t=='ArrayProperty' and pr.inner=='StructProperty':
            cnt=struct.unpack_from('<i',buf,p)[0]; q=p+4
            # inner tag
            iname=self.fname(buf,q); q+=8; itype=self.fname(buf,q); q+=8
            isz,iidx=struct.unpack_from('<ii',buf,q); q+=8
            sname=self.fname(buf,q); q+=8+16
            q+=1
            pr.sname=sname; pr.value=(cnt,q,isz)
            if sname not in('Vector','LinearColor','Color','Vector4','Rotator','Vector2D','Quat','Guid') and cnt>0:
                el=isz//cnt if cnt else 0
                pr.children=[]
                for i in range(cnt):
                    c=Prop(); c.name=f'[{i}]'; c.type='StructProperty'; c.sname=sname; c.vpos=q+i*el; c.size=el; c.idx=0; c.inner=None; c.enum=None; c.value=None
                    c.path=pr.path+f'[{i}]'
                    try: c.children=self.read_props(buf,c.vpos,c.vpos+el,c.path)
                    except Exception: c.children=None; self.failed.add(sname)
                    pr.children.append(c)
    def export_props(self,i):
        e=self.exports[i]
        return self.read_props(self.ux,e['soff'],e['soff']+e['ssize'],e['name'])

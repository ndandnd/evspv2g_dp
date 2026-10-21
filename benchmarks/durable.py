from pathlib import Path
import os,json,hashlib,time
import numpy as np
from master import Column

def digest(obj): return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def atomic(path,obj):
    tmp=path.with_suffix(path.suffix+'.tmp')
    with open(tmp,'w') as f: json.dump(obj,f,sort_keys=True,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    fd=os.open(path.parent,os.O_RDONLY);os.fsync(fd);os.close(fd)

def pack(c):return dict(kind=c.kind,a=c.a.tolist(),e=c.e.tolist(),fixed_cost=c.fixed_cost,label=c.label)

def unpack(c):return Column(c['kind'],np.array(c['a']),np.array(c['e']),c['fixed_cost'],c['label'])

def key(c):return digest(dict(kind=c.kind,a=c.a.tolist(),e=c.e.tolist(),fixed_cost=c.fixed_cost))

class Journal:
    def __init__(self,out,ident):
        self.out=out;self.ident=ident;self.path=out/'accepted.columns.jsonl';self.cols=[];self.hash='0'*64
        if (out/'identity.json').exists():
            if json.loads((out/'identity.json').read_text())!=ident:raise RuntimeError('Incompatible run identity')
        else:
            if self.path.exists():raise RuntimeError('Journal without identity')
            atomic(out/'identity.json',ident)
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                r=json.loads(line);h=r.pop('hash')
                if r['previous']!=self.hash or digest(r)!=h or r['sequence']!=len(self.cols):raise RuntimeError('Corrupt journal; manual recovery required')
                self.cols.append(unpack(r['column']));self.hash=h
        cp=out/'checkpoint.json'
        if cp.exists():
            q=json.loads(cp.read_text())
            if q['identity_sha256']!=digest(ident) or q['count']>len(self.cols):raise RuntimeError('Checkpoint mismatch')
            lines=self.path.read_text().splitlines()
            prefix='0'*64 if not q['count'] else json.loads(lines[q['count']-1])['hash']
            if prefix!=q['journal_hash']:raise RuntimeError('Checkpoint prefix mismatch')
    def add(self,c,iteration):
        r=dict(sequence=len(self.cols),previous=self.hash,iteration=iteration,column=pack(c));r['hash']=digest(r)
        with open(self.path,'a') as f:f.write(json.dumps(r,sort_keys=True)+'\n');f.flush();os.fsync(f.fileno())
        self.cols.append(c);self.hash=r['hash']
    def checkpoint(self,iteration,state,**extra):
        q=dict(identity_sha256=digest(self.ident),count=len(self.cols),journal_hash=self.hash,iteration=iteration,state=state,wall_time=time.time(),**extra)
        atomic(self.out/'checkpoint.json',q);atomic(self.out/'cg_status.json',q)
        return q

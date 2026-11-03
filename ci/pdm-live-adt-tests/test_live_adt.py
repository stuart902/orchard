"""Actual Linux ADT decoder under ASan/UBSan, using synthetic calibration."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
base = Path(__file__).resolve().parents[1]
source = (base / 't8010-pdm.c').read_text()
a = source.index('static bool pdm_rate_present(')
b = source.index('static int pdm_calibration_read(', a)
c = r'''
#include <stdio.h>
#include <stdlib.h>
#include <assert.h>
#include <string.h>
#include "t8010-pdm.h"
#include "t8010-pdm-adt.h"
#define GFP_KERNEL 0
struct pdm_decimator {u64 size,physical; u32 config,delay_ms,force_gating; u8 mic_name[4]; unsigned nfilters; struct pdm_filter filters[PDM_MAX_RATES];};
struct pdm_profile {const char *model;};
struct t8010_pdm {const struct pdm_profile *profile;void *dev;u64 physical,size; struct pdm_decimator dec[2]; u32 delay_ms,rates[PDM_MAX_RATES]; struct {unsigned count;u32 *list;}rate_list;};
static void *allocations[32];static unsigned allocated;
static void *devm_kmemdup(void *dev,const void *p,size_t n,int flags) {void *v=malloc(n);assert(allocated<32);allocations[allocated++]=v;if(v)memcpy(v,p,n);return v;}
''' + source[a:b] + r'''
int main(int argc,char **argv) {
 assert(argc==3);FILE *f=fopen(argv[1],"rb");assert(f);fseek(f,0,SEEK_END);long size=ftell(f);rewind(f);assert(size>=0);
 u8 *blob=malloc(size?size:1);assert(blob);assert(fread(blob,1,size,f)==(size_t)size);fclose(f);
 struct pdm_adt t={.data=blob,.size=size,.nodes=calloc(PDM_ADT_MAX_NODES,sizeof(*t.nodes))};assert(t.nodes);
 const struct pdm_profile profile={.model="iPad7,5"};
 struct t8010_pdm p={.profile=&profile,.physical=0x20a0b4000,.size=0x1000,.dec={{.size=0x4000,.physical=0x20a120000},{.size=0x4000,.physical=0x20a124000}}};
 int result=pdm_adt_parse(&t);if(!result)result=pdm_adt_decode(&p,&t);
 int want=atoi(argv[2]);if((result==0)!=(!want)){fprintf(stderr,"unexpected result %d, expected %s\n",result,want?"failure":"success");return 1;}
 if(!result){assert(p.rate_list.count==4);assert(p.dec[0].nfilters==p.dec[1].nfilters);for(unsigned i=0;i<2;i++)for(unsigned j=0;j<p.dec[i].nfilters;j++){const u8 *q=p.dec[i].filters[j].coefficients;assert((uintptr_t)q<(uintptr_t)blob || (uintptr_t)q>=(uintptr_t)blob+size);assert(p.dec[i].force_gating==0);}}
 for(unsigned i=0;i<allocated;i++)free(allocations[i]);free(t.nodes);free(blob);return 0;
}
'''
tmp = Path(tempfile.mkdtemp(prefix='pdm-live-adt-'))
(tmp / 'test.c').write_text(c)
subprocess.run(['cc', '-std=gnu11', '-fsanitize=address,undefined', '-g', '-I'+str(base/'tests/include'), '-I'+str(base), str(tmp/'test.c'), '-o', str(tmp/'test')], check=True)

def word(n): return struct.pack('<I', n)
def qword(n): return struct.pack('<Q', n)
def node(props, children=()):
    out=word(len(props))+word(len(children))
    for key,value in props:
        out+=key.encode().ljust(32,b'\0')+word(len(value))+value+b'\0'*((-len(value))%4)
    return out+b''.join(children)
def rates(values): return b''.join(word(0)+word(x) for x in values)
def fixture(change=None):
    dst=[('function-pdm-clk-cfg',word(51)+word(0x70646d43)),('reg',qword(0xa0b4000)+qword(0x1000)),('name',b'pdm\0'),('compatible',b'pdm,t8010\0'),('decimators',word(149)+word(150)),('dst-samplerates',rates([16000,24000,44100,48000]))]
    coeff=[('name',b'dmic\0'),('AAPL,phandle',word(148)),('mic-samplerates',rates([16000,24000,32000,44100,48000]))]
    for rate in [16000,24000,32000,44100,48000]:
        coeff += [(f'pdmfreq-{rate}',word(2823530 if rate==44100 else 2400000)),(f'latency-{rate}',word(40)),(f'ratios-{rate}',bytes([2,2,2,0])),(f'lengths-{rate}',bytes([1,1,1,0])),(f'coeff-{rate}',bytes(24))]
    dec=[]
    for i in range(2):
        dec.append([('reg',qword(0xa120000+i*0x4000)+qword(0x4000)),('name',f'hfdec{i}\0'.encode()),('compatible',b'hifidec,t8010\0'),('AAPL,phandle',word(149+i)),('index',word(i)),('config',word(i)),('mic-startup-delay',word(50)),('mic-coeff-data',word(148)),('mic-name',bytes([49+i,105,109,105]))])
    root=[('name',b'device-tree\0'),('model',b'iPad7,5\0')]
    if change: change(root,dst,coeff,dec)
    return node(root,[node([('name',b'arm-io\0'),('compatible',b'arm-io,t8010\0'),('ranges',qword(0)+qword(0x200000000)+qword(0x100000000))],[node(dst,[node(coeff)]),node(dec[0]),node(dec[1]),node([('name',b'audio-pdm2\0'),('AAPL,phandle',word(51)),('identifier',word(0x70646d30))])])])
def replace(props,key,value):
    for i,(k,v) in enumerate(props):
        if k==key:props[i]=(key,value);return
    raise AssertionError(key)

cases=[('valid',fixture(),False),('empty',b'',True),('truncated',fixture()[:-1],True)]
mutations={
'wrong-clock-selector':lambda r,p,c,d:replace(p,'function-pdm-clk-cfg',word(51)+word(0)),
'wrong-clock-target':lambda r,p,c,d:replace(p,'function-pdm-clk-cfg',word(148)+word(0x70646d43)),
'wrong-address':lambda r,p,c,d:replace(d[0],'reg',qword(0xa124000)+qword(0x4000)),
'wrong-resource-size':lambda r,p,c,d:replace(d[0],'reg',qword(0xa120000)+qword(0x1000)),
'wrong-model':lambda r,p,c,d:replace(r,'model',b'iPad7,6\0'),
'duplicate-property':lambda r,p,c,d:r.append(('model',b'iPad7,5\0')),
'duplicate-phandle':lambda r,p,c,d:replace(d[1],'AAPL,phandle',word(149)),
'duplicate-decimator':lambda r,p,c,d:replace(p,'decimators',word(149)*2),
'bad-index':lambda r,p,c,d:replace(d[1],'index',word(0)),
'bad-rate-padding':lambda r,p,c,d:replace(p,'dst-samplerates',word(1)+word(48000)),
'duplicate-rate':lambda r,p,c,d:replace(p,'dst-samplerates',rates([48000,48000])),
'missing-coeff':lambda r,p,c,d:c.__setitem__(slice(None),[(k,v)for k,v in c if k!='coeff-48000']),
'short-coeff':lambda r,p,c,d:replace(c,'coeff-48000',bytes(23)),
'ratio-padding':lambda r,p,c,d:replace(c,'ratios-48000',bytes([2,2,2,1])),
'length-padding':lambda r,p,c,d:replace(c,'lengths-48000',bytes([1,1,1,1])),
'ratio-product':lambda r,p,c,d:replace(c,'ratios-48000',bytes([63,63,63,0])),
'zero-frequency':lambda r,p,c,d:replace(c,'pdmfreq-48000',word(0)),
'bad-mic-name':lambda r,p,c,d:replace(d[0],'mic-name',b'abc'),
'bad-delay':lambda r,p,c,d:replace(d[0],'mic-startup-delay',word(1001)),
'wrong-decimator':lambda r,p,c,d:replace(d[0],'compatible',b'wrong\0'),
}
for name,change in mutations.items():cases.append((name,fixture(change),True))
# Structural denial tests stop before recursion/allocation beyond configured limits.
cases += [('huge-properties',word(257)+word(0),True),('huge-children',word(0)+word(4097),True),('unterminated-property',word(1)+word(0)+b'x'*32+word(0),True),('oversized-property',word(1)+word(0)+b'name\0'.ljust(32,b'\0')+word(0xffffff),True)]
deep=node([('name',b'end\0')])
for _ in range(34):deep=node([('name',b'n\0')],[deep])
cases.append(('depth-limit',deep,True))
cases.append(('oversized-tree',bytes(16*1024*1024+1),True))
for name,blob,bad in cases:
    path=tmp/(name+'.adt');path.write_bytes(blob)
    subprocess.run([str(tmp/'test'),str(path),str(int(bad))],check=True)
print(f'{len(cases)} actual ADT decoder sanitizer cases passed')
if len(sys.argv)>1:
    subprocess.run([str(tmp/'test'),sys.argv[1],'0'],check=True)
    print('Private matching ADT decoded successfully; no calibration emitted')

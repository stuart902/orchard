"""Actual snapshot function with mocked OF/MTD and driver-core lifetime APIs."""
from pathlib import Path
import subprocess
import tempfile
base=Path(__file__).resolve().parents[1]
s=(base/'t8010-pdm.c').read_text();a=s.index('static void *pdm_adt_snapshot(');b=s.index('static bool pdm_rate_present(',a)
c=r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#define ENODEV 19
#define EINVAL 22
#define EPROBE_DEFER 517
#define ENOMEM 12
#define EIO 5
#define GFP_KERNEL 0
#define MTD_RAM 1
#define PDM_ADT_MAX_BYTES (16*1024*1024)
#define ERR_PTR(e) ((void *)(intptr_t)(e))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
struct device_node {int ref;const char *label;bool compatible,available;};
struct device {int ref;bool bound;};
struct platform_device {struct device dev;};
struct mtd_info {int type;size_t size;};
static struct device_node reserved, children[2];static struct platform_device provider;static struct mtd_info mtd;
static bool absent_reserved,absent_provider,alloc_fail,locked,short_read;static int children_count,mtd_error,read_error,mtd_refs,reads;
static struct device_node *of_node_get(struct device_node *n){if(n)n->ref++;return n;}
static void of_node_put(struct device_node *n){if(n){assert(n->ref>0);n->ref--;}}
static struct device_node *of_find_node_by_path(const char *path){assert(!strcmp(path,"/reserved-memory"));return absent_reserved?NULL:of_node_get(&reserved);}
static struct device_node *next_child(struct device_node *p,struct device_node *last){int i=last?(int)(last-children)+1:0;of_node_put(last);return i<children_count?of_node_get(&children[i]):NULL;}
#define for_each_child_of_node(parent,node) for(node=next_child(parent,NULL);node;node=next_child(parent,node))
static int of_property_read_string(struct device_node *n,const char *key,const char **out){assert(!strcmp(key,"label"));*out=n->label;return n->label?0:-1;}
static bool of_device_is_compatible(struct device_node*n,const char*c){assert(!strcmp(c,"phram"));return n->compatible;}
static bool of_device_is_available(struct device_node*n){return n->available;}
static struct platform_device *of_find_device_by_node(struct device_node*n){if(absent_provider)return NULL;provider.dev.ref++;return &provider;}
static void device_lock(struct device*d){assert(!locked);locked=true;}
static void device_unlock(struct device*d){assert(locked&&!mtd_refs);locked=false;}
static bool device_is_bound(struct device*d){assert(locked);return d->bound;}
static void put_device(struct device*d){assert(!locked&&d->ref==1);d->ref--;}
static struct mtd_info *of_get_mtd_device_by_node(struct device_node*n){assert(locked);if(mtd_error)return ERR_PTR(mtd_error);mtd_refs++;return &mtd;}
static void put_mtd_device(struct mtd_info*m){assert(locked&&mtd_refs==1);mtd_refs--;}
static void *kvmalloc(size_t size,int flags){assert(locked&&mtd_refs==1);return alloc_fail?NULL:malloc(size);}
static void kvfree(void*p){free(p);}
static int mtd_read(struct mtd_info*m,size_t off,size_t size,size_t *received,void*out){assert(locked&&mtd_refs==1&&off==0&&size==m->size);reads++;*received=short_read?size-1:size;memset(out,0,size);return read_error;}
''' + s[a:b] + r'''
static void reset(void){
 absent_reserved=absent_provider=alloc_fail=locked=short_read=false;children_count=1;mtd_error=read_error=mtd_refs=reads=0;
 reserved=(struct device_node){};children[0]=(struct device_node){.label="adt",.compatible=true,.available=true};children[1]=children[0];
 provider=(struct platform_device){.dev={.bound=true}};mtd=(struct mtd_info){.type=MTD_RAM,.size=128};
}
static void check(int expected,int expected_reads){size_t size=0;void*p=pdm_adt_snapshot(&size);if(expected)assert(IS_ERR(p)&&PTR_ERR(p)==expected);else{assert(!IS_ERR(p)&&size==128);free(p);}assert(!locked&&!mtd_refs&&!provider.dev.ref&&!reserved.ref&&!children[0].ref&&!children[1].ref);assert(reads==expected_reads);}
int main(void){
 reset();check(0,1);
 reset();absent_reserved=true;check(-ENODEV,0);
 reset();children_count=0;check(-ENODEV,0);
 reset();children_count=2;check(-EINVAL,0);
 reset();children[0].compatible=false;check(-EINVAL,0);
 reset();children[0].available=false;check(-EINVAL,0);
 reset();absent_provider=true;check(-EPROBE_DEFER,0);
 reset();provider.dev.bound=false;check(-EPROBE_DEFER,0);
 reset();mtd_error=-EPROBE_DEFER;check(-EPROBE_DEFER,0);
 reset();mtd.type=2;check(-EINVAL,0);
 reset();mtd.size=7;check(-EINVAL,0);
 reset();mtd.size=PDM_ADT_MAX_BYTES+1;check(-EINVAL,0);
 reset();alloc_fail=true;check(-ENOMEM,0);
 reset();read_error=-EIO;check(-EIO,1);
 reset();short_read=true;check(-EIO,1);
 puts("15 actual MTD snapshot lifecycle/failure cases passed");
}
'''
p=Path(tempfile.mkdtemp(prefix='pdm-snapshot-'))/'test.c';p.write_text(c)
subprocess.run(['cc','-std=gnu11','-fsanitize=address,undefined','-g',str(p),'-o',str(p.with_suffix(''))],check=True)
subprocess.run([str(p.with_suffix(''))],check=True)

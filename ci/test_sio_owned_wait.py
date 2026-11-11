"""Exercise extracted SmartIO ownership functions; deterministic mocked IRQ/waits.

No hardware is accessed. This is not an IRQ/lockdep or firmware test.
"""
import argparse, os, shlex, subprocess, tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);a=p.parse_args()
core=(a.source/'drivers/soc/apple/apple-sio-core.c').read_text()
dma=(a.source/'drivers/dma/apple-sio-dma.c').read_text()
def extract(text,name):
    start=text.index(name+'(');start=text.rfind('\n',0,start)+1
    # Include declaration's return type line when it is on its own line.
    if text[start:].startswith(name): start=text.rfind('\n',0,start-1)+1
    begin=text.index('{',start);level=1;i=begin+1
    while level:
        level += (text[i]=='{')-(text[i]=='}');i+=1
    return text[start:i]+'\n'
prelude=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64;
#define APPLE_SIO_MAX_ENDPOINTS 0x82
#define APPLE_SIO_MSG_ENDPOINT 0xffULL
#define APPLE_SIO_MSG_TAG 0xff00ULL
#define APPLE_SIO_MSG_OPCODE 0xff0000ULL
#define APPLE_SIO_MSG_PARAMETER 0xff000000ULL
#define APPLE_SIO_OP_DMA_COMPLETE 0x68
#define APPLE_SIO_OP_ERROR 0x6a
#define APPLE_SIO_OP_DMA_ERROR 0x66
#define APPLE_SIO_DMA_COMPLETE_TAGGED 0x80
#define SIO_DMA_OP_ACK 0x65
#define FIELD_GET(mask,v) (((v)&(mask)) >> __builtin_ctzll(mask))
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
#define IS_ERR(x) ((uintptr_t)(x) > (uintptr_t)-4096)
#define PTR_ERR(x) ((intptr_t)(x))
#define dev_err(...) do {} while(0)
struct completion {bool done;};
struct apple_sio_async;
struct xarray {struct apple_sio_async *slot;};
struct apple_sio {
 struct xarray pending; bool running,stopping; struct completion ready;
 int owned_pending,owned_drained,unmatched_count;
 struct {void(*fn)(void*,u64);void *data;} notify[APPLE_SIO_MAX_ENDPOINTS];
};
typedef void(*apple_sio_notify_t)(void*,u64);
struct apple_sio_async {
 struct apple_sio *sio; struct completion done; unsigned long key;
 bool active,owned; int status,refs; u64 response; u8 endpoint,tag,expected_opcode;
 void(*callback)(void*,int,u64);void *callback_data;
};
static bool locked;static int tags_freed,puts,callbacks,notifies,waits,wakes;
static void(*on_wait)(void);
#define xa_lock_irqsave(p,f) do{(void)(p);(f)=0;assert(!locked);locked=true;}while(0)
#define xa_unlock_irqrestore(p,f) do{(void)(p);(void)(f);assert(locked);locked=false;}while(0)
static struct apple_sio_async *xa_load(struct xarray*x,unsigned long k){return x->slot&&x->slot->key==k?x->slot:NULL;}
static void __xa_erase(struct xarray*x,unsigned long k){assert(locked);assert(x->slot->key==k);x->slot=NULL;}
static unsigned long apple_sio_request_key(u8 e,u8 t){return ((unsigned long)e<<8)|t;}
static bool apple_sio_is_ready(u64 m){(void)m;return false;}
static void apple_sio_submit_setup(struct apple_sio*s){(void)s;assert(0);}
static void apple_sio_tag_free(struct apple_sio*s,u8 e,u8 t){(void)s;(void)e;(void)t;assert(!locked);tags_freed++;}
static void apple_sio_async_put(struct apple_sio_async*r){assert(r->refs>0);r->refs--;puts++;}
static void complete_all(struct completion*c){c->done=true;}
static bool atomic_dec_and_test(int*n){assert(*n>0);return --*n==0;}
static void wake_up_all(int*q){(void)q;assert(!locked);wakes++;}
static void wait_for_completion(struct completion*c){assert(!locked);waits++;if(!c->done&&on_wait)on_wait();assert(c->done);}
static unsigned long wait_for_completion_timeout(struct completion*c,unsigned long t){assert(!locked);assert(t);return c->done;}
static void cb(void*d,int status,u64 response){struct apple_sio_async*r=d;(void)status;(void)response;assert(!locked);assert(!r->done.done);assert(r->sio->owned_pending==1);callbacks++;}
static void notify(void*d,u64 response){(void)d;(void)response;assert(!locked);notifies++;}
'''
functions=''.join(extract(core,n) for n in ['apple_sio_dispatch','apple_sio_async_finish','apple_sio_async_cancel','apple_sio_async_wait'])
mid=r'''
struct sio_dma {struct apple_sio*sio;void*dev;};
struct sio_dma_chan {struct sio_dma*host;u8 endpoint;bool faulted;};
static struct apple_sio_async request;
static void sio_dma_fault(struct sio_dma_chan*c){c->faulted=true;}
static struct apple_sio_async *apple_sio_request_async_owned(struct apple_sio*s,u8 e,u8 op,u8 p,u32 d,u8 expect,void*cb,void*data){(void)s;(void)e;(void)op;(void)p;(void)d;(void)cb;(void)data;assert(expect==0x65);return &request;}
'''
helper=extract(dma,'sio_dma_request_owned')
main=r'''
static u64 msg(u8 e,u8 t,u8 op,u8 p){return e|((u64)t<<8)|((u64)op<<16)|((u64)p<<24);}
static struct apple_sio sio;
static void init(u8 expected,bool owned){
 memset(&sio,0,sizeof(sio));memset(&request,0,sizeof(request));
 request=(struct apple_sio_async){.sio=&sio,.endpoint=0x5b,.tag=3,.expected_opcode=expected,.owned=owned,.active=true,.refs=2,.status=-EINPROGRESS,.callback=cb};
 request.callback_data=&request;request.key=apple_sio_request_key(request.endpoint,request.tag);
 sio.pending.slot=&request;sio.owned_pending=owned?1:0;sio.notify[0x5b].fn=notify;
 tags_freed=puts=callbacks=notifies=waits=wakes=0;on_wait=NULL;
}
static void deliver(void){apple_sio_dispatch(&sio,msg(0x5b,3,request.expected_opcode,0x80));}
int main(void){
 init(0x68,true);
 apple_sio_dispatch(&sio,msg(0x5b,3,0x66,0));
 apple_sio_dispatch(&sio,msg(0x5b,3,0x6a,0));
 apple_sio_dispatch(&sio,msg(0x5b,3,0x65,0));
 apple_sio_dispatch(&sio,msg(0x5b,3,0x68,0));
 assert(notifies==4&&request.active&&sio.pending.slot==&request&&sio.owned_pending==1);
 assert(!tags_freed&&!callbacks&&!request.done.done);
 assert(apple_sio_async_cancel(&request)==-EBUSY);
 assert(apple_sio_async_wait(&request,10,NULL)==-ETIME);
 assert(request.active&&!tags_freed&&!puts);
 on_wait=deliver;assert(!apple_sio_async_wait(&request,0,NULL));
 assert(callbacks==1&&tags_freed==1&&puts==1&&wakes==1&&!sio.owned_pending);
 assert(!request.active&&!sio.pending.slot&&request.done.done);
 assert(apple_sio_async_cancel(&request)==-EALREADY);
 apple_sio_dispatch(&sio,msg(0x5b,3,0x68,0x80));assert(callbacks==1);
 init(0x65,true);request.callback=NULL;
 struct sio_dma host={.sio=&sio};struct sio_dma_chan chan={.host=&host,.endpoint=0x5b};
 on_wait=deliver;
 assert(sio_dma_request_owned(&chan,5,123,10)==0);
 assert(chan.faulted&&request.done.done&&puts==2&&tags_freed==1);
 init(0x65,true);request.callback=NULL;deliver();chan.faulted=false;
 assert(!sio_dma_request_owned(&chan,5,123,10)&&!chan.faulted);
 /* Proven never-published send failure may safely retire an owned request. */
 init(0x68,true);sio.pending.slot=NULL;request.active=false;
 apple_sio_async_finish(&request,-ESHUTDOWN,0,true);
 assert(request.status==-ESHUTDOWN&&callbacks==1&&tags_freed==1&&!sio.owned_pending);
 init(0x68,false);request.callback=NULL;
 assert(!apple_sio_async_cancel(&request)&&request.status==-ECANCELED&&tags_freed==1);
 puts("PASS: expected-only retirement, errors, idle, cancellation, late reply, timeout poisoning, never-published failure");
 return 0;
}
'''
# Avoid clash with stdio puts.
code=(prelude+functions+mid+helper+main).replace('puts,','put_count,').replace('puts++;','put_count++;').replace('puts=','put_count=').replace('!puts','!put_count').replace('puts==','put_count==')
with tempfile.TemporaryDirectory(prefix='sio-owned-test-') as t:
    src=Path(t)/'test.c';exe=Path(t)/'test';src.write_text(code)
    subprocess.run(shlex.split(os.environ.get('CC','cc'))+['-std=gnu11','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True,timeout=5)

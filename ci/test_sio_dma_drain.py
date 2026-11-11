"""Extract actual DMA completion/stop functions and model deterministic event order."""
import argparse,os,shlex,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);a=p.parse_args();text=(a.source/'drivers/dma/apple-sio-dma.c').read_text()
def extract(name):
 start=text.index(name+'(');start=text.rfind('\n',0,start)+1
 if text[start:].startswith(name):start=text.rfind('\n',0,start-1)+1
 begin=text.index('{',start);level=1;i=begin+1
 while level:level+=(text[i]=='{')-(text[i]=='}');i+=1
 return text[start:i]+'\n'
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8;typedef uint64_t u64;
#define SIO_DMA_OP_STOP 8
#define SIO_DMA_OP_ACK 0x65
#define SIO_DMA_OP_COMPLETE 0x68
#define SIO_DMA_OP_ASYNC_ERROR 0x66
#define SIO_DMA_STOP_TIMEOUT_MS 200
#define SIO_DMA_DRAIN_TIMEOUT_MS 500
#define SIO_DMA_SUBMIT_RETRIES 3
#define SIO_DMA_MSG_OPCODE 0xff0000ULL
#define SIO_DMA_MSG_DATA 0xffffffff00000000ULL
#define FIELD_GET(mask,v) (((v)&(mask)) >> __builtin_ctzll(mask))
#define BIT_ULL(n) (1ULL<<(n))
#define container_of(p,t,m) ((t*)((char*)(p)-offsetof(t,m)))
#define READ_ONCE(x) (x)
#define WARN_ON_ONCE(x) (!!(x))
#define DMA_TRANS_ABORTED 1
#define DMA_TRANS_NOERROR 0
#define dev_err(...) do{}while(0)
#define dev_err_ratelimited(...) do{}while(0)
#define dev_dbg(...) do{}while(0)
struct work_struct {int unused;};struct completion {bool done;};
struct virt_dma_desc {struct {int result;size_t residue;}tx_result;};
struct virt_dma_chan {int lock,desc_issued;struct virt_dma_desc*cyclic;};
struct sio_dma {void*dev;};struct sio_dma_desc;
struct sio_dma_chan {struct virt_dma_chan vc;struct sio_dma*host;u8 endpoint;struct sio_dma_desc*active;unsigned inflight;bool stopping,faulted,idle_seen;struct work_struct submit_work,stop_work;struct completion drained;};
struct sio_dma_desc {struct virt_dma_desc vd;struct sio_dma_chan*chan;bool cyclic;int status;unsigned done;size_t total;};
struct sio_dma_block {struct sio_dma_desc*desc;bool queued;};
static bool locked;static int requeues,terminated,periods,flushes,requests,sleeps,unsent;
static void(*on_request)(void),(*on_wait)(void);
static jmp_buf blocked;
static int system_highpri_wq;
#define spin_lock_irqsave(l,f) do{(void)(l);(f)=0;assert(!locked);locked=true;}while(0)
#define spin_unlock_irqrestore(l,f) do{(void)(l);(void)(f);assert(locked);locked=false;}while(0)
static void complete(struct completion*c){c->done=true;}
static void queue_work(int q,struct work_struct*w){(void)q;(void)w;requeues++;}
static void vchan_cyclic_callback(struct virt_dma_desc*d){(void)d;periods++;}
static void vchan_cookie_complete(struct virt_dma_desc*d){(void)d;assert(0);}
static void vchan_terminate_vdesc(struct virt_dma_desc*d){(void)d;assert(locked);terminated++;}
static bool list_empty(int*l){return !*l;}
static void flush_work(struct work_struct*w){(void)w;assert(!locked);flushes++;}
static unsigned long msecs_to_jiffies(unsigned t){return t;}
static unsigned long wait_for_completion_timeout(struct completion*c,unsigned long t){assert(!locked);assert(t);return c->done;}
static void wait_for_completion(struct completion*c){assert(!locked);if(on_wait)on_wait();if(!c->done)longjmp(blocked,1);}
static void msleep(unsigned ms){assert(!locked);assert(ms==100);sleeps++;}
static int sio_dma_request_owned(struct sio_dma_chan*c,u8 op,unsigned d,unsigned long t){(void)c;assert(op==8&&!d&&t);assert(!locked);requests++;if(unsent){unsent--;return -ENOMEM;}if(on_request)on_request();return 0;}
'''
func=''.join(extract(n) for n in ['sio_dma_fault','sio_dma_block_done','sio_dma_stop_work','sio_dma_notify'])
main=r'''
static struct sio_dma host;static struct sio_dma_chan chan;static struct sio_dma_desc desc;static struct sio_dma_block block;
static void init(void){
 memset(&chan,0,sizeof(chan));memset(&desc,0,sizeof(desc));memset(&block,0,sizeof(block));
 chan.host=&host;chan.active=&desc;chan.inflight=1;chan.stopping=true;chan.vc.desc_issued=1;desc.chan=&chan;desc.cyclic=true;block.desc=&desc;block.queued=true;
 locked=false;requeues=terminated=periods=flushes=requests=sleeps=unsent=0;on_request=on_wait=NULL;
}
static void done(void){sio_dma_block_done(&block,0,0x80680000);}
static void idle(void){sio_dma_notify(&chan,0x00680000);}
int main(void){
 init();on_request=done;sio_dma_stop_work(&chan.stop_work);
 assert(terminated==1&&!chan.active&&!chan.inflight&&!chan.stopping&&chan.idle_seen);
 assert(requeues==1&&!periods&&requests==1&&flushes==1);
 init();idle();assert(!chan.drained.done&&!chan.idle_seen&&chan.inflight==1);
 sio_dma_notify(&chan,0x80680000);assert(!chan.drained.done);
 sio_dma_block_done(&block,-ETIMEDOUT,0);assert(!chan.inflight&&!chan.idle_seen&&!chan.drained.done);
 idle();assert(chan.drained.done&&chan.idle_seen);
 init();on_wait=done;sio_dma_stop_work(&chan.stop_work);
 assert(chan.faulted&&terminated==1&&!requeues&&!periods);
 init();if(!setjmp(blocked)){sio_dma_stop_work(&chan.stop_work);assert(0);}
 assert(chan.faulted&&chan.active==&desc&&block.queued&&chan.inflight==1&&!terminated&&!requeues);
 init();unsent=3;on_request=done;sio_dma_stop_work(&chan.stop_work);
 assert(requests==4&&sleeps==3&&chan.faulted&&terminated==1&&!requeues);
 init();chan.inflight=0;block.queued=false;on_request=idle;sio_dma_stop_work(&chan.stop_work);
 assert(chan.idle_seen&&terminated==1&&!periods);
 init();sio_dma_notify(&chan,0x00660000);assert(chan.faulted&&chan.inflight==1&&block.queued&&!chan.drained.done);
 puts("PASS: completion before ACK, idle ordering, no synthetic idle, missing completion retains, late completion poisoned, unsent STOP retries");
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='sio-drain-') as t:
 src=Path(t)/'test.c';exe=Path(t)/'test';src.write_text(pre+func+main)
 subprocess.run(shlex.split(os.environ.get('CC','cc'))+['-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-value','-Wno-unused-parameter',str(src),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,timeout=5)

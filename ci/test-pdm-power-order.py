from pathlib import Path
import subprocess
import sys
import tempfile
src=(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).with_name('t8010-pdm.c')).read_text()
a=src.index('static void pdm_power_down(');b=src.index('\nstatic void pdm_mark_stopped',a)
fn=src[a:b]
c=r'''
#include <assert.h>
#include <stdbool.h>
#include <string.h>
#include <setjmp.h>
#include <stdio.h>
#define PDM_DECIMATORS 2
#define EIO 5
struct t8010_pdm { bool powered,clocked,irq_enabled,prepared; int irq; void *dev,*clock; struct {void *base;} dec[2]; };
static char logbuf[100]; static int pos,rxerr,dmaerr,pmerr,clkerr; static bool retention; static jmp_buf fault;
static void logc(char c) {logbuf[pos++]=c;logbuf[pos]=0;}
static int pdm_stop_receiver(struct t8010_pdm*p){logc('R');return rxerr;}
static int dmaengine_terminate_sync(void*p){logc('D');return dmaerr;}
static void __attribute__((noreturn)) pdm_retain_fault(struct t8010_pdm*p,const char*s,int e){logc('F');longjmp(fault,1);}
static void disable_irq(int i){logc('I');}
static void writel(int i,void*p){assert(i==0x1111);logc('G');}
static int pm_runtime_put_sync(void*p){logc('P');return pmerr;}
static int apple_aop_pdm_clock_stop(void*p){logc('C');return clkerr;}
static bool apple_aop_pdm_clock_needs_retention(void*p){logc('N');return retention;}
'''.replace('int irq;','int irq; void *dma;')+fn+r'''
static void run(bool active,int r,int d,int p,int c,bool uncertain,const char*expected,bool parks){
 struct t8010_pdm x={.powered=active,.clocked=active,.irq_enabled=active,.prepared=active};
 pos=0;rxerr=r;dmaerr=d;pmerr=p;clkerr=c;retention=uncertain;
 int failed=setjmp(fault);if(!failed)pdm_power_down(&x);
 assert(!!failed==parks);assert(!strcmp(logbuf,expected));
}
int main(void){
 run(true,0,0,0,0,false,"RDIGGPCN",false);
 run(false,0,0,0,0,false,"RDN",false);
 run(true,-1,0,0,0,false,"RDF",true);
 run(true,0,-1,0,0,false,"RDF",true);
 run(true,0,0,-1,0,false,"RDIGGPF",true);
 run(true,0,0,0,-1,true,"RDIGGPCF",true);
 run(false,0,0,0,0,true,"RDNF",true);
 puts("7 actual power_down ordering/failure cases passed");
}
'''
out=Path(tempfile.mkdtemp(prefix='j71b-pdm-order-')) / 'test_power_order.c';out.write_text(c)
subprocess.run(['cc','-std=gnu11','-fsanitize=address,undefined','-g',str(out),'-o',str(out.with_suffix(''))],check=True)
subprocess.run([str(out.with_suffix(''))],check=True)

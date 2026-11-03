"""Exercise actual prepare code with mocked dependencies; no hardware claims."""
from pathlib import Path
import subprocess
import sys
import tempfile
src = (Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name('t8010-pdm.c')).read_text()
a = src.index('static int pdm_prepare_locked(')
b = src.index('\nstatic int pdm_trigger(', a)
c = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <setjmp.h>
#include <string.h>
typedef uint32_t u32;
#define PDM_DECIMATORS 2
#define EINVAL 22
#define roundup(x,y) (((x)+(y)-1)/(y)*(y))
#define min(x,y) ((x)<(y)?(x):(y))
#define GENMASK(h,l) (((1u<<((h)+1))-1) & ~((1u<<(l))-1))
struct pdm_filter { unsigned frequency; };
struct pdm_decimator { int unused; };
struct t8010_pdm {
 bool shutting_down,powered,clocked,prepared,irq_enabled;
 struct pdm_decimator dec[2]; unsigned rate,position; void *discard,*clock,*dev,*base; int irq;
};
struct snd_soc_component { struct t8010_pdm *pdm; };
struct snd_pcm_substream {};
static struct pdm_filter filter = {2400000};
static char events[128]; static unsigned n,mmio;
static int start_error,stop_error,pm_error; static bool retained; static jmp_buf fault;
static void log_event(char c) {events[n++]=c;events[n]=0;}
static void *snd_soc_component_get_drvdata(struct snd_soc_component *c) {return c->pdm;}
static const struct pdm_filter *pdm_find_filter(void *d,unsigned r) {return &filter;}
static void pdm_mark_stopped(struct t8010_pdm *p) {log_event('M');}
static void pdm_power_down(struct t8010_pdm *p) {log_event('D');}
static int apple_aop_pdm_clock_stop(void *p) {log_event('O');return stop_error;}
static int apple_aop_pdm_clock_start(void *p,unsigned f) {assert(f==2400000);log_event('S');return start_error;}
static bool apple_aop_pdm_clock_needs_retention(void *p) {log_event('N');return retained;}
static void __attribute__((noreturn)) pdm_retain_fault(struct t8010_pdm *p,const char *why,int error) {log_event('F');longjmp(fault,1);}
static int pm_runtime_resume_and_get(void *p) {log_event('P');return pm_error;}
static void writel(u32 v,void *p) {mmio++;log_event('W');}
static int pdm_reset(struct t8010_pdm *p) {log_event('R');return 0;}
static u32 readl(void *p) {mmio++;log_event('L');return 64<<16;}
static void pdm_program_decimator(void *d,const void *f,unsigned i) {mmio++;log_event('G');}
static int pdm_queue_dma(struct t8010_pdm *p,struct snd_pcm_substream *s) {log_event('Q');return 0;}
static void enable_irq(int i) {log_event('I');}
''' + src[a:b] + r'''
static void run(int start,int stop,int pm,bool uncertain,const char *expect,bool parks) {
 char registers[256]; struct t8010_pdm p={.base=registers,.rate=48000,.discard=registers};
 struct snd_soc_component c={&p}; struct snd_pcm_substream s;
 n=mmio=0;start_error=start;stop_error=stop;pm_error=pm;retained=uncertain;
 int jumped=setjmp(fault); if(!jumped)pdm_prepare_locked(&c,&s);
 assert(!!jumped==parks); assert(!strcmp(events,expect));
 /* All tested failures must stop before any MMIO or DMA submission. */
 if(start || stop || pm<0) assert(mmio==0);
}
int main(void) {
 run(0,0,-1,false,"MDOSPF",true);
 run(-1,0,0,true,"MDOSNF",true);
 run(0,-1,0,true,"MDONF",true);
 run(-1,0,0,false,"MDOSND",false);
 run(0,-1,0,false,"MDOND",false);
 run(0,0,0,false,"MDOSPWRLWWWWGGQWI",false);
 run(0,0,1,false,"MDOSPWRLWWWWGGQWI",false);
 puts("7 actual prepare ordering/failure cases passed");
}
'''
out = Path(tempfile.mkdtemp(prefix='j71b-pdm-prepare-')) / 'test.c'
out.write_text(c)
subprocess.run(['cc', '-std=gnu11', '-fsanitize=address,undefined', '-g', str(out), '-o', str(out.with_suffix(''))], check=True)
subprocess.run([str(out.with_suffix(''))], check=True)

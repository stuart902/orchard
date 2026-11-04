#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
# Source-extracted MCA IRQ tests; mocks do not validate hardware or ALSA locking.
from pathlib import Path
import re,subprocess,os,tempfile
src=(Path(os.environ['LINUX_TREE']) / 'sound/soc/apple/s8000-mca.c').read_text() if 'LINUX_TREE' in os.environ else Path(__file__).with_name('s8000-mca.c').read_text()
# Keep fixture register bits and variant dispatch contracts tied to production.
for name, bit in [('TX_UNDERFLOW', 0), ('TX_OVERFLOW', 1),
                  ('RX_UNDERFLOW', 3), ('RX_OVERFLOW', 4), ('FRAME_ERROR', 6)]:
 assert re.search(r'#define\s+MCA_IRQ_' + name + r'\s+BIT\(' + str(bit) + r'\)', src)
for name, expected in [('s8000_mca_hw', None), ('t8010_mca_hw', 'MCA_IRQ_FRAME_ERROR')]:
 m=re.search(r'static const struct s8000_mca_hw ' + name + r' = \{(.*?)\n\};', src, re.S);assert m
 field=re.search(r'\.stream_irqs\s*=\s*(\w+)\s*,',m[1])
 assert (field[1] if field else None) == expected
def function(name):
 m=re.search(r'^static (?:int|void|irqreturn_t) '+name+r'\(',src,re.M);assert m
 start=m.start();o=src.index('{',m.end());depth=1;i=o+1
 while depth:
  depth+=(src[i]=='{')-(src[i]=='}');i+=1
 return src[start:i]
head=r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stddef.h>
typedef uint32_t u32; typedef int irqreturn_t;
#define BIT(x) (1U<<(x))
#define IRQ_NONE 0
#define IRQ_HANDLED 1
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define SNDRV_PCM_STREAM_CAPTURE 1
#define MCA_IRQ_STATUS 0x1c
#define MCA_IRQ_MASK 0x20
#define MCA_IRQ_TX_CAUSES 3U
#define MCA_IRQ_RX_CAUSES 24U
#define MCA_IRQ_FRAME_ERROR 64U
#define MCA_IRQ_ERRORS (3U|24U|MCA_IRQ_FRAME_ERROR)
#define MCA_IRQ_ALL 8191U
struct snd_pcm {bool nonatomic;};
struct snd_pcm_substream {int stream;struct snd_pcm *pcm;};
struct s8000_mca_hw {u32 stream_irqs;};
struct s8000_mca {const struct s8000_mca_hw *hw;int hw_lock,irq; unsigned int run_mask,irq_mask;struct snd_pcm_substream *streams[2];u32 regs[64];void *dev;};
struct snd_soc_dai {struct s8000_mca *mca;};
struct snd_soc_component {struct s8000_mca *mca;};
#define snd_soc_component_get_drvdata(c) ((c)->mca)
static struct s8000_mca *active;static int stopped[2],synced;
#define snd_soc_dai_get_drvdata(dai) ((dai)->mca)
#define spin_lock(p) do {assert(!*(p));*(p)=1;} while(0)
#define spin_unlock(p) do {assert(*(p));*(p)=0;} while(0)
#define spin_lock_irqsave(p,f) do {(f)=0;spin_lock(p);} while(0)
#define spin_unlock_irqrestore(p,f) do {(void)(f);spin_unlock(p);} while(0)
#define dev_dbg_ratelimited(...) ((void)0)
static u32 mca_read(struct s8000_mca *m,u32 r){return m->regs[r/4];}
static void mca_write(struct s8000_mca *m,u32 r,u32 v){m->regs[r/4]=v;}
static void synchronize_irq(int irq){assert(irq==active->irq);assert(!active->hw_lock);synced++;}
static void snd_pcm_stop_xrun(struct snd_pcm_substream *s){assert(!active->hw_lock);stopped[s->stream]++;active->run_mask&=~BIT(s->stream);}
'''
main=r'''
static const struct s8000_mca_hw s8000={0},t8010={MCA_IRQ_FRAME_ERROR};
static struct s8000_mca m;static struct snd_soc_dai d={&m};static struct snd_pcm pcm;static struct snd_pcm_substream tx={0,&pcm},rx={1,&pcm};
static void setup(u32 status,u32 run,u32 mask){m=(struct s8000_mca){.hw=&s8000,.irq=7,.run_mask=run,.irq_mask=mask};active=&m;stopped[0]=stopped[1]=synced=0;mca_startup(&tx,&d);mca_startup(&rx,&d);m.regs[MCA_IRQ_STATUS/4]=status;}
int main(void){
setup(1,1,0);assert(mca_irq(7,&m)==IRQ_HANDLED);assert(stopped[0]==1&&!stopped[1]);assert(m.irq_mask==1);
setup(2,1,0);mca_irq(7,&m);assert(stopped[0]==1&&!stopped[1]);
setup(8,2,0);mca_irq(7,&m);assert(!stopped[0]&&stopped[1]==1);
setup(16,2,0);mca_irq(7,&m);assert(!stopped[0]&&stopped[1]==1);
setup(1|16,3,0);mca_irq(7,&m);assert(stopped[0]==1&&stopped[1]==1);
setup(1,0,0);mca_irq(7,&m);assert(!stopped[0]&&!stopped[1]);
setup(1,1,1);assert(mca_irq(7,&m)==IRQ_NONE);assert(!stopped[0]);
setup(BIT(31),3,0);assert(mca_irq(7,&m)==IRQ_NONE);assert(!stopped[0]&&!stopped[1]);
setup(BIT(2),1,0);mca_irq(7,&m);assert(!stopped[0]);
setup(1,2,0);mca_irq(7,&m);assert(!stopped[0]&&!stopped[1]);
setup(1,1,0);mca_shutdown(&tx,&d);assert(m.streams[0]==NULL&&m.streams[1]==&rx&&synced==1);mca_irq(7,&m);assert(!stopped[0]);
setup(0,0,0);mca_shutdown(&tx,&d);mca_startup(&tx,&d);assert(m.streams[0]==&tx&&synced==1);
pcm.nonatomic=true;assert(mca_startup(&tx,&d)==-EOPNOTSUPP);pcm.nonatomic=false;
struct snd_soc_component component={&m};synced=0;assert(mca_sync_stop(&component,&tx)==0);assert(synced==1);
setup(MCA_IRQ_FRAME_ERROR,1,0);m.hw=&t8010;mca_irq(7,&m);assert(stopped[0]==1&&!stopped[1]);assert(m.irq_mask==MCA_IRQ_FRAME_ERROR);
setup(MCA_IRQ_FRAME_ERROR,0,0);m.hw=&t8010;mca_irq(7,&m);assert(!stopped[0]&&!stopped[1]);
setup(MCA_IRQ_FRAME_ERROR,1,MCA_IRQ_FRAME_ERROR);m.hw=&t8010;assert(mca_irq(7,&m)==IRQ_NONE);assert(!stopped[0]);
setup(MCA_IRQ_FRAME_ERROR,1,0);mca_irq(7,&m);assert(!stopped[0]&&!stopped[1]);
setup(MCA_IRQ_FRAME_ERROR,2,0);m.hw=&t8010;mca_irq(7,&m);assert(!stopped[0]&&!stopped[1]);
setup(MCA_IRQ_FRAME_ERROR|1,1,0);m.hw=&t8010;mca_irq(7,&m);assert(stopped[0]==1&&!stopped[1]);
setup(MCA_IRQ_FRAME_ERROR,1,0);m.hw=&t8010;mca_shutdown(&tx,&d);mca_irq(7,&m);assert(!stopped[0]&&!stopped[1]);
puts("21 actual MCA IRQ/lifecycle cases passed");return 0;}
'''
with tempfile.TemporaryDirectory() as t:
 c=Path(t)/'test.c';exe=Path(t)/'test';c.write_text(head+'\n'.join(function(n) for n in ['mca_startup','mca_shutdown','mca_sync_stop','mca_irq'])+main)
 subprocess.run(['cc','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=address,undefined','-g',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})

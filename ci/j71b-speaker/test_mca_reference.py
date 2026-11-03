from pathlib import Path
import os, subprocess, tempfile
r=Path(os.environ['LINUX_TREE']);s=(r/'sound/soc/apple/s8000-mca.c').read_text()
macros='\n'.join(l for l in s.splitlines() if l.startswith('#define MCA_') or l.startswith('#define  MCA_'))
# Only constants referenced by these functions are expanded by the compiler.
helpers=s[s.index('static int mca_set_fmt'):s.index('static void mca_write_tx')]
helpers+=s[s.index('static int mca_dai_probe'):s.index('static const struct snd_soc_dai_ops mca_dai_ops')]
stub=r'''
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <errno.h>
#include <stdio.h>
typedef uint32_t u32;
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) ((~0U>>(31-(h)))&(~0U<<(l)))
#define FIELD_PREP(mask,val) ((val)<<__builtin_ctz(mask))
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define max_t(t,a,b) ((t)(a)>(t)(b)?(t)(a):(t)(b))
#define round_up(n,a) (((n)+(a)-1)/(a)*(a))
#define CONFIG_SND_SOC_APPLE_J71B_DIGITAL 1
#define IS_ENABLED(n) (n)
#define SND_SOC_DAIFMT_CLOCK_PROVIDER_MASK 0xf000
#define SND_SOC_DAIFMT_BP_FP 0x1000
#define SND_SOC_DAIFMT_BC_FC 0x4000
#define SND_SOC_DAIFMT_FORMAT_MASK 0xf
#define SND_SOC_DAIFMT_I2S 1
#define SND_SOC_DAIFMT_INV_MASK 0xf00
#define SND_SOC_DAIFMT_NB_NF 0
#define SNDRV_PCM_STREAM_PLAYBACK 0
#define DMA_SLAVE_BUSWIDTH_2_BYTES 2
#define DMA_SLAVE_BUSWIDTH_4_BYTES 4
struct snd_dmaengine_dai_dma_data {unsigned int addr_width,maxburst;};
struct s8000_mca_hw {bool clock_provider;unsigned int version;bool reference_capable;};
struct clock {unsigned long rate;int error;bool round_bad;};
struct snd_pcm_hardware {unsigned int channels_max;};
struct snd_dmaengine_pcm_config {void *pcm_hardware;};
struct snd_soc_dai_driver {struct {unsigned int channels_max;} playback;};
struct s8000_mca {struct snd_pcm_hardware pcm_hw;struct snd_soc_dai_driver dai_drv;const struct s8000_mca_hw *hw;bool format_set,reference_profile,reference_faulted,capture;unsigned int sw_aud,sw_pin,prep_mask,run_mask,fifo_tx;struct clock *bitclk;u32 sample,frame,tx_cfg,tx_fifo_cfg,tx_slots,rx_slots;struct snd_dmaengine_dai_dma_data dma_tx,dma_rx;};
struct snd_soc_dai {struct s8000_mca *m;};
#define dev_err(...) ((void)0)
static int dma_inits;
static void snd_soc_dai_init_dma_data(struct snd_soc_dai *d,void *tx,void *rx){(void)d;(void)tx;(void)rx;dma_inits++;}
static struct s8000_mca *snd_soc_dai_get_drvdata(struct snd_soc_dai *d){return d->m;}
struct snd_pcm_substream {unsigned int stream;};
struct snd_pcm_hw_params {unsigned int bits,slot,channels,rate;};
#define params_width(p) ((p)->bits)
#define params_physical_width(p) ((p)->slot)
#define params_channels(p) ((p)->channels)
#define params_rate(p) ((p)->rate)
static int clk_set_rate(struct clock *c,unsigned long r){if(c->error)return c->error;c->rate=r+(c->round_bad?1:0);return 0;}
static unsigned long clk_get_rate(struct clock *c){return c->rate;}
'''
cases=r'''
int main(void){
 const struct s8000_mca_hw h={true,5,true};struct clock clk={0};
 struct s8000_mca m={.hw=&h,.sw_aud=2,.sw_pin=2,.fifo_tx=64,.bitclk=&clk};
 struct snd_soc_dai d={&m};struct snd_pcm_substream sub={0};
 struct snd_pcm_hw_params p={16,16,2,48000};
 assert(!mca_set_fmt(&d,SND_SOC_DAIFMT_BP_FP|SND_SOC_DAIFMT_I2S));
 assert(!mca_hw_params(&sub,&p,&d));assert(m.tx_cfg==0x137);assert(m.tx_slots==3);assert(m.rx_slots==3);assert(clk.rate==1536000);assert(m.frame==0x0f10104d);
 p.bits=p.slot=32;assert(!mca_hw_params(&sub,&p,&d));assert(m.frame==0x1f40104d);assert(clk.rate==3072000);
 assert(mca_set_tdm_slot(&d,15,0,8,16)==-EINVAL);
 m.format_set=false; const struct s8000_mca_hw ordinary={true,5,false};m.hw=&ordinary;assert(mca_set_tdm_slot(&d,15,0,8,16)==-EINVAL);m.hw=&h;
 assert(mca_set_tdm_slot(&d,3,0,2,16)==-EINVAL);
 assert(!mca_set_tdm_slot(&d,15,0,8,16));assert(m.pcm_hw.channels_max==4&&m.dai_drv.playback.channels_max==4);
 assert(mca_set_fmt(&d,SND_SOC_DAIFMT_BP_FP|SND_SOC_DAIFMT_I2S)==-EINVAL);
 p.bits=p.slot=16;p.channels=4;
 assert(!mca_hw_params(&sub,&p,&d));assert(m.frame==0x107001);assert(m.tx_cfg==0x133);assert(m.tx_slots==15);assert(m.rx_slots==0);assert(m.sample==0x1010);assert(clk.rate==6144000);
 p.channels=2;assert(mca_hw_params(&sub,&p,&d)==-EINVAL);p.channels=4;
 p.bits=p.slot=32;assert(mca_hw_params(&sub,&p,&d)==-EINVAL);p.bits=p.slot=16;
 p.rate=44100;assert(mca_hw_params(&sub,&p,&d)==-EINVAL);p.rate=48000;
 sub.stream=1;assert(mca_hw_params(&sub,&p,&d)==-EINVAL);sub.stream=0;
 clk.round_bad=true;assert(mca_hw_params(&sub,&p,&d)==-EINVAL);clk.round_bad=false;
 clk.error=-EIO;assert(mca_hw_params(&sub,&p,&d)==-EIO);
 clk.error=0;assert(!mca_set_tdm_slot(&d,0,0,0,0));assert(!m.reference_profile&&!m.format_set);assert(m.pcm_hw.channels_max==2&&m.dai_drv.playback.channels_max==2);assert(!mca_set_fmt(&d,SND_SOC_DAIFMT_BP_FP|SND_SOC_DAIFMT_I2S));
 assert(!mca_dai_remove(&d));assert(!m.format_set&&!m.reference_profile);assert(!mca_dai_probe(&d));assert(dma_inits==1);
 assert(!mca_set_tdm_slot(&d,15,0,8,16));assert(!mca_dai_remove(&d));assert(m.pcm_hw.channels_max==2&&!m.reference_profile);
 assert(!mca_set_tdm_slot(&d,15,0,8,16));m.prep_mask=1;
 assert(!mca_dai_remove(&d));assert(m.reference_faulted&&m.reference_profile);assert(mca_dai_probe(&d)==-EIO);assert(dma_inits==1);
 assert(mca_set_fmt(&d,SND_SOC_DAIFMT_BP_FP|SND_SOC_DAIFMT_I2S)==-EIO);assert(mca_set_tdm_slot(&d,15,0,8,16)==-EIO);assert(mca_set_tdm_slot(&d,0,0,0,0)==-EIO);
 puts("Current production MCA: normal stereo unchanged; reference profile and rejections passed");
}
'''
with tempfile.TemporaryDirectory() as td:
 t=Path(td);(t/'linux').mkdir();(t/'linux/types.h').write_text('#include <stdbool.h>\n#include <stdint.h>\ntypedef uint32_t u32;\n')
 (t/'test.c').write_text(stub+macros+'\n#include "t8010-mca-reference.h"\n'+helpers+cases)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all','-I'+str(t),'-I'+str(r/'sound/soc/apple'),str(t/'test.c'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)

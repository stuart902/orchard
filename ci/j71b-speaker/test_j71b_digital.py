"""Production machine-driver reset/format tests; synthetic GPIO only."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

STUB = r'''
#include <stdbool.h>
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
struct gpio_desc { bool low, sleep; int value, direction_error, read_error, set_error; bool fail_set; unsigned int writes, directions; };
static int gpiod_set_value(struct gpio_desc *g,int v) { assert(v==1);g->writes++;if(g->set_error)return g->set_error;if(!g->fail_set)g->value=v;return 0; }
static int gpiod_get_value(struct gpio_desc *g) { return g->read_error ? g->read_error : g->value; }
static int gpiod_is_active_low(struct gpio_desc *g) {return g->low;}
static int gpiod_cansleep(struct gpio_desc *g) {return g->sleep;}
static int gpiod_direction_output(struct gpio_desc *g,int v) { assert(v==1);g->directions++;if(g->direction_error)return g->direction_error;gpiod_set_value(g,v);return 0; }
struct device { void *data; };
struct snd_soc_card { struct device *dev; void *data; };
struct j71b_digital { struct snd_soc_card card; struct gpio_desc *reset; };
struct snd_soc_pcm_runtime {struct snd_soc_card *card;};
struct snd_pcm_substream {struct snd_soc_pcm_runtime *rtd;void *runtime;};
#define SNDRV_PCM_HW_PARAM_CHANNELS 1
#define SNDRV_PCM_HW_PARAM_RATE 2
#define SNDRV_PCM_HW_PARAM_FORMAT 3
#define SNDRV_PCM_FMTBIT_S16_LE 4
static int constraint_calls;
static int snd_pcm_hw_constraint_single(void *r,int which,int value){(void)r;assert((which==1&&value==4)||(which==2&&value==48000));constraint_calls++;return 0;}
static int snd_pcm_hw_constraint_mask64(void *r,int which,unsigned long value){(void)r;assert(which==3&&value==4);constraint_calls++;return 0;}

struct snd_pcm_hw_params { unsigned int format,channels,rate; };
#define snd_soc_substream_to_rtd(s) ((s)->rtd)
#define snd_soc_card_get_drvdata(c) ((c)->data)
#define dev_get_drvdata(d) ((d)->data)
#define snd_soc_rtd_to_cpu(r,i) ((void)(i),(r))
#define SNDRV_PCM_FORMAT_S16_LE 2
#define params_format(p) ((p)->format)
#define params_channels(p) ((p)->channels)
#define params_rate(p) ((p)->rate)
#define SNDRV_PCM_TRIGGER_START 0
#define SNDRV_PCM_TRIGGER_RESUME 1
#define SNDRV_PCM_TRIGGER_PAUSE_RELEASE 2
#define SNDRV_PCM_TRIGGER_STOP 3
#define SNDRV_PCM_TRIGGER_SUSPEND 4
#define SNDRV_PCM_TRIGGER_PAUSE_PUSH 5
static unsigned int errors,tdm_calls,suspends,resumes,poweroffs;
#define dev_err(...) (errors++)
static int snd_soc_dai_set_tdm_slot(void *d,unsigned int tx,unsigned int rx,int slots,int width) { (void)d;assert(tx==15&&rx==0&&slots==8&&width==16);tdm_calls++;return 0; }
static int snd_soc_suspend(struct device *d) { (void)d;suspends++;return 0; }
static int snd_soc_resume(struct device *d) { (void)d;resumes++;return 0; }
static int snd_soc_poweroff(struct device *d) { (void)d;poweroffs++;return 0; }
'''

CASES = r'''
int main(void) {
 struct gpio_desc g={.low=true};struct j71b_digital p={.reset=&g};
 struct device dev={&p.card};p.card.dev=&dev;p.card.data=&p;
 struct snd_soc_pcm_runtime rtd={&p.card};struct snd_pcm_substream stream={.rtd=&rtd};
 struct snd_pcm_hw_params params={SNDRV_PCM_FORMAT_S16_LE,4,48000};
 g.low=false;assert(j71b_reset_init(&p)==-EINVAL);assert(!g.writes&&!g.directions);
 g.low=true;g.sleep=true;assert(j71b_reset_init(&p)==-EINVAL);assert(!g.writes&&!g.directions);
 g.sleep=false;g.direction_error=-EIO;assert(j71b_reset_init(&p)==-EIO);assert(!g.writes);
 g.direction_error=0;assert(!j71b_reset_init(&p));assert(g.value==1);
 assert(!j71b_startup(&stream));assert(constraint_calls==3);assert(!j71b_prepare(&stream));assert(!j71b_link_init(&rtd));assert(tdm_calls==1);
 assert(!j71b_hw_params(&stream,&params));params.rate=44100;assert(j71b_hw_params(&stream,&params)==-EINVAL);
 params.channels=2;assert(j71b_hw_params(&stream,&params)==-EINVAL);params.channels=4;
 params.rate=32000;assert(j71b_hw_params(&stream,&params)==-EINVAL);params.rate=48000;
 params.format=3;assert(j71b_hw_params(&stream,&params)==-EINVAL);params.format=SNDRV_PCM_FORMAT_S16_LE;
 for(int cmd=0;cmd<=5;cmd++)assert(!j71b_trigger(&stream,cmd));
 unsigned int writes=g.writes;assert(j71b_trigger(&stream,99)==-EINVAL);assert(writes==g.writes);
 g.set_error=-EIO;assert(j71b_hold_reset(&p)==-EIO);g.set_error=0;
 g.read_error=-EIO;assert(j71b_startup(&stream)==-EIO);assert(j71b_trigger(&stream,0)==-EIO);
 assert(j71b_link_init(&rtd)==-EIO);assert(tdm_calls==1);
 assert(j71b_digital_suspend(&dev)==-EIO);assert(!suspends);
 assert(j71b_digital_resume(&dev)==-EIO);assert(!resumes);
 assert(j71b_digital_poweroff(&dev)==-EIO);assert(!poweroffs);
 j71b_shutdown_stream(&stream);assert(errors==1);j71b_reset_on_release(&p);assert(errors==2);
 g.read_error=0;g.fail_set=true;g.value=0;assert(j71b_hold_reset(&p)==-EIO);
 g.fail_set=false;assert(!j71b_digital_suspend(&dev));assert(suspends==1);
 assert(!j71b_digital_resume(&dev));assert(resumes==1&&g.value==1);
 assert(!j71b_digital_poweroff(&dev));assert(poweroffs==1);
 j71b_shutdown_stream(&stream);j71b_reset_on_release(&p);assert(errors==2&&g.value==1);
 puts("J71b digital machine reset remains asserted across lifecycle and faults");
}
'''

def production_source():
    return (Path(os.environ["LINUX_TREE"]) / "sound/soc/apple/j71b-digital.c").read_text()


class J71bDigitalTests(unittest.TestCase):
    def test_production_reset_lifecycle(self):
        compiler = shutil.which(os.environ.get("CC", "cc"))
        if not compiler:
            self.skipTest("native C compiler unavailable")
        source = production_source()
        helpers = source[source.index("static int j71b_hold_reset"):
                         source.index("/* No physical speaker positions")]
        helpers=helpers[:helpers.index("static void j71b_link_exit")] + helpers[helpers.index("static int j71b_card_hold_reset"):]
        helpers += source[source.index("static void j71b_reset_on_release"):
                          source.index("static int j71b_digital_probe")]
        helpers += source[source.index("static int j71b_digital_suspend"):
                          source.index("static const struct dev_pm_ops")]
        with tempfile.TemporaryDirectory() as tmp:
            src, exe = Path(tmp) / "test.c", Path(tmp) / "test"
            src.write_text(STUB + helpers + CASES)
            subprocess.run([compiler, "-std=gnu11", "-Wall", "-Wextra",
                            *shlex.split(os.environ.get("CFLAGS", "")),
                            str(src), "-o", str(exe)], check=True, capture_output=True, text=True)
            result = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            self.assertIn("reset remains asserted", result.stdout)

    def test_explicit_digital_only_contract(self):
        source = production_source()
        self.assertIn('devm_gpiod_get(dev, "reset", GPIOD_ASIS)', source)
        self.assertNotIn("snd_soc_dai_set_fmt(", source)
        self.assertNotIn(".dai_fmt =", source)
        self.assertIn("&snd_soc_dummy_dlc", source)
        self.assertEqual(source.count("SNDRV_CHMAP_UNKNOWN"), 4)
        self.assertNotIn("SNDRV_CHMAP_FL", source)
        self.assertNotIn("SNDRV_CHMAP_FR", source)

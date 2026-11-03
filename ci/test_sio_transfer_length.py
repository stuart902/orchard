"""Check actual completion handler's byte-count validation, without hardware."""
import argparse,ast,os,shlex,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);a=p.parse_args()
text=(a.source/'drivers/dma/apple-sio-dma.c').read_text();start=text.index('static void sio_dma_block_done(');end=text.index('static void sio_dma_submit_work(',start);function=text[start:end]
tree=ast.parse(Path(__file__).with_name('test_sio_dma_drain.py').read_text())
pre=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='pre' for t in n.targets))
pre=pre.replace('struct sio_dma_block {struct sio_dma_desc*desc;bool queued;};','struct sio_dma_block {struct sio_dma_desc*desc;bool queued;size_t len;};')
pre=pre.replace('static void vchan_cookie_complete(struct virt_dma_desc*d){(void)d;assert(0);}','static void vchan_cookie_complete(struct virt_dma_desc*d){(void)d;terminated++;}')
main=r'''
static struct sio_dma host;static struct sio_dma_chan chan;static struct sio_dma_desc desc;static struct sio_dma_block block;
static void init(bool cyclic){memset(&chan,0,sizeof(chan));memset(&desc,0,sizeof(desc));memset(&block,0,sizeof(block));chan.host=&host;chan.active=&desc;chan.inflight=1;desc.chan=&chan;desc.cyclic=cyclic;desc.total=1024;block.desc=&desc;block.queued=true;block.len=1024;locked=false;requeues=periods=terminated=0;}
static u64 reply(unsigned bytes){return ((u64)bytes<<32)|0x80680000;}
int main(void){
 init(true);sio_dma_block_done(&block,0,reply(1024));assert(periods==1&&requeues==1&&desc.done==1&&!desc.status&&!chan.inflight);
 init(true);sio_dma_block_done(&block,0,reply(512));assert(!periods&&!requeues&&!desc.done&&desc.status==-EIO&&!chan.inflight);
 block.queued=true;chan.inflight=1;sio_dma_block_done(&block,0,reply(1024));assert(!periods&&!requeues&&!desc.done&&desc.status==-EIO);
 init(true);sio_dma_block_done(&block,0,reply(0));assert(desc.status==-EIO&&!periods);
 init(true);sio_dma_block_done(&block,0,reply(2048));assert(desc.status==-EIO&&!periods);
 init(true);sio_dma_block_done(&block,-ESHUTDOWN,reply(1024));assert(desc.status==-ESHUTDOWN&&!periods);
 init(true);chan.stopping=true;sio_dma_block_done(&block,0,reply(128));assert(!desc.status&&!periods&&!chan.inflight&&chan.drained.done);
 init(false);sio_dma_block_done(&block,0,reply(512));assert(terminated==1&&desc.vd.tx_result.result==DMA_TRANS_ABORTED&&desc.vd.tx_result.residue==1024&&!chan.active);
 init(false);sio_dma_block_done(&block,0,reply(1024));assert(terminated==1&&desc.vd.tx_result.result==DMA_TRANS_NOERROR&&!desc.vd.tx_result.residue&&!chan.active);
 puts("PASS: exact, short, zero, excess, sticky cyclic error, transport error, STOP partial and noncyclic result");return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='sio-length-') as t:
 src=Path(t)/'test.c';exe=Path(t)/'test';src.write_text(pre+function+main)
 subprocess.run(shlex.split(os.environ.get('CC','cc'))+['-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-value','-Wno-unused-parameter','-Wno-unused-variable',str(src),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,timeout=5)

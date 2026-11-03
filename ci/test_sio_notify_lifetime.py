"""Run actual notifier replacement against a captured-IRQ callback model.

Usage: python3 kernel/tests/test_sio_notify_lifetime.py PREPARED_KERNEL_SOURCE
Requires a host C11 compiler (CC, default cc). No device or MMIO access.
"""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
args = parser.parse_args()
text = (args.source / 'drivers/soc/apple/apple-sio-core.c').read_text()
start = text.index('void apple_sio_set_notify(')
end = text.index('EXPORT_SYMBOL_GPL(apple_sio_set_notify)', start)
function = text[start:end]
prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
typedef uint8_t u8;
typedef void (*apple_sio_notify_t)(void *, uint64_t);
#define APPLE_SIO_MAX_ENDPOINTS 0x82
struct apple_sio {
    int pending, irq;
    bool irq_requested;
    struct { apple_sio_notify_t fn; void *data; } notify[APPLE_SIO_MAX_ENDPOINTS];
};
static bool locked;
static unsigned int waits, callbacks, may_sleep;
static apple_sio_notify_t captured;
static void *captured_data;
static struct apple_sio *current;
static apple_sio_notify_t expected_fn;
static void *expected_data;
struct context { bool alive; };
static void callback(void *data, uint64_t message) {
    struct context *c=data;
    (void)message;
    assert(c->alive); callbacks++;
}
#define xa_lock_irqsave(p,f) do { (void)(p); (f)=0; assert(!locked); locked=true; } while (0)
#define xa_unlock_irqrestore(p,f) do { (void)(p); (void)(f); assert(locked); locked=false; } while (0)
static __attribute__((unused)) void might_sleep(void) { may_sleep++; }
static __attribute__((unused)) void synchronize_irq(int irq) {
    (void)irq; assert(!locked); waits++;
    assert(current->notify[0x5b].fn == expected_fn);
    assert(current->notify[0x5b].data == expected_data);
    if (captured) { captured(captured_data,0); captured=NULL; }
}
'''
main = r'''
int main(void) {
    struct apple_sio sio={.irq_requested=true};
    struct context old={.alive=true}, next={.alive=true};
    current=&sio; expected_fn=callback; expected_data=&old;
    apple_sio_set_notify(&sio,0x5b,callback,&old);
    captured=sio.notify[0x5b].fn; captured_data=sio.notify[0x5b].data;
    expected_data=&next;
    apple_sio_set_notify(&sio,0x5b,callback,&next);
    assert(callbacks==1 && !captured); old.alive=false;
    captured=sio.notify[0x5b].fn; captured_data=sio.notify[0x5b].data;
    expected_fn=NULL; expected_data=NULL;
    apple_sio_set_notify(&sio,0x5b,NULL,NULL);
    assert(callbacks==2 && !captured); next.alive=false;
    assert(!sio.notify[0x5b].fn && !sio.notify[0x5b].data);
    assert(waits==3);
    sio.irq_requested=false;
    expected_fn=NULL; expected_data=NULL;
    apple_sio_set_notify(&sio,0x5b,NULL,NULL);
    apple_sio_set_notify(&sio,0xff,NULL,NULL);
    assert(waits==3 && may_sleep==5);
    return 0;
}
'''
compiler = shlex.split(os.environ.get('CC', 'cc'))
if not compiler:
    parser.error('CC must name a host C compiler')
with tempfile.TemporaryDirectory(prefix='sio-notify-test-') as temp:
    source = Path(temp) / 'test.c'
    binary = Path(temp) / 'test'
    source.write_text(prelude + function + main)
    subprocess.run(compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror',
                               str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=5)
print('PASS: registration, replacement, removal, absent IRQ, invalid endpoint')

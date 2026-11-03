#!/usr/bin/env python3
"""Repack precompiled components with Orchard's standard RAM assembler; no device I/O."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from orchard import ram, ram_session


def main():
    # This manifest covers immutable source/components, not relocated build receipts.
    for line in (ROOT / 'BUNDLE-SHA256SUMS').read_text().splitlines():
        expected, name = line.split('  ', 1)
        path = ROOT / name
        if path.is_symlink() or ROOT not in path.resolve().parents:
            raise ValueError(f'Invalid bundle path: {name}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Checksum mismatch: {name}')
    provenance = json.loads((ROOT / 'capture-test-provenance.json').read_text())
    if provenance['kernel_commit'] != 'b1694a574a8f12b4004f269ae4cc83e6f4b8a30b':
        raise ValueError('Unexpected kernel revision')
    payload = ROOT / 'examples/hardware-check'
    components = ROOT / 'capture-components'
    files = {str(p.relative_to(payload / 'rootfs')): p
             for p in (payload / 'rootfs').rglob('*') if p.is_file()}
    for tool in (components / 'boot').iterdir():
        if tool.name != 'busybox' and tool.is_file():
            files[ram.TOOL_DESTINATIONS.get(tool.name, 'usr/bin') + '/' + tool.name] = tool
    capture = ROOT / 'capture-userspace'
    for path in capture.rglob('*'):
        if path.is_file():
            destination = str(path.relative_to(capture))
            if destination in files:
                raise ValueError(f'Capture userspace conflicts with payload: {destination}')
            files[destination] = path
    if 'usr/bin/arecord' not in files:
        raise ValueError('Missing capture program')
    files.update(ram_session.payload_files())
    output = ram.assemble_ram(
        ROOT, payload / 'out/apple-16k', kernel=components / 'kernel',
        busybox=components / 'boot/busybox', loader=components / 'quiet/m1n1.bin',
        pongo=components / 'quiet/pongo.bin', init=payload / 'init', files=files,
        hostname='j71b-capture-test', platform='apple-16k', boards={'j71b': 't8010-j71b'},
        modules=True)
    receipt = json.loads((output / 'build.json').read_text())
    receipt['firmware'] = True
    (output / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    ram.verify_ram(output)
    print('Prepared experimental J71b capture image. No device was accessed.')
    print('No recording or playback starts automatically. Capture can hang until physical reset.')


if __name__ == '__main__':
    main()


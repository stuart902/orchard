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
    provenance = json.loads((ROOT / 'audio-test-provenance.json').read_text())
    if provenance['kernel_commit'] != '4d80a6b183d51565d442f745ea5e95160107e032':
        raise ValueError('Unexpected kernel revision')
    payload = ROOT / 'examples/hardware-check'
    components = ROOT / 'audio-components'
    files = {str(p.relative_to(payload / 'rootfs')): p
             for p in (payload / 'rootfs').rglob('*') if p.is_file()}
    for tool in (components / 'boot').iterdir():
        if tool.name != 'busybox' and tool.is_file():
            files[ram.TOOL_DESTINATIONS.get(tool.name, 'usr/bin') + '/' + tool.name] = tool
    files.update(ram_session.payload_files())
    output = ram.assemble_ram(
        ROOT, payload / 'out/apple-16k', kernel=components / 'kernel',
        busybox=components / 'boot/busybox', loader=components / 'quiet/m1n1.bin',
        pongo=components / 'quiet/pongo.bin', init=payload / 'init', files=files,
        hostname='j71b-audio-check', platform='apple-16k', boards={'j71b': 't8010-j71b'},
        modules=True)
    receipt = json.loads((output / 'build.json').read_text())
    receipt['firmware'] = True
    (output / 'build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    ram.verify_ram(output)
    print('Prepared J71b boot/touch/ALSA enumeration image. No device was accessed.')
    print('This is not a microphone or loudness fix. No playback starts automatically.')


if __name__ == '__main__':
    main()

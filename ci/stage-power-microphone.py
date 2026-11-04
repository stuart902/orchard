#!/usr/bin/env python3
"""Reuse verified final-power boot inputs and stage the combined kernel bundle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reuse():
    root = ROOT / 'out/reused/components'
    record = json.loads((root / 'components.json').read_text())
    if record['schema'] != 1:
        raise ValueError('Unknown component schema')
    for name, expected in record['files'].items():
        path = root / name
        if Path(name).is_absolute() or '..' in Path(name).parts or path.is_symlink():
            raise ValueError('Invalid component path: ' + name)
        if path.stat().st_size != expected['bytes'] or digest(path) != expected['sha256']:
            raise ValueError('Invalid component digest: ' + name)
    evidence = json.loads((root / 'integration-receipt.json').read_text())
    if evidence['orchard'] != '1b9457c9cc17327ccd08a19a0181c28c6d6028ed':
        raise ValueError('Unexpected reused Orchard source')
    if evidence['power_source_linux'] != '778174c50d5fd6b36849f9eea728a6811b1b6e9e':
        raise ValueError('Unexpected reused power source')
    from orchard.build import M1N1_INPUTS, TOOL_INPUTS, PONGO_RECIPE
    subprocess.run(['git', 'diff', '--exit-code',
                    'a68aae672613176d203d4a3823f03f929bc84f5c', 'HEAD', '--',
                    *sorted(set(M1N1_INPUTS + TOOL_INPUTS + PONGO_RECIPE))], cwd=ROOT, check=True)
    target = ROOT / 'out/components'
    target.mkdir(parents=True)
    for name in ('boot', 'quiet'):
        shutil.copytree(root / name, target / name)
    for path in root.glob('*toolchain*.lock'):
        if not path.name.startswith('kernel-'):
            shutil.copy2(path, target / path.name)
    reused = {'schema': 1, 'run': 41734585711, 'artifact': 13278797723,
              'workflow_commit': '81b364712f9bbc9ea44aeac6825f0be1e63b071b',
              'artifact_sha256': 'dd7b4e46910d9876eae7e1eed6886e93f54d7eef8a68ab9d5dbe2eab8b77377f',
              'recipe_inputs_equal': True, 'original_integration': evidence,
              'files': {str(p.relative_to(target)): digest(p) for p in sorted(target.rglob('*')) if p.is_file()}}
    (target / 'reuse-receipt.json').write_text(json.dumps(reused, indent=2) + '\n')


def stage():
    from orchard.ram import verify_ram
    receipt = verify_ram(ROOT / 'examples/hardware-check/out/apple-16k')
    kernel = Path(receipt['assembly']['kernel']).parent
    target = ROOT / 'out/components'
    shutil.copytree(kernel, target / 'kernel')
    config = ROOT / 'linux/.orchard-out/apple-16k/output/.config'
    shutil.copy2(config, target / 'resolved.config')
    subprocess.run([sys.executable, str(ROOT / 'ci/audit-power-microphone.py'), str(ROOT / 'linux'),
                    '--config', str(config), '--output', str(target / 'integration-receipt.json')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'ci/audit-capture-platform.py'), str(target / 'kernel')], check=True)
    release = (target / 'kernel/kernel.release').read_text().strip()
    expected = '7.3.0-rc1-j71b-power-mic-nov4-r1-orchard-apple-16k'
    if release != expected:
        raise ValueError('Unexpected candidate release: ' + release)
    modules = target / 'kernel/lib/modules' / release
    if 'kernel/drivers/power/reset/apple-d2365-poweroff.ko' not in (modules / 'modules.builtin').read_text().splitlines():
        raise ValueError('Power driver is not built in')
    dtb = target / 'kernel/dtbs/t8010-j71b.dtb'
    def fdt(node, prop, kind=None):
        return subprocess.check_output(['fdtget', *(['-t', kind] if kind else []),
                                        str(dtb), node, prop], text=True).strip()
    pmic = fdt('/__symbols__', 'd2365_pmic')
    charger = fdt('/__symbols__', 'tristar_charger')
    if fdt(pmic + '/poweroff', 'compatible') != 'apple,d2365-poweroff':
        raise ValueError('Power-off child missing from built DTB')
    if fdt(pmic + '/poweroff', 'power-supplies', 'x') != fdt(charger, 'phandle', 'x'):
        raise ValueError('Built DTB has wrong power supply')
    module_records = {}
    for path in sorted(modules.rglob('*.ko')):
        module_records[str(path.relative_to(modules))] = digest(path)
    for name in ('t8010-pdm.ko', 'aop-audio.ko', 'apple-sio.ko', 'apple-sio-dma.ko'):
        matches = list(modules.rglob(name))
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous module: ' + name)
        vermagic = subprocess.check_output(['modinfo', '-F', 'vermagic', str(matches[0])], text=True)
        if vermagic.split()[0] != release:
            raise ValueError('Wrong module vermagic: ' + name)
    record = json.loads((target / 'integration-receipt.json').read_text())
    record.update(orchard=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  platform='apple-16k', kernel_release=release,
                  build_run=int(os.environ.get('GITHUB_RUN_ID', 0)), hardware_tested=False,
                  modules=module_records, dtb_sha256=digest(dtb), image_sha256=digest(target / 'kernel/Image.gz'),
                  power_dtb_supply_verified=True, playback_disabled=True)
    (target / 'integration-receipt.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['reuse', 'stage'])
    args = parser.parse_args()
    {'reuse': reuse, 'stage': stage}[args.stage]()

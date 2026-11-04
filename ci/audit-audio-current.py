#!/usr/bin/env python3
"""Audit current Orchard audio source/configuration without accessing hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def config_values(text):
    values = {}
    for line in text.splitlines():
        enabled = re.fullmatch(r'(CONFIG_\w+)=(.*)', line)
        disabled = re.fullmatch(r'# (CONFIG_\w+) is not set', line)
        if enabled or disabled:
            name, value = (enabled[1], enabled[2]) if enabled else (disabled[1], 'n')
            if name in values:
                raise ValueError('Duplicate config symbol: ' + name)
            values[name] = value
    return values


def check_config(resolved, baseline, localversion, pages):
    expected = config_values(baseline)
    expected.update(CONFIG_APPLE_AOP_T8010='m', CONFIG_APPLE_AOP_AUDIO='m',
                    CONFIG_SND_SOC_APPLE_T8010_PDM='m', CONFIG_SND_SOC_DMIC='m',
                    CONFIG_LOCALVERSION=json.dumps(localversion))
    actual = config_values(resolved)
    # Kconfig omits symbols whose dependencies are disabled. Omitted and n
    # are equivalent; no new enabled option or changed baseline choice is.
    differences = {name: [expected.get(name, 'n'), actual.get(name, 'n')]
                   for name in expected.keys() | actual.keys()
                   if expected.get(name, 'n') != actual.get(name, 'n')}
    if differences:
        raise ValueError('Unexpected configuration delta: ' + json.dumps(differences, sort_keys=True))
    for name in ('CONFIG_EXPERT', 'CONFIG_MTD', 'CONFIG_MTD_PHRAM',
                 'CONFIG_ARM64_' + pages.upper() + '_PAGES'):
        if actual.get(name) != 'y':
            raise ValueError('Required built-in option missing: ' + name)
    for name in ('CONFIG_APPLE_SIO', 'CONFIG_APPLE_SIO_DMA',
                 'CONFIG_SND_SOC_APPLE_S8000_MCA', 'CONFIG_SND_SOC_MAX98357A'):
        if actual.get(name) != 'm':
            raise ValueError('Required unchanged audio dependency missing: ' + name)


def check_source(kernel, record, variant, expected_commit):
    def git(*args, env=None):
        return subprocess.check_output(['git', '-C', str(kernel), *args], env=env).strip()

    current = record['variants'][variant]
    if git('rev-parse', 'HEAD').decode() != expected_commit:
        raise ValueError('Unexpected kernel commit')
    if git('rev-parse', 'HEAD^{tree}').decode() != current['kernel_tree']:
        raise ValueError('Unexpected kernel tree')
    subprocess.run(['git', '-C', str(kernel), 'diff', '--exit-code', 'HEAD'], check=True)
    if git('ls-files', '--others', '--exclude-standard'):
        raise ValueError('Untracked kernel source files are not permitted')
    files = dict(record['microphone_files'])
    files['sound/soc/apple/s8000-mca.c'] = current['mca_sha256']
    files['arch/arm64/boot/dts/apple/t8010-j71b.dts'] = current['dts_sha256']
    for name, expected in files.items():
        data = subprocess.check_output(['git', '-C', str(kernel), 'show', 'HEAD:' + name])
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Pinned source changed: ' + name)
    with tempfile.TemporaryDirectory() as temporary:
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(temporary) / 'index')}
        git('read-tree', 'HEAD', env=env)
        for row in record['production_restore']:
            if row['production_blob'] is None:
                git('update-index', '--force-remove', row['path'], env=env)
            else:
                git('update-index', '--add', '--cacheinfo', row['production_mode'],
                    row['production_blob'], row['path'], env=env)
        # Restore only the declared audio/config paths. The complete tree hash
        # proves every other path still matches the current Orchard patch series.
        if git('write-tree', '--missing-ok', env=env).decode() != record['production_kernel_tree']:
            raise ValueError('Unexpected change outside the declared audio/config paths')
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('--record', type=Path,
                        default=Path(__file__).with_name('j71b-audio-current.json'))
    parser.add_argument('--variant', choices=('audio', 'microphone'), required=True)
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--baseline-config', type=Path)
    parser.add_argument('--pages', choices=('4k', '16k'), default='16k')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if bool(args.config) != bool(args.baseline_config):
        parser.error('--config and --baseline-config must be supplied together')
    record = json.loads(args.record.read_text())
    current = check_source(args.kernel, record, args.variant, args.expected_commit)
    result = {'kernel_commit': args.expected_commit, 'variant': args.variant,
              'kernel_tree': current['kernel_tree'], 'source_verified': True,
              'orchard_commit': record['orchard_commit'],
              'production_kernel_tree': record['production_kernel_tree']}
    if args.config:
        baseline = args.baseline_config.read_bytes()
        if hashlib.sha256(baseline).hexdigest() != record['baseline_configs'][args.pages]:
            raise ValueError('Baseline configuration is not the pinned current Orchard config')
        check_config(args.config.read_text(), baseline.decode(), current['localversion'], args.pages)
        result.update(pages=args.pages, config_verified=True,
                      resolved_config_sha256=hashlib.sha256(args.config.read_bytes()).hexdigest())
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('Pinned source, current Orchard base and declared configuration verified')


if __name__ == '__main__':
    main()

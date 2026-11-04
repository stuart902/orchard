#!/usr/bin/env python3
"""Verify the exact combined source and resolved configuration, without a device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def config_values(text):
    values = {}
    for line in text.splitlines():
        match = re.fullmatch(r'(CONFIG_\w+)=(.*)', line)
        disabled = re.fullmatch(r'# (CONFIG_\w+) is not set', line)
        if match or disabled:
            name, value = (match[1], match[2]) if match else (disabled[1], 'n')
            if name in values:
                raise ValueError('Duplicate config symbol: ' + name)
            values[name] = value
    return values


def check_config(resolved, baseline, localversion):
    expected = config_values(baseline)
    expected.update(CONFIG_APPLE_AOP_AUDIO='m', CONFIG_SND_SOC_APPLE_T8010_PDM='m',
                    CONFIG_SND_SOC_DMIC='m', CONFIG_LOCALVERSION=json.dumps(localversion))
    actual = config_values(resolved)
    difference = {name: [expected.get(name), actual.get(name)]
                  for name in expected.keys() | actual.keys()
                  if expected.get(name) != actual.get(name)}
    if difference:
        raise ValueError('Unexpected configuration delta: ' + json.dumps(difference, sort_keys=True))
    for name in ('CONFIG_ARM64_16K_PAGES', 'CONFIG_POWER_RESET_APPLE_D2365',
                 'CONFIG_GPIO_APPLE_D2365', 'CONFIG_APPLE_TRISTAR_CHARGER',
                 'CONFIG_MTD', 'CONFIG_MTD_PHRAM', 'CONFIG_UDMABUF'):
        if actual.get(name) != 'y':
            raise ValueError('Required built-in option missing: ' + name)
    if actual.get('CONFIG_NVME_APPLE') != 'm' or actual.get('CONFIG_RTC_SYSTOHC') != 'n':
        raise ValueError('Final production configuration regressed')


def check_source(kernel, record):
    def git(*args, env=None):
        return subprocess.check_output(['git', '-C', str(kernel), *args], env=env).strip()
    if git('rev-parse', 'HEAD').decode() != record['kernel_commit']:
        raise ValueError('Unexpected kernel commit')
    if git('rev-parse', 'HEAD^{tree}').decode() != record['kernel_tree']:
        raise ValueError('Unexpected kernel tree')
    subprocess.run(['git', '-C', str(kernel), 'diff', '--exit-code', 'HEAD'], check=True)
    if git('ls-files', '--others', '--exclude-standard'):
        raise ValueError('Untracked kernel source files are not permitted')
    for group in ('power_files', 'microphone_files'):
        for name, expected in record[group].items():
            data = subprocess.check_output(['git', '-C', str(kernel), 'show', 'HEAD:' + name])
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Validated source changed: ' + name)
    with tempfile.TemporaryDirectory() as temporary:
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(temporary) / 'index')}
        git('read-tree', 'HEAD', env=env)
        for row in record['production_restore']:
            if row['production_blob'] is None:
                git('update-index', '--force-remove', row['path'], env=env)
            else:
                git('update-index', '--add', '--cacheinfo',
                    row['production_mode'], row['production_blob'], row['path'], env=env)
        # Preimage blobs need not be materialized: the complete tree hash proves
        # that every path outside the explicitly declared audio/test/config delta
        # is identical to the source used by the final power distribution.
        if git('write-tree', '--missing-ok', env=env).decode() != record['production_kernel_tree']:
            raise ValueError('Unexpected change to final power production source')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    record = json.loads((ROOT / 'ci/j71b-power-microphone.json').read_text())
    check_source(args.kernel, record)
    if args.config:
        check_config(args.config.read_text(),
                     (ROOT / 'kernel/configs/apple-16k/config').read_text(), record['localversion'])
        record['resolved_config_sha256'] = hashlib.sha256(args.config.read_bytes()).hexdigest()
        record['config_exact'] = True
    if args.output:
        args.output.write_text(json.dumps(record, indent=2) + '\n')
    print('Exact production base, unchanged power/microphone source and declared configuration verified')


if __name__ == '__main__':
    main()

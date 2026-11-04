#!/usr/bin/env python3
"""Host-only positive/negative tests of source and configuration audit gates."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('audit-audio-current.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.baseline = '\n'.join([
            'CONFIG_EXPERT=y', 'CONFIG_MTD=y', 'CONFIG_MTD_PHRAM=y',
            'CONFIG_ARM64_16K_PAGES=y', 'CONFIG_APPLE_SIO=m',
            'CONFIG_APPLE_SIO_DMA=m', 'CONFIG_SND_SOC_APPLE_S8000_MCA=m',
            'CONFIG_SND_SOC_MAX98357A=m', 'CONFIG_APPLE_AOP_T8010=m',
            '# CONFIG_RTC_SYSTOHC is not set', 'CONFIG_NVME_APPLE=m',
            'CONFIG_UDMABUF=y', 'CONFIG_LOCALVERSION=""', 'CONFIG_CPU_IDLE=y',
        ]) + '\n'
        self.config = self.baseline.replace('CONFIG_LOCALVERSION=""', 'CONFIG_LOCALVERSION="-test"')
        self.config += 'CONFIG_APPLE_AOP_AUDIO=m\nCONFIG_SND_SOC_APPLE_T8010_PDM=m\nCONFIG_SND_SOC_DMIC=m\n'

    def check(self, value):
        audit.check_config(value, self.baseline, '-test', '16k')

    def test_exact_configuration_passes(self):
        self.check(self.config)

    def test_new_disabled_symbols_are_semantically_unchanged(self):
        self.check(self.config + '# CONFIG_APPLE_AOP_ACCEL is not set\n')

    def test_omitted_disabled_symbol_is_equivalent(self):
        self.check(self.config.replace('# CONFIG_RTC_SYSTOHC is not set\n', ''))

    def test_each_required_module_must_survive_resolution(self):
        for symbol in ['APPLE_AOP_T8010', 'APPLE_AOP_AUDIO', 'SND_SOC_APPLE_T8010_PDM',
                       'SND_SOC_DMIC', 'APPLE_SIO', 'APPLE_SIO_DMA',
                       'SND_SOC_APPLE_S8000_MCA', 'SND_SOC_MAX98357A']:
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                self.check(self.config.replace('CONFIG_' + symbol + '=m\n', ''))

    def test_new_enabled_option_fails(self):
        with self.assertRaises(ValueError):
            self.check(self.config + 'CONFIG_UNKNOWN=y\n')

    def test_duplicate_enabled_option_fails(self):
        with self.assertRaises(ValueError):
            self.check(self.config + 'CONFIG_MTD=y\n')

    def test_conflicting_enabled_disabled_option_fails(self):
        with self.assertRaises(ValueError):
            self.check(self.config + '# CONFIG_MTD is not set\n')

    def test_upstream_choices_cannot_regress(self):
        for old, new in [('CONFIG_NVME_APPLE=m', 'CONFIG_NVME_APPLE=y'),
                         ('CONFIG_UDMABUF=y', '# CONFIG_UDMABUF is not set'),
                         ('# CONFIG_RTC_SYSTOHC is not set', 'CONFIG_RTC_SYSTOHC=y'),
                         ('CONFIG_CPU_IDLE=y', '# CONFIG_CPU_IDLE is not set')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                self.check(self.config.replace(old, new))

    def test_wrong_variant_release_fails(self):
        with self.assertRaises(ValueError):
            self.check(self.config.replace('"-test"', '""'))

    def test_wrong_page_size_fails(self):
        with self.assertRaises(ValueError):
            self.check(self.config.replace('CONFIG_ARM64_16K_PAGES=y', 'CONFIG_ARM64_4K_PAGES=y'))

    def test_four_k_provider_is_explicitly_enabled(self):
        baseline = self.baseline.replace('16K', '4K').replace('CONFIG_APPLE_AOP_T8010=m', '# CONFIG_APPLE_AOP_T8010 is not set')
        audit.check_config(self.config.replace('16K', '4K'), baseline, '-test', '4k')


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Audit test')
        self.git('config', 'user.email', 'audit@example.invalid')
        self.paths = ['sound/soc/apple/s8000-mca.c',
                      'arch/arm64/boot/dts/apple/t8010-j71b.dts', 'unrelated.c']
        for path in self.paths:
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('baseline\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')
        production = self.git('rev-parse', 'HEAD^{tree}')
        blob = self.git('rev-parse', 'HEAD:unrelated.c')
        for path in self.paths[:2]:
            (self.root / path).write_text('audio\n')
        (self.root / 'microphone.c').write_text('microphone\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'audio')
        self.commit = self.git('rev-parse', 'HEAD')
        self.record = {'production_kernel_tree': production,
                       'production_restore': [{'path': p, 'production_blob': blob, 'production_mode': '100644'} for p in self.paths[:2]]
                       + [{'path': 'microphone.c', 'production_blob': None, 'production_mode': None}],
                       'microphone_files': {'microphone.c': hashlib.sha256(b'microphone\n').hexdigest()},
                       'variants': {'microphone': {'kernel_tree': self.git('rev-parse', 'HEAD^{tree}'),
                                                  'mca_sha256': hashlib.sha256(b'audio\n').hexdigest(),
                                                  'dts_sha256': hashlib.sha256(b'audio\n').hexdigest()}}}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.DEVNULL, text=True).strip()

    def check(self, record=None, commit=None):
        audit.check_source(self.root, record or self.record, 'microphone', commit or self.commit)

    def test_exact_source_and_production_restore_pass(self):
        self.check()

    def test_wrong_commit_fails(self):
        with self.assertRaises(ValueError):
            self.check(commit='0' * 40)

    def test_wrong_tree_fails(self):
        record = copy.deepcopy(self.record)
        record['variants']['microphone']['kernel_tree'] = '0' * 40
        with self.assertRaises(ValueError):
            self.check(record)

    def test_dirty_tracked_source_fails(self):
        (self.root / 'unrelated.c').write_text('changed\n')
        with self.assertRaises(subprocess.CalledProcessError):
            self.check()

    def test_untracked_source_fails(self):
        (self.root / 'extra.c').write_text('changed\n')
        with self.assertRaises(ValueError):
            self.check()

    def test_mic_source_digest_mismatch_fails(self):
        record = copy.deepcopy(self.record)
        record['microphone_files']['microphone.c'] = '0' * 64
        with self.assertRaises(ValueError):
            self.check(record)

    def test_tdm_digest_mismatch_fails(self):
        record = copy.deepcopy(self.record)
        record['variants']['microphone']['mca_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.check(record)

    def test_undeclared_source_change_fails_restore(self):
        (self.root / 'unrelated.c').write_text('changed\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'unrelated modification')
        record = copy.deepcopy(self.record)
        record['variants']['microphone']['kernel_tree'] = self.git('rev-parse', 'HEAD^{tree}')
        with self.assertRaises(ValueError):
            self.check(record, self.git('rev-parse', 'HEAD'))


if __name__ == '__main__':
    unittest.main()

"""Negative source/config audit tests; synthetic fixtures never access a device."""
import copy
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
AUDIT = runpy.run_path(str(ROOT / 'ci/audit-power-microphone.py'))


class CombinedConfig(unittest.TestCase):
    def setUp(self):
        self.baseline = (ROOT / 'kernel/configs/apple-16k/config').read_text()
        self.localversion = '-j71b-power-mic-nov4-r1'
        self.expected = AUDIT['config_values'](self.baseline)
        self.expected.update(CONFIG_APPLE_AOP_AUDIO='m', CONFIG_SND_SOC_APPLE_T8010_PDM='m',
                             CONFIG_SND_SOC_DMIC='m', CONFIG_LOCALVERSION=json.dumps(self.localversion))

    def check(self, edits=None):
        values = {**self.expected, **(edits or {})}
        text = ''.join(f'{key}={value}\n' for key, value in values.items())
        AUDIT['check_config'](text, self.baseline, self.localversion)

    def test_only_declared_audio_and_release_changes(self):
        self.check()

    def test_final_power_configuration_cannot_regress(self):
        for name, value in [('CONFIG_RTC_SYSTOHC', 'y'), ('CONFIG_NVME_APPLE', 'n'),
                            ('CONFIG_UDMABUF', 'n'), ('CONFIG_POWER_RESET_APPLE_D2365', 'm')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check({name: value})

    def test_capture_modules_and_identity_are_required(self):
        for name in ['CONFIG_APPLE_AOP_AUDIO', 'CONFIG_SND_SOC_APPLE_T8010_PDM', 'CONFIG_SND_SOC_DMIC']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check({name: 'n'})
        with self.assertRaises(ValueError):
            self.check({'CONFIG_LOCALVERSION': '""'})

    def test_unrelated_option_addition_is_refused(self):
        with self.assertRaises(ValueError):
            self.check({'CONFIG_UNDECLARED_FEATURE': 'y'})

    def test_duplicate_config_is_refused(self):
        with self.assertRaises(ValueError):
            AUDIT['config_values']('CONFIG_SND=y\nCONFIG_SND=m\n')


class CombinedSource(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Source Audit Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.root / 'power.c').write_text('unchanged production power\n')
        (self.root / 'platform.c').write_text('unchanged production platform\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'production')
        baseline = self.git('rev-parse', 'HEAD^{tree}')
        (self.root / 'microphone.c').write_text('unchanged tested microphone\n\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'microphone')
        self.record = {'kernel_commit': self.git('rev-parse', 'HEAD'),
                       'kernel_tree': self.git('rev-parse', 'HEAD^{tree}'),
                       'production_kernel_tree': baseline,
                       'power_files': {'power.c': hashlib.sha256((self.root / 'power.c').read_bytes()).hexdigest()},
                       'microphone_files': {'microphone.c': hashlib.sha256((self.root / 'microphone.c').read_bytes()).hexdigest()},
                       'production_restore': [{'path': 'microphone.c', 'production_blob': None}]}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], stderr=subprocess.PIPE, text=True).strip()

    def test_exact_source_and_complete_base(self):
        AUDIT['check_source'](self.root, self.record)

    def test_wrong_commit_is_rejected(self):
        record = copy.deepcopy(self.record)
        record['kernel_commit'] = '0' * 40
        with self.assertRaises(ValueError):
            AUDIT['check_source'](self.root, record)

    def test_changed_validated_source_is_rejected(self):
        record = copy.deepcopy(self.record)
        record['microphone_files']['microphone.c'] = '0' * 64
        with self.assertRaises(ValueError):
            AUDIT['check_source'](self.root, record)

    def test_undeclared_production_change_cannot_be_hidden_by_updated_commit(self):
        (self.root / 'platform.c').write_text('regressed production platform\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'regression')
        record = copy.deepcopy(self.record)
        record.update(kernel_commit=self.git('rev-parse', 'HEAD'), kernel_tree=self.git('rev-parse', 'HEAD^{tree}'))
        with self.assertRaises(ValueError):
            AUDIT['check_source'](self.root, record)

    def test_uncommitted_tracked_change_is_refused(self):
        (self.root / 'power.c').write_text('dirty\n')
        with self.assertRaises(subprocess.CalledProcessError):
            AUDIT['check_source'](self.root, self.record)

    def test_untracked_source_is_refused(self):
        (self.root / 'unexpected.c').write_text('unreviewed source\n')
        with self.assertRaises(ValueError):
            AUDIT['check_source'](self.root, self.record)

    def test_shallow_checkout_does_not_need_original_blob_contents(self):
        original = self.git('rev-parse', 'HEAD:platform.c')
        (self.root / 'platform.c').write_text('declared integration change\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'declared change')
        record = copy.deepcopy(self.record)
        record.update(kernel_commit=self.git('rev-parse', 'HEAD'), kernel_tree=self.git('rev-parse', 'HEAD^{tree}'))
        record['production_restore'].append({'path': 'platform.c', 'production_mode': '100644', 'production_blob': original})
        with tempfile.TemporaryDirectory() as temporary:
            shallow = Path(temporary) / 'kernel'
            subprocess.run(['git', 'clone', '-q', '--depth=1', self.root.as_uri(), str(shallow)], check=True)
            self.assertNotEqual(subprocess.run(['git', '-C', str(shallow), 'cat-file', '-e', original],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode, 0)
            AUDIT['check_source'](shallow, record)

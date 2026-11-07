#!/usr/bin/env python3
"""Positive/negative fixture tests of build artifact acceptance, no device access."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('stage', Path(__file__).with_name('stage-audio-current.py'))
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
RELEASE = '7.3.0-rc1-j71b-speaker-window-nov7-r1-orchard-apple-16k'
ALIASES = [('apple,j71b-pdm', 't8010_pdm'), ('apple,t8010-aop-audio', 'aop_audio'),
           ('apple,t8010-aop', 'apple_aop'), ('apple,t8010-sio', 'apple_sio'),
           ('apple,t8010-mca', 'snd_soc_apple_s8000_mca'), ('maxim,max98357a', 'snd_soc_max98357a'),
           ('dmic-codec', 'snd_soc_dmic'), ('simple-audio-card', 'snd_soc_simple_card')]


class ArchiveTests(unittest.TestCase):
    def tar(self, names):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            for name, kind in names:
                member = tarfile.TarInfo(name)
                member.type = kind
                archive.addfile(member)
        data.seek(0)
        return tarfile.open(fileobj=data)

    def test_regular_members_pass(self):
        with self.tar([('components', tarfile.DIRTYPE), ('components/file', tarfile.REGTYPE)]) as archive:
            self.assertEqual(len(stage.safe_members(archive)), 2)

    def test_unsafe_members_fail(self):
        for name, kind in [('../escape', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('link', tarfile.SYMTYPE), ('hard', tarfile.LNKTYPE), ('dev', tarfile.CHRTYPE)]:
            with self.subTest(name=name), self.tar([(name, kind)]) as archive, self.assertRaises(ValueError):
                stage.safe_members(archive)

    def test_duplicate_fails(self):
        with self.tar([('same', tarfile.REGTYPE), ('same', tarfile.REGTYPE)]) as archive, self.assertRaises(ValueError):
            stage.safe_members(archive)

    def test_recipe_matches_and_detects_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'recipe').mkdir()
            (root / 'recipe/input').write_text('exact')
            archive = root / 'source.tar'
            with tarfile.open(archive, 'w') as tar:
                tar.add(root / 'recipe', arcname='recipe')
            with patch.object(stage, 'ROOT', root):
                self.assertEqual(stage.source_recipe_matches(archive, ['recipe']), ['recipe/input'])
                (root / 'recipe/input').write_text('changed')
                with self.assertRaises(ValueError):
                    stage.source_recipe_matches(archive, ['recipe'])
                (root / 'recipe/input').write_text('exact')
                (root / 'recipe/extra').write_text('unexpected')
                with self.assertRaises(ValueError):
                    stage.source_recipe_matches(archive, ['recipe'])


class ModuleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.kernel = Path(self.directory.name)
        (self.kernel / 'kernel.release').write_text(RELEASE + '\n')
        self.modules = self.kernel / 'lib/modules' / RELEASE
        self.modules.mkdir(parents=True)
        elf = b'\x7fELF\x02\x01' + b'\0' * 12 + b'\xb7\x00'
        for name in stage.MODULES:
            (self.modules / name).write_bytes(elf)
        (self.modules / 'modules.dep').write_text(''.join(name + ':\n' for name in stage.MODULES))
        aliases = ''.join('alias of:N*T*C' + compatible + ' ' + module + '\n' for compatible, module in ALIASES)
        (self.modules / 'modules.alias').write_text(aliases + 'alias platform:apple-sio-dma apple_sio_dma\n')
        for name in ('modules.alias.bin', 'modules.dep.bin'):
            (self.modules / name).write_bytes(b'index')
        def output(argv, **kw):
            if argv[0] == 'llvm-nm-19': return 'j71b_test_arm b 0 1\n'
            if argv[1] == '-p': return 'j71b_test_arm:Permit one 30 ms J71b amplifier test window (default: false) (bool)\n'
            return RELEASE + ' SMP preempt mod_unload aarch64\n'
        mock = patch.object(stage.subprocess, 'check_output', side_effect=output)
        mock.start()
        self.addCleanup(mock.stop)

    def test_exact_passes(self):
        release, hashes = stage.audit_modules(self.kernel)
        self.assertEqual(release, RELEASE)
        self.assertEqual(len(hashes), len(stage.MODULES))

    def test_missing_module(self):
        (self.modules / 't8010-pdm.ko').unlink()
        with self.assertRaises(ValueError): stage.audit_modules(self.kernel)

    def test_missing_dependency(self):
        with (self.modules / 'modules.dep').open('a') as stream:
            stream.write('unrelated.ko: missing.ko\n')
        (self.modules / 'modules.dep').write_text((self.modules / 'modules.dep').read_text().replace('t8010-pdm.ko:', 't8010-pdm.ko: missing.ko'))
        with self.assertRaises(ValueError): stage.audit_modules(self.kernel)

    def test_missing_alias(self):
        (self.modules / 'modules.alias').write_text('')
        with self.assertRaises(ValueError): stage.audit_modules(self.kernel)

    def test_empty_index(self):
        (self.modules / 'modules.dep.bin').write_bytes(b'')
        with self.assertRaises(ValueError): stage.audit_modules(self.kernel)

    def test_wrong_release(self):
        (self.kernel / 'kernel.release').write_text('wrong')
        with self.assertRaises(ValueError): stage.audit_modules(self.kernel)

    def test_extra_release(self):
        (self.modules.parent / 'stale').mkdir()
        with self.assertRaises(ValueError): stage.audit_modules(self.kernel)

    def test_wrong_vermagic(self):
        with patch.object(stage.subprocess, 'check_output', return_value='wrong SMP'):
            with self.assertRaises(ValueError): stage.audit_modules(self.kernel)

    def test_wrong_architecture(self):
        (self.modules / 't8010-pdm.ko').write_bytes(b'not an ELF')
        with self.assertRaises(ValueError): stage.audit_modules(self.kernel)

    def test_dependency_path_escape(self):
        (self.modules / 'modules.dep').write_text((self.modules / 'modules.dep').read_text().replace('t8010-pdm.ko:', 't8010-pdm.ko: ../escape.ko'))
        with self.assertRaises(ValueError): stage.audit_modules(self.kernel)


class DtbTests(unittest.TestCase):
    def setUp(self):
        self.values = {(node, 'status'): value for node, value in [('/dmic', 'okay'), ('/microphones', 'okay'),
                       ('/soc/pdm@20a0b4000', 'okay'), ('/soc/aop@210800000/aop-audio', 'okay'),
                       ('/sound', 'okay'), ('/soc/mca@20a0a8000', 'okay')]}
        self.values.update({('/', 'compatible'): 'apple,j71b apple,t8010', ('/sound', 'simple-audio-card,format'): 'dsp_a',
                            ('/__symbols__', 'speaker_amps'): '/amplifier', ('/amplifier', 'maxim,tdm'): '',
                            ('/amplifier', 'compatible'): 'maxim,max98357a',
                            ('/__symbols__', 'pinctrl_ap'): '/soc/pinctrl',
                            ('/soc/pinctrl', 'phandle'): 'b', ('/amplifier', 'sdmode-gpios'): 'b 14 0',
                            ('/dmic', 'num-channels'): '2', ('/soc/pdm@20a0b4000', 'dmas'): 'a 5b'})
        mock = patch.object(stage.subprocess, 'check_output', side_effect=lambda argv, **kw: self.values[tuple(argv[-2:])])
        mock.start()
        self.addCleanup(mock.stop)

    def test_exact_passes(self): stage.audit_dtb(Path('fake.dtb'))

    def test_any_wrong_state_or_tdm_fails(self):
        for key, value in list(self.values.items()):
            if key[0] == '/__symbols__':
                continue
            with self.subTest(key=key):
                self.values[key] = 'wrong'
                with self.assertRaises(ValueError): stage.audit_dtb(Path('fake.dtb'))
                self.values[key] = value


class GateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.codec = Path(self.directory.name) / 'codec.ko'
        self.codec.write_bytes(b'fixture')
        self.parameter = 'j71b_test_arm:Permit one 30 ms J71b amplifier test window (default: false) (bool)\n'
        self.symbols = 'j71b_test_arm b 0 1\n'
        mock = patch.object(stage.subprocess, 'check_output', side_effect=lambda argv, **kw:
                            self.symbols if argv[0] == 'llvm-nm-19' else self.parameter)
        mock.start()
        self.addCleanup(mock.stop)

    def test_exact_gate_passes(self):
        self.assertFalse(stage.audit_gate(self.codec)['arming_default'])

    def test_missing_parameter_fails(self):
        self.parameter = ''
        with self.assertRaises(ValueError): stage.audit_gate(self.codec)

    def test_nonzero_initializer_storage_fails(self):
        self.symbols = 'j71b_test_arm d 0 1\n'
        with self.assertRaises(ValueError): stage.audit_gate(self.codec)

    def test_missing_or_ambiguous_or_wrong_size_symbol_fails(self):
        for symbols in ('', 'j71b_test_arm b 0 2\n', self.symbols * 2):
            with self.subTest(symbols=symbols):
                self.symbols = symbols
                with self.assertRaises(ValueError): stage.audit_gate(self.codec)

    def test_wrong_default_description_fails(self):
        self.parameter = self.parameter.replace('false', 'true')
        with self.assertRaises(ValueError): stage.audit_gate(self.codec)


if __name__ == '__main__':
    unittest.main()

"""bin/orchard runs its own checkout; fake uv, no environment setup."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

LAUNCHER = Path(__file__).resolve().parents[1] / 'bin/orchard'


class LauncherTests(unittest.TestCase):
    """bin/orchard runs the checkout it belongs to, from wherever it is called."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.bin = self.root / 'fake-bin'
        self.bin.mkdir()
        self.log = self.root / 'uv.log'
        (self.bin / 'uv').write_text('#!/bin/sh\nprintf "%s\\n" "$UV_PROJECT_ENVIRONMENT" "$@" > "$LAUNCH_LOG"\n')
        (self.bin / 'uv').chmod(0o755)
        self.checkout = self.root / 'orchard'
        (self.checkout / 'bin').mkdir(parents=True)
        shutil.copy2(LAUNCHER, self.checkout / 'bin/orchard')

    def launch(self, launcher, cwd, *arguments):
        return subprocess.run(['sh', str(launcher), *arguments], cwd=cwd, capture_output=True, text=True,
                              env={'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.root),
                                   'LAUNCH_LOG': str(self.log), 'UV_PROJECT_ENVIRONMENT': '/elsewhere'})

    def test_runs_its_own_checkout_from_anywhere_and_through_a_link(self):
        elsewhere = self.root / 'omarchy-a'
        elsewhere.mkdir()
        (elsewhere / 'orchard.local.toml').write_text('orchard = "../somewhere"\n')  # not read
        link = self.root / 'link-to-orchard'
        link.symlink_to(self.checkout / 'bin/orchard')
        for launcher in (self.checkout / 'bin/orchard', link):
            with self.subTest(launcher=launcher.name):
                result = self.launch(launcher, elsewhere, 'build', 'with spaces')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.log.read_text().splitlines(),
                                 [str(self.checkout / '.venv'), 'run', '--quiet', '--project', str(self.checkout),
                                  'orchard', 'build', 'with spaces'])

    def test_python_runs_in_the_checkout_environment(self):
        result = self.launch(self.checkout / 'bin/orchard', self.root, 'python', '-m', 'unittest')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines()[-3:], ['python', '-m', 'unittest'])

    def test_mainline_from_an_older_setup_hands_over_to_the_launcher(self):
        main = self.root / 'cache/orchard-main'
        (main / 'bin').mkdir(parents=True)
        (main / 'tools').mkdir()
        shutil.copy2(LAUNCHER, main / 'bin/orchard')
        (main / 'tools/launcher').write_text('echo "launcher $*"\n')
        result = subprocess.run(['sh', str(main / 'bin/orchard'), 'build'], cwd=self.root, capture_output=True,
                                text=True, env={'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.root),
                                                'ORCHARD_CACHE_DIR': str(self.root / 'cache')})
        self.assertEqual(result.stdout.strip(), 'launcher build')
        self.assertIn('run orchard update once', result.stderr)

    def test_exit_status_is_preserved(self):
        (self.bin / 'uv').write_text('#!/bin/sh\nexit 7\n')
        self.assertEqual(self.launch(self.checkout / 'bin/orchard', self.root, '--version').returncode, 7)


class ExampleTests(unittest.TestCase):
    """Examples teach the system; they must parse and name no board."""
    EXAMPLES = sorted((Path(__file__).resolve().parents[1] / 'examples').iterdir())

    def test_every_example_has_a_valid_init_and_payload(self):
        from orchard import build
        self.assertTrue(self.EXAMPLES)
        for example in self.EXAMPLES:
            with self.subTest(example=example.name):
                init = example / 'init'
                self.assertTrue(os.access(init, os.X_OK), 'init must be executable')
                subprocess.run(['sh', '-n', str(init)], check=True)
                build.payload_settings(example)
                self.assertNotIn('apple,j71b', init.read_text())
                self.assertFalse((example / 'payload.toml').exists())


if __name__ == '__main__':
    unittest.main()

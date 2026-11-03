"""The orchard on PATH (tools/launcher) runs the newest nightly per command; pinned or offline as asked."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ORCHARD = Path(__file__).resolve().parents[1] / 'tools/launcher'
NAME = 'nightly-20261103-0123456789ab'


@unittest.skipUnless(shutil.which('git') and shutil.which('curl'), 'needs git and curl')
class ToolingVersion(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        repo = self.root / 'repo'
        (repo / 'tools').mkdir(parents=True)
        (repo / 'pyproject.toml').write_text('[project]\nname = "orchard"\n')
        (repo / 'tools/launcher').write_text('the nightly launcher\n')
        git = ['git', '-C', str(repo), '-c', 'user.email=t@example.invalid', '-c', 'user.name=t']
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run([*git, 'add', '.'], check=True)
        subprocess.run([*git, 'commit', '-qm', 'x', '--no-gpg-sign'], check=True)
        subprocess.run([*git, 'tag', NAME], check=True)
        (self.root / 'releases/nightly').mkdir(parents=True)
        (self.root / 'releases/nightly/latest.json').write_text(f'{{"schema": 1, "name": "{NAME}"}}\n')
        (self.root / 'work').mkdir()
        # uv prints the project it was asked to run instead of running it.
        self.bin = self.root / 'fake-bin'
        self.bin.mkdir()
        (self.bin / 'uv').write_text('#!/bin/sh\nprintf "%s\\n" "$4"\n')
        (self.bin / 'uv').chmod(0o755)
        self.launcher = self.root / 'home/.local/bin/orchard'
        self.launcher.parent.mkdir(parents=True)
        shutil.copy2(ORCHARD, self.launcher)

    def run_orchard(self, *arguments, releases='releases', **env):
        return subprocess.run([str(self.launcher), *arguments], cwd=self.root / 'work', capture_output=True, text=True,
                              env={**os.environ, 'PATH': f'{self.bin}:{os.environ["PATH"]}',
                                   'ORCHARD_CACHE_DIR': str(self.root / 'cache'), 'HOME': str(self.root / 'home'),
                                   'ORCHARD_MAINLINE_URL': f'file://{self.root}/repo',
                                   'ORCHARD_RELEASES_URL': f'file://{self.root}/{releases}', **env})

    def test_the_newest_nightly_then_offline_the_cached_one(self):
        result = self.run_orchard('build')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.root / 'cache/tooling' / NAME))
        offline = self.run_orchard('build', releases='nowhere')
        self.assertEqual(offline.stdout.strip(), str(self.root / 'cache/tooling' / NAME))
        self.assertIn('no network', offline.stderr)

    def test_without_a_nightly_reachable_or_cached_it_says_so(self):
        result = self.run_orchard('build', releases='nowhere')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('no nightly reachable', result.stderr)
        self.assertFalse((self.root / 'cache/orchard-main').exists())

    def test_a_pinned_version_and_an_unknown_one(self):
        result = self.run_orchard('build', releases='nowhere', ORCHARD_VERSION=NAME)
        self.assertEqual(result.stdout.strip(), str(self.root / 'cache/tooling' / NAME))
        result = self.run_orchard('build', ORCHARD_VERSION='v9.9.9')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no orchard version v9.9.9', result.stderr)

    def test_an_orchard_line_in_the_local_file_is_refused_not_ignored(self):
        (self.root / 'work/orchard.local.toml').write_text('orchard = "../orchard"\n')
        result = self.run_orchard('build')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no longer read', result.stderr)

    def test_an_older_launcher_says_so_and_update_installs_the_nightlys(self):
        self.assertIn(f'a newer launcher is in {NAME}', self.run_orchard('build').stderr)
        update = self.run_orchard('update')
        self.assertEqual(update.returncode, 0, update.stderr)
        self.assertEqual(self.launcher.read_text(), 'the nightly launcher\n')

    def test_update_replaces_the_link_an_older_setup_made(self):
        self.launcher.unlink()
        self.launcher.symlink_to(ORCHARD)
        self.assertEqual(self.run_orchard('update').returncode, 0)
        self.assertFalse(self.launcher.is_symlink())
        self.assertEqual(self.launcher.read_text(), 'the nightly launcher\n')


if __name__ == '__main__':
    unittest.main()

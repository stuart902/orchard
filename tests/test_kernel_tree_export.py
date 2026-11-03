"""export.py: a branch's defconfig change becomes orchard's config, not a patch."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / 'tools/kernel-tree/export.py'


class Export(unittest.TestCase):
    def test_a_defconfig_change_is_planned_as_a_config_and_the_rest_as_a_patch(self):
        with tempfile.TemporaryDirectory() as temporary:
            linux = Path(temporary) / 'linux'
            git = ['git', '-C', str(linux), '-c', 'user.email=t@example.invalid', '-c', 'user.name=t']
            subprocess.run(['git', 'init', '-q', '-b', 'main', str(linux)], check=True)
            for name, text in (('arch/arm64/configs/orchard_apple16k_defconfig', 'CONFIG_A=y\n'),
                               ('drivers/power/supply/x.c', 'int x;\n')):
                (linux / name).parent.mkdir(parents=True, exist_ok=True)
                (linux / name).write_text(text)
            subprocess.run([*git, 'add', '.'], check=True)
            subprocess.run([*git, 'commit', '-qm', 'base', '--no-gpg-sign'], check=True)
            subprocess.run([*git, 'checkout', '-qb', 'work'], check=True)
            (linux / 'arch/arm64/configs/orchard_apple16k_defconfig').write_text('CONFIG_A=y\nCONFIG_B=y\n')
            (linux / 'drivers/power/supply/x.c').write_text('int y;\n')
            subprocess.run([*git, 'commit', '-qam', 'power: x: Need B', '--no-gpg-sign'], check=True)
            result = subprocess.run([sys.executable, str(EXPORT), '--orchard', str(ROOT), '--linux', str(linux),
                                     '--dry-run', 'work'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('drivers/power/', result.stdout)
            self.assertIn('kernel/configs/apple-16k/config  from arch/arm64/configs/orchard_apple16k_defconfig',
                          result.stdout)


if __name__ == '__main__':
    unittest.main()

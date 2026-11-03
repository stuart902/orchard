"""--kernel-tree: a developer's kernel tree, built as it is with its own defconfig."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from orchard import build, kernel
from orchard.hardware import ROOT

BOARD = 'p105'  # apple-armv7: arch arm, orchard_applearmv7_defconfig


class DeveloperKernelTree(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        cache = patch.dict(os.environ, {'ORCHARD_CACHE_DIR': str(self.root / 'cache')})
        cache.start()
        self.addCleanup(cache.stop)
        self.tree = self.make_tree('linux')

    def make_tree(self, name):
        tree = self.root / name
        (tree / 'arch/arm/configs').mkdir(parents=True)
        (tree / 'Makefile').write_text('VERSION = 6\n')
        (tree / 'arch/arm/configs/orchard_applearmv7_defconfig').write_text('CONFIG_ARCH_APPLE_S5L=y\n')
        (tree / 'drivers').mkdir()
        (tree / 'drivers/driver.c').write_text('int x;\n')
        (tree / '.gitignore').write_text('*.o\n')
        subprocess.run(['git', 'init', '-q', str(tree)], check=True)
        subprocess.run(['git', '-C', str(tree), 'add', '-A'], check=True)
        subprocess.run(['git', '-C', str(tree), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q',
                        '-m', 'tree'], check=True)
        return tree

    def key(self):
        return build.keyed(lambda: build.kernel_base_inputs(ROOT, BOARD, None, self.tree))()

    def test_a_tree_needs_the_platforms_defconfig_and_git(self):
        self.assertEqual(kernel.check_tree(ROOT, BOARD, self.tree), self.tree.resolve())
        (self.tree / 'arch/arm/configs/orchard_applearmv7_defconfig').unlink()
        with self.assertRaisesRegex(ValueError, 'orchard_applearmv7_defconfig'):
            kernel.check_tree(ROOT, BOARD, self.tree)
        bare = self.root / 'not-git'
        (bare / 'arch/arm/configs').mkdir(parents=True)
        (bare / 'Makefile').write_text('')
        (bare / 'arch/arm/configs/orchard_applearmv7_defconfig').write_text('')
        with self.assertRaisesRegex(ValueError, 'not a git checkout'):
            kernel.check_tree(ROOT, BOARD, bare)

    def test_a_tree_builds_inside_itself_and_its_git_ignores_that(self):
        other = self.make_tree('linux-gpu')
        one = kernel.work_directory(ROOT, BOARD, self.tree)
        self.assertEqual(one, self.tree.resolve() / '.orchard-out/apple-armv7')
        self.assertNotEqual(one, kernel.work_directory(ROOT, BOARD, other))
        self.assertNotEqual(one, kernel.work_directory(ROOT, BOARD))
        kernel.check_tree(ROOT, BOARD, self.tree)
        kernel.check_tree(ROOT, BOARD, self.tree)  # once in the exclude file, not twice
        exclude = (self.tree / '.git/info/exclude').read_text()
        self.assertEqual(exclude.splitlines().count('/.orchard-out/'), 1)
        before = self.key()
        (one / 'output').mkdir(parents=True)
        (one / 'output/vmlinux').write_text('build output')
        self.assertEqual(self.key(), before)  # the output is no part of the tree's content
        status = subprocess.run(['git', '-C', str(self.tree), 'status', '--porcelain'], capture_output=True, text=True)
        self.assertNotIn('.orchard-out', status.stdout)

    def test_the_key_follows_the_trees_content_not_orchards_config(self):
        before = self.key()
        (self.tree / 'drivers/driver.o').write_text('build output')  # ignored by the tree
        self.assertEqual(self.key(), before)
        (self.tree / 'arch/arm/configs/orchard_applearmv7_defconfig').write_text('CONFIG_ARCH_APPLE_S5L=n\n')
        changed = self.key()
        self.assertNotEqual(changed, before)
        (self.tree / 'drivers/driver.c').write_text('int y;\n')  # uncommitted edits count
        self.assertNotEqual(self.key(), changed)
        inputs = build.kernel_base_inputs(ROOT, BOARD, None, self.tree)
        self.assertNotIn(kernel.descriptor(ROOT, BOARD)['config'], inputs['recipes'])

    def test_the_argument_wins_over_the_local_file_which_is_relative_to_itself(self):
        project = self.root / 'project'
        (project / '.git').mkdir(parents=True)
        self.assertIsNone(build.resolve_kernel_tree(project))
        (project / 'orchard.local.toml').write_text('kernel-tree = "../linux"\n')
        self.assertEqual(build.resolve_kernel_tree(project), self.tree.resolve())
        self.assertEqual(build.resolve_kernel_tree(project, self.root / 'elsewhere'), (self.root / 'elsewhere').resolve())

    def test_a_staged_kernel_and_a_tree_exclude_each_other(self):
        with self.assertRaisesRegex(ValueError, 'not both'):
            build.prepare_components(ROOT, self.root / 'cache', device=BOARD, kernel=self.root / 'staged',
                                     kernel_tree=self.tree)


if __name__ == '__main__':
    unittest.main()

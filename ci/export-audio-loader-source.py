#!/usr/bin/env python3
"""Export pinned corresponding m1n1 source without rebuilding or running it."""
from pathlib import Path
import subprocess
import tarfile
import tempfile

root = Path(__file__).resolve().parents[1]
lock = dict(line.split('=', 1) for line in (root / 'boot/m1n1/upstream.lock').read_text().splitlines() if '=' in line)
with tempfile.TemporaryDirectory(dir=root / 'out') as temporary:
    source = Path(temporary) / 'source'
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'fetch', '--depth=1', lock['url'], lock['commit']], check=True)
    subprocess.run(['git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
    subprocess.run(['git', '-C', str(source), 'submodule', 'update', '--init', '--depth=1'], check=True)
    for line in (root / 'boot/m1n1/series').read_text().splitlines():
        layer = line.split('#', 1)[0].strip()
        if layer:
            for patch in sorted((root / 'boot/m1n1' / layer).glob('*.patch')):
                subprocess.run(['git', '-C', str(source), 'apply', '--whitespace=nowarn', str(patch)], check=True)
    subprocess.run(['git', '-C', str(source), 'apply', '--whitespace=nowarn', str(root / 'boot/quiet/m1n1.patch')], check=True)
    with tarfile.open(root / 'out/publication/m1n1-source.tar.gz', 'x:gz') as archive:
        def exclude_git(member):
            return None if '.git' in Path(member.name).parts else member
        archive.add(source, arcname='m1n1', filter=exclude_git)

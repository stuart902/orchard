#!/usr/bin/env python3
"""Fetch the unchanged public source archives named by the recovery recipe."""
import hashlib
import json
import pathlib
import subprocess
import urllib.parse
import urllib.request

root = pathlib.Path('out/recovery-tool-sources')
root.mkdir(parents=True, exist_ok=True)
lock = json.loads(pathlib.Path('boot/initramfs/recovery/upstream.lock').read_text())
for name, item in lock.items():
    filename = pathlib.PurePosixPath(urllib.parse.urlsplit(item['url']).path).name
    destination = root / filename
    with urllib.request.urlopen(item['url']) as response, destination.open('wb') as out:
        while block := response.read(1024 * 1024):
            out.write(block)
    with destination.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
            raise SystemExit(f'{name}: source/input checksum mismatch')
    if name == 'busybox':
        source = subprocess.check_output(['dpkg-deb', '-f', str(destination), 'Source'], text=True).strip()
        # Debian binary-only rebuilds retain the parent source version.
        package, version = source.split(' (', 1)
        subprocess.run(['apt-get', 'source', '--download-only', package + '=' + version.rstrip(')')],
                       cwd=root, check=True)
# Build scripts, lock and toolchain recipe are supplied in the Orchard source.
# The reused tool artifact's recorded toolchain is musl 1.2.3-1.
subprocess.run(['apt-get', 'source', '--download-only', 'musl=1.2.3-1'], cwd=root, check=True)
import tarfile
for archive in root.glob('musl_*.orig.tar.*'):
    if not archive.name.endswith(('.tar.gz', '.tar.bz2', '.tar.xz')):
        continue
    with tarfile.open(archive) as tar:
        notices = [m for m in tar.getmembers() if m.name.endswith('/COPYRIGHT') and m.isfile()]
        if len(notices) != 1:
            raise SystemExit('Expected one musl copyright notice')
        (root / 'COPYRIGHT.musl').write_bytes(tar.extractfile(notices[0]).read())
if not (root / 'COPYRIGHT.musl').is_file():
    raise SystemExit('Missing musl source/copyright')

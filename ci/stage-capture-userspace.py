#!/usr/bin/env python3
"""Stage distro arecord and its ELF dependencies; no capture or playback."""
import pathlib
import re
import shutil
import subprocess

root = pathlib.Path('out/capture-root')
root.mkdir(parents=True, exist_ok=True)
program = pathlib.Path(shutil.which('arecord'))
ldd = subprocess.check_output(['ldd', str(program)], text=True)
if 'not found' in ldd:
    raise SystemExit('Missing arecord shared library')
paths = {program}
paths.update(pathlib.Path(p) for p in re.findall(r'(/[^\s()]+)', ldd))
sources = set()
for path in sorted(paths):
    destination = root / path.relative_to('/')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    owner = subprocess.check_output(['dpkg-query', '-S', str(path)], text=True).split(': ', 1)[0]
    source = subprocess.check_output(['dpkg-query', '-W', '-f=${source:Package}=${source:Version}', owner], text=True)
    sources.add(source)
shutil.copytree('/usr/share/alsa', root / 'usr/share/alsa')
# The RAM system uses /usr/bin; Debian may resolve arecord through /bin.
if not (root / 'usr/bin/arecord').exists():
    (root / 'usr/bin').mkdir(parents=True, exist_ok=True)
    shutil.copy2(program, root / 'usr/bin/arecord')
subprocess.run(['chroot', str(root), '/usr/bin/arecord', '--version'], check=True)
subprocess.run(['chroot', str(root), '/usr/bin/arecord', '--help'], check=True,
               stdout=subprocess.DEVNULL)
pathlib.Path('out/capture-source-packages.txt').write_text('\n'.join(sorted(sources)) + '\n')
pathlib.Path('out/capture-ldd.txt').write_text(ldd)

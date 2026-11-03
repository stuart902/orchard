#!/usr/bin/env python3
"""Stage distro arecord and its ELF dependencies; no capture or playback."""
import pathlib
import re
import shutil
import subprocess

def package_owner(path):
    # ldd prints loader paths; dpkg may record their merged-/usr aliases.
    candidates = [path, path.resolve()]
    for candidate in list(candidates):
        name = str(candidate)
        if name.startswith('/usr/'):
            candidates.append(pathlib.Path(name[4:]))
        elif name.startswith(('/lib/', '/bin/', '/sbin/')):
            candidates.append(pathlib.Path('/usr' + name))
    for candidate in dict.fromkeys(candidates):
        if not candidate.exists() or candidate.resolve() != path.resolve():
            continue
        result = subprocess.run(['dpkg-query', '-S', str(candidate)],
                                text=True, capture_output=True)
        if result.returncode == 0:
            return result.stdout.split(': ', 1)[0]
    raise SystemExit(f'No Debian package owns {path}')


root = pathlib.Path('out/capture-root')
root.mkdir(parents=True, exist_ok=True)
program = pathlib.Path(shutil.which('arecord'))
ldd = subprocess.check_output(['ldd', str(program)], text=True)
if 'not found' in ldd:
    raise SystemExit('Missing arecord shared library')
paths = {program}
paths.update(pathlib.Path(p) for p in re.findall(r'(/[^\s()]+)', ldd))
sources = set()
owners = {"libasound2-data"}
for path in sorted(paths):
    destination = root / path.relative_to('/')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    owner = package_owner(path)
    source = subprocess.check_output(['dpkg-query', '-W', '-f=${source:Package}=${source:Version}', owner], text=True)
    sources.add(source)
    owners.add(owner)
shutil.copytree('/usr/share/alsa', root / 'usr/share/alsa')
for owner in sorted(owners):
    source = subprocess.check_output(['dpkg-query', '-W', '-f=${source:Package}=${source:Version}', owner], text=True)
    sources.add(source)
    package = owner.split(':', 1)[0]
    copyright_file = pathlib.Path('/usr/share/doc') / package / 'copyright'
    if not copyright_file.is_file():
        raise SystemExit(f'Missing copyright notice for {owner}')
    destination = root / 'usr/share/doc' / package / 'copyright'
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(copyright_file, destination)
pathlib.Path('out/capture-binary-packages.txt').write_text(
    subprocess.check_output(['dpkg-query', '-W', '-f=${binary:Package} ${Version}\\n', *sorted(owners)], text=True))
# The RAM system uses /usr/bin; Debian may resolve arecord through /bin.
if not (root / 'usr/bin/arecord').exists():
    (root / 'usr/bin').mkdir(parents=True, exist_ok=True)
    shutil.copy2(program, root / 'usr/bin/arecord')
subprocess.run(['chroot', str(root), '/usr/bin/arecord', '--version'], check=True)
subprocess.run(['chroot', str(root), '/usr/bin/arecord', '--help'], check=True,
               stdout=subprocess.DEVNULL)
pathlib.Path('out/capture-source-packages.txt').write_text('\n'.join(sorted(sources)) + '\n')
pathlib.Path('out/capture-ldd.txt').write_text(ldd)

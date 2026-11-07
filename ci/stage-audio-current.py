#!/usr/bin/env python3
"""Build-only reuse, staging and provenance for the J71b audio test variant."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
OUT = ROOT / 'out'
SOURCE_RUN = 41669566156
SOURCE_ARTIFACT = 13248760109
SOURCE_COMMIT = '70af56d6962cfb800483dca566d89224a5f06384'
SOURCE_DIGEST = '894aca22eeaee38bef59b896b0530d90e6fd741810c2a799e14014aa7663e2f2'
MODULES = ('apple-aop.ko', 'aop-audio.ko', 'apple-sio.ko', 'apple-sio-dma.ko',
           't8010-pdm.ko', 'snd-soc-dmic.ko', 'snd-soc-max98357a.ko',
           'snd-soc-simple-card.ko', 'snd-soc-simple-card-utils.ko', 'snd-soc-apple-s8000-mca.ko')


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def json_file(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def safe_members(archive):
    members = archive.getmembers()
    seen = set()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
            raise ValueError('Unsafe archive member: ' + member.name)
        name = path.as_posix()
        if name in seen:
            raise ValueError('Duplicate archive member: ' + name)
        seen.add(name)
    return members


def download(url, path, checksum, maximum):
    temporary = Path(str(path) + '.part')
    try:
        with urllib.request.urlopen(url, timeout=300) as response, temporary.open('wb') as target:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > maximum:
                    raise ValueError('Download exceeds expected size')
                target.write(block)
        if digest(temporary) != checksum:
            raise ValueError('Downloaded checksum differs: ' + Path(path).name)
        temporary.rename(path)
    finally:
        temporary.unlink(missing_ok=True)


def source_recipe_matches(archive, inputs):
    files = set()
    for name in inputs:
        path = ROOT / name
        if path.is_dir():
            files.update(p.relative_to(ROOT).as_posix() for p in path.rglob('*') if p.is_file())
        else:
            files.add(name)
    with tarfile.open(archive) as tar:
        rows = {m.name.removeprefix('./'): m for m in tar.getmembers()}
        for name in files:
            member = rows.get(name)
            if member is None or not member.isfile() or tar.extractfile(member).read() != (ROOT / name).read_bytes():
                raise ValueError('Reused recipe differs: ' + name)
        archived = {name for name, member in rows.items() if member.isfile() and
                    any(name == prefix or name.startswith(prefix + '/') for prefix in inputs)}
        if archived != files:
            raise ValueError('Reused recipe inventory differs')
    return sorted(files)


def recovery_sources(destination):
    api = 'https://api.github.com/repos/stuart902/orchard'
    token = os.environ['GH_TOKEN']
    def get(path):
        request = urllib.request.Request(api + path, headers={'Authorization': 'Bearer ' + token,
                                         'Accept': 'application/vnd.github+json'})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    run = get('/actions/runs/' + str(SOURCE_RUN))
    if run['head_sha'] != SOURCE_COMMIT or run['conclusion'] != 'success' or run['status'] != 'completed':
        raise ValueError('Recovery source run is not the exact successful input')
    meta = get('/actions/artifacts/' + str(SOURCE_ARTIFACT))
    if meta['expired'] or meta['workflow_run']['id'] != SOURCE_RUN or meta['digest'] != 'sha256:' + SOURCE_DIGEST:
        raise ValueError('Recovery source artifact identity differs')
    with tempfile.TemporaryDirectory(dir=OUT) as directory:
        zipped = Path(directory) / 'source.zip'
        # curl does not forward Authorization on the cross-host download redirect.
        result = subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                                 '--connect-timeout', '30', '--max-time', '600',
                                 '-H', 'Authorization: Bearer ' + token,
                                 api + '/actions/artifacts/' + str(SOURCE_ARTIFACT) + '/zip',
                                 '-o', str(zipped)])
        if result.returncode:
            raise ValueError('Recovery source artifact download failed')
        if digest(zipped) != SOURCE_DIGEST:
            raise ValueError('Recovery source ZIP checksum differs')
        with zipfile.ZipFile(zipped) as archive:
            matches = [m for m in archive.infolist() if m.filename == 'recovery-tool-source.tar.gz']
            if len(matches) != 1 or matches[0].file_size > 1024 ** 3:
                raise ValueError('Expected one bounded recovery source archive')
            with archive.open(matches[0]) as source, destination.open('wb') as target:
                shutil.copyfileobj(source, target)
    lock = json.loads((ROOT / 'boot/initramfs/recovery/upstream.lock').read_text())
    with tarfile.open(destination) as archive:
        members = safe_members(archive)
        for item in lock.values():
            filename = PurePosixPath(urllib.parse.urlsplit(item['url']).path).name
            matches = [m for m in members if m.isfile() and PurePosixPath(m.name).name == filename]
            if len(matches) != 1 or hashlib.sha256(archive.extractfile(matches[0]).read()).hexdigest() != item['sha256']:
                raise ValueError('Recovery source does not match current lock: ' + filename)
        if not any(m.isfile() and PurePosixPath(m.name).name == 'COPYRIGHT.musl' for m in members):
            raise ValueError('Missing musl source notice')
    return {'repository': 'stuart902/orchard', 'run': SOURCE_RUN, 'artifact': SOURCE_ARTIFACT,
            'commit': SOURCE_COMMIT, 'zip_sha256': SOURCE_DIGEST, 'source_sha256': digest(destination)}


def reuse():
    from orchard.build import M1N1_INPUTS, TOOL_INPUTS, PONGO_RECIPE
    from orchard.published import shared_keys, tools
    record = json.loads((ROOT / 'ci/j71b-audio-reuse.json').read_text())
    reused = OUT / 'reused'
    reused.mkdir(parents=True)
    for name, asset in record['assets'].items():
        download(asset['url'], reused / name, asset['sha256'], asset['bytes'])
        if (reused / name).stat().st_size != asset['bytes']:
            raise ValueError('Unexpected asset size: ' + name)
    recipes = source_recipe_matches(reused / 'orchard-source.tar.gz', sorted(set(M1N1_INPUTS + TOOL_INPUTS + PONGO_RECIPE)))
    keys = json.loads((reused / 'component-keys.json').read_text())
    for name, key in shared_keys(ROOT).items():
        if keys['shared'][name]['key'] != key:
            raise ValueError('Published component recipe key differs: ' + name)
    with tarfile.open(reused / 'tool-components.tar.gz') as archive:
        members = safe_members(archive)
        if any(not (m.name == 'components' or m.name.startswith('components/')) for m in members):
            raise ValueError('Unexpected tool archive root')
        archive.extractall(OUT, members=members, filter='data')
    target = OUT / 'components'
    if digest(target / 'quiet/m1n1.bin') != record['assets']['m1n1.bin']['sha256']:
        raise ValueError('Bundled loader differs from published loader')
    shutil.copy2(reused / 'pongo.bin', target / 'quiet/pongo.bin')
    package_lock = (target / 'tools-toolchain-packages.lock').read_text()
    if not any(line.split() == ['musl:arm64', '1.2.3-1'] or line.split() == ['musl', '1.2.3-1'] for line in package_lock.splitlines()):
        raise ValueError('Recovery musl source version needs a new review')
    recovery = recovery_sources(reused / 'recovery-tool-source.tar.gz')
    # Use Orchard's supported published-component path to prime its cache. A
    # subsequent orchard build reuses this exact checked entry, never a new nightly.
    cached_tools = tools(ROOT, Path(os.environ['ORCHARD_CACHE_DIR']), tag=record['tag'])
    if cached_tools is None:
        raise ValueError('Exact published tools could not be resolved')
    for name in ('busybox', 'dropbear', 'dropbearkey', 'wpa_supplicant', 'wpa_cli', 'iw'):
        if digest(cached_tools / name) != digest(target / 'boot' / name):
            raise ValueError('Cached tool differs from pinned archive: ' + name)
    record.update(recipe_inputs_equal=recipes, recovery_sources=recovery,
                  files={p.relative_to(target).as_posix(): digest(p) for p in target.rglob('*') if p.is_file()})
    json_file(target / 'reuse-receipt.json', record)


def audit_modules(kernel):
    release = (kernel / 'kernel.release').read_text().strip()
    if release != '7.3.0-rc1-j71b-speaker-window-nov7-r1-orchard-apple-16k':
        raise ValueError('Unexpected test kernel release: ' + release)
    roots = list((kernel / 'lib/modules').iterdir())
    if len(roots) != 1 or roots[0].name != release:
        raise ValueError('Kernel/module release mismatch')
    modules = roots[0]
    dependencies = {}
    for line in (modules / 'modules.dep').read_text().splitlines():
        name, separator, rest = line.partition(':')
        if not separator or name in dependencies:
            raise ValueError('Invalid module dependency entry')
        dependencies[name] = rest.split()
    for name in ('modules.dep.bin', 'modules.alias.bin'):
        if not (modules / name).is_file() or not (modules / name).stat().st_size:
            raise ValueError('Missing module index: ' + name)
    pending = []
    for name in MODULES:
        matches = list(modules.rglob(name))
        if len(matches) != 1:
            raise ValueError('Missing/ambiguous module: ' + name)
        pending.append(matches[0].relative_to(modules).as_posix())
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts or not (modules / name).is_file() or name not in dependencies:
            raise ValueError('Invalid module dependency: ' + name)
        pending.extend(dependencies[name])
    aliases = {tuple(line.split()) for line in (modules / 'modules.alias').read_text().splitlines() if not line.startswith('#')}
    for compatible, module in [('apple,j71b-pdm', 't8010_pdm'), ('apple,t8010-aop-audio', 'aop_audio'),
                               ('apple,t8010-aop', 'apple_aop'), ('apple,t8010-sio', 'apple_sio'),
                               ('apple,t8010-mca', 'snd_soc_apple_s8000_mca'), ('maxim,max98357a', 'snd_soc_max98357a'),
                               ('dmic-codec', 'snd_soc_dmic'), ('simple-audio-card', 'snd_soc_simple_card')]:
        if ('alias', 'of:N*T*C' + compatible, module) not in aliases:
            raise ValueError('Missing exact module alias: ' + compatible)
    if ('alias', 'platform:apple-sio-dma', 'apple_sio_dma') not in aliases:
        raise ValueError('Missing SmartIO module alias')
    hashes = {}
    for path in sorted(modules.rglob('*.ko')):
        if subprocess.check_output(['modinfo', '-F', 'vermagic', str(path)], text=True).split()[0] != release:
            raise ValueError('Wrong module vermagic: ' + str(path))
        elf = path.read_bytes()[:20]
        if elf[:6] != b'\x7fELF\x02\x01' or elf[18:20] != b'\xb7\x00':
            raise ValueError('Module is not little-endian ELF64 AArch64: ' + str(path))
        hashes[path.relative_to(modules).as_posix()] = digest(path)
    codec = next(modules.rglob('snd-soc-max98357a.ko'))
    audit_gate(codec)
    return release, hashes


def audit_gate(codec):
    parameters = subprocess.check_output(['modinfo', '-p', str(codec)], text=True)
    if 'j71b_test_arm:Permit one 30 ms J71b amplifier test window (default: false) (bool)' not in parameters.splitlines():
        raise ValueError('Compiled codec lacks the diagnostic parameter')
    symbols = subprocess.check_output(['llvm-nm-19', '--format=posix', str(codec)], text=True)
    arm = [line.split() for line in symbols.splitlines() if line.split() and line.split()[0] == 'j71b_test_arm']
    if len(arm) != 1 or len(arm[0]) != 4 or arm[0][1] not in ('b', 'B') or int(arm[0][3], 16) != 1:
        raise ValueError('Compiled arming boolean is not zero-initialized BSS')
    return {'module_sha256': digest(codec), 'arming_default': False,
            'arming_symbol_storage': 'BSS', 'parameter_permission_source': '0400',
            'window_ms': 30, 'physical_cutoff_verified': False}


def audit_dtb(dtb):
    def fdt(node, prop, kind=None):
        return subprocess.check_output(['fdtget', *(['-d', 'okay'] if node == '/sound' and prop == 'status' else []), *(['-t', kind] if kind else []), str(dtb), node, prop], text=True).strip()
    for node, expected in [('/dmic', 'okay'), ('/microphones', 'okay'), ('/soc/pdm@20a0b4000', 'okay'),
                           ('/soc/aop@210800000/aop-audio', 'okay'), ('/sound', 'okay'),
                           ('/soc/mca@20a0a8000', 'okay')]:
        if fdt(node, 'status') != expected:
            raise ValueError('Wrong DT state: ' + node)
    if fdt('/sound', 'simple-audio-card,format') != 'dsp_a':
        raise ValueError('Current upstream TDM format was not preserved')
    amp = fdt('/__symbols__', 'speaker_amps')
    if fdt(amp, 'maxim,tdm') != '':
        raise ValueError('Amplifier TDM property is not boolean')
    if fdt(amp, 'compatible') != 'maxim,max98357a':
        raise ValueError('Wrong amplifier codec')
    controller = fdt('/__symbols__', 'pinctrl_ap')
    if fdt(amp, 'sdmode-gpios', 'x').split() != [fdt(controller, 'phandle', 'x'), '14', '0']:
        raise ValueError('SD_MODE is not pinctrl_ap GPIO20 active high')
    if fdt('/dmic', 'num-channels', 'u') != '2':
        raise ValueError('Expected two capture channels')
    if fdt('/soc/pdm@20a0b4000', 'dmas', 'x').split()[-1] != '5b':
        raise ValueError('Wrong PDM DMA endpoint')


def stage(expected_commit):
    from orchard.ram import verify_ram
    receipt = verify_ram(ROOT / 'examples/hardware-check/out/apple-16k')
    kernel = Path(receipt['assembly']['kernel']).parent
    target = OUT / 'components'
    shutil.copytree(kernel, target / 'kernel')
    config = ROOT / 'linux/.orchard-out/apple-16k/output/.config'
    shutil.copy2(config, target / 'resolved.config')
    subprocess.run([sys.executable, str(ROOT / 'ci/audit-audio-current.py'), str(ROOT / 'linux'),
                    '--variant', 'speaker', '--expected-commit', expected_commit,
                    '--config', str(config), '--baseline-config', str(ROOT / 'kernel/configs/apple-16k/config'),
                    '--pages', '16k', '--output', str(target / 'integration-receipt.json')], check=True)
    release, modules = audit_modules(target / 'kernel')
    dtb = target / 'kernel/dtbs/t8010-j71b.dtb'
    audit_dtb(dtb)
    record = json.loads((target / 'integration-receipt.json').read_text())
    record.update(workflow_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  platform='apple-16k', kernel_release=release, hardware_tested=False,
                  build_run=int(os.environ['GITHUB_RUN_ID']), modules=modules,
                  dtb_sha256=digest(dtb), image_sha256=digest(target / 'kernel/Image.gz'),
                  speaker_topology_enabled=True, amplifier_default_unarmed=True,
                  upstream_tdm_preserved=True,
                  diagnostic_gate=audit_gate(next((target / 'kernel/lib/modules').rglob('snd-soc-max98357a.ko'))),
                  package_kind='components-only-no-installer', arming_configuration_included=False)
    json_file(target / 'integration-receipt.json', record)
    shutil.copy2(ROOT / 'examples/hardware-check/out/apple-16k/build.json', target / 'ram-assembly-receipt.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('reuse', 'stage'))
    parser.add_argument('--expected-commit')
    args = parser.parse_args()
    if args.action == 'reuse':
        reuse()
    elif not args.expected_commit:
        parser.error('--expected-commit is required for staging')
    else:
        stage(args.expected_commit)

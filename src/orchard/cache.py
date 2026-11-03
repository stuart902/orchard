"""Central Orchard store, independent of distro and source checkout."""
import json
import os
from pathlib import Path
import shutil
import sys

# The layout of Orchard's directories. A tool that finds a newer version
# refuses to touch them; a newer tool migrates an older layout, then records
# its own version. Raise it with every change older tools would misread.
STATE_VERSION = 1


def cache_root() -> Path:
    override = os.environ.get('ORCHARD_HOME')
    if override:
        return Path(override).expanduser().absolute()
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Orchard'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'orchard'


def check_state(root=None):
    """Refuse ROOT (default: the store) if a newer orchard laid it out; record this version otherwise.

    Every orchard on a host shares its directories: the user's orchard, a
    distribution's installer, development checkouts. Returns the version found
    (0 for a directory no versioned orchard has written yet).
    """
    root = Path(root) if root is not None else cache_root()
    record = root / 'state.json'
    try:
        found = json.loads(record.read_text())['version']
    except FileNotFoundError:
        found = 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'{record} is unreadable ({error}); move it away and retry') from error
    if not isinstance(found, int) or found > STATE_VERSION:
        raise ValueError(f'{root} was laid out by a newer orchard (state {found}, this one knows '
                         f'{STATE_VERSION}); update orchard: orchard update')
    if found < STATE_VERSION:
        root.mkdir(parents=True, exist_ok=True)
        partial = record.with_name(f'.state-{os.getpid()}.json')
        partial.write_text(json.dumps({'version': STATE_VERSION}) + '\n')
        os.replace(partial, record)
    return found


MIN_FREE_GB = 10  # a kernel, root or image build; ORCHARD_MIN_FREE_GB changes it, 0 turns the check off


def check_free(*paths):
    """Refuse to start a build when a filesystem under PATHS has less than MIN_FREE_GB free.

    A build that runs out of space halfway leaves broken work directories and
    stops other builds on the host; refusing up front costs nothing.
    """
    needed = float(os.environ.get('ORCHARD_MIN_FREE_GB', MIN_FREE_GB))
    if needed <= 0:
        return
    for path in paths:
        path = Path(path)
        while not path.exists() and path != path.parent:
            path = path.parent
        free = shutil.disk_usage(path).free / 1e9
        if free < needed:
            raise ValueError(f'Only {free:.1f} GB free on the disk of {path}; a build needs {needed:g} GB. '
                             'Free space first (orchard cache --prune, your own out/ builds), or set '
                             'ORCHARD_MIN_FREE_GB to change the limit')

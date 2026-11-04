#!/usr/bin/env python3
"""Run Orchard's documented export workflow for the J71b submission."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = "0b1ed24f6d10d2a539101945061c21b6907c1d32"
CANDIDATE = "9a70f8a7864d0a96ba907e4d1e5440fefb94bc5e"
LINUX_SOURCE = "778174c50d5fd6b36849f9eea728a6811b1b6e9e"
workspace = Path.cwd()
scratch = Path(os.environ["RUNNER_TEMP"]) / "j71b-documented-export"
scratch.mkdir()
orchard = scratch / "orchard"
linux = scratch / "linux"
m1n1 = scratch / "m1n1"
out = workspace / "out" / "j71b-export"
out.mkdir(parents=True)

def run(*args, cwd=None, capture=False):
    result = subprocess.run([str(x) for x in args], cwd=cwd, check=True,
                            text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else None

def git(repo, *args):
    return run("git", "-C", repo, *args, capture=True)

assert shutil.disk_usage(workspace).free >= 10 * 1024**3
run("git", "config", "--global", "user.name", "Stuart Fraser")
run("git", "config", "--global", "user.email", "60394096+stuart902@users.noreply.github.com")
run("git", "fetch", "--no-tags", "origin", SOURCE, CANDIDATE)
run("git", "worktree", "add", "--detach", orchard, SOURCE)
run("git", "clone", "--depth=1", "--no-checkout", "https://github.com/OrchardLinux/linux.git", linux)
run("git", "clone", "--no-checkout", "https://github.com/OrchardLinux/m1n1.git", m1n1)
# Keep regeneration away from a checked-out branch; these are disposable clones.
run("git", "-C", linux, "symbolic-ref", "HEAD", "refs/heads/export-workspace")
run("git", "-C", m1n1, "symbolic-ref", "HEAD", "refs/heads/export-workspace")

# Use the repository's unmodified regeneration command and toolchain.
run(sys.executable, orchard / "tools/kernel-tree/regenerate",
    "--linux", linux, "--m1n1", m1n1, SOURCE, cwd=orchard)
base = git(linux, "rev-parse", "main")
run("git", "-C", linux, "switch", "-c", "j71b-power-export", base)

patch_inputs = [
    "kernel/patches/drivers/power/0019-dt-bindings-power-reset-Describe-Apple-D2365-power-o.patch",
    "kernel/patches/drivers/gpio/0005-gpio-apple-d2365-Expose-scoped-PMU-event-quiescing.patch",
    "kernel/patches/drivers/power/0020-power-reset-Add-Apple-D2365-shutdown-and-restart-pre.patch",
    "kernel/patches/devices/t8010/0017-arm64-dts-apple-t8010-j71b-Describe-PMIC-power-off.patch",
]
source_commits = []
for i, name in enumerate(patch_inputs):
    patch = scratch / ("source-%d.patch" % i)
    patch.write_bytes(subprocess.check_output(["git", "-C", str(orchard), "show", CANDIDATE + ":" + name]))
    run("git", "-C", linux, "am", patch)
    source_commits.append(git(linux, "rev-parse", "HEAD"))

for name in ("orchard_apple4k_defconfig", "orchard_apple16k_defconfig"):
    run(linux / "scripts/config", "--file", linux / "arch/arm64/configs" / name,
        "--enable", "POWER_RESET_APPLE_D2365")
run("git", "-C", linux, "add", "arch/arm64/configs/orchard_apple4k_defconfig",
    "arch/arm64/configs/orchard_apple16k_defconfig")
run("git", "-C", linux, "commit", "-m", "arm64: configs: enable J71b PMIC power-off",
    "-m", "Enable the built-in D2365 power-off handler in both Orchard ARM64 configurations.\n\nAssisted-by: LLM")
source_tip = git(linux, "rev-parse", "HEAD")

production = [
    "arch/arm64/boot/dts/apple/t8010-j71b.dts",
    "drivers/gpio/gpio-apple-d2365.c",
    "include/linux/gpio/apple-d2365.h",
    "Documentation/devicetree/bindings/mfd/apple,pmic.yaml",
    "Documentation/devicetree/bindings/power/reset/apple,d2365-poweroff.yaml",
    "drivers/power/reset/Kconfig", "drivers/power/reset/Makefile",
    "drivers/power/reset/apple-d2365-poweroff.c",
]
run("git", "-C", linux, "fetch", "--no-tags", "--depth=1",
    "https://github.com/stuart902/linux.git", LINUX_SOURCE)
for name in production:
    assert git(linux, "rev-parse", source_tip + ":" + name) == git(linux, "rev-parse", LINUX_SOURCE + ":" + name), name
before = set(git(orchard, "ls-files", "kernel/patches").splitlines())
base_configs = {p: (orchard / p).read_bytes() for p in
                ("kernel/configs/apple-4k/config", "kernel/configs/apple-16k/config")}
export_command = [sys.executable, orchard / "tools/kernel-tree/export.py",
                  "--orchard", orchard, "--linux", linux, "--base", base,
                  "--topic", source_commits[0] + "=drivers/power", "j71b-power-export"]
run(*export_command, "--dry-run", cwd=orchard)
run(*export_command, cwd=orchard)
generated = sorted(set(str(p.relative_to(orchard)) for p in (orchard / "kernel/patches").rglob("*.patch")) - before)
assert len(generated) == 4, generated
for path in before:
    assert git(orchard, "hash-object", orchard / path) == git(orchard, "rev-parse", SOURCE + ":" + path), path
for path, content in base_configs.items():
    anchor = b"CONFIG_POWER_RESET_MACSMC=y\n"
    assert content.count(anchor) == 1 and b"CONFIG_POWER_RESET_APPLE_D2365=" not in content
    expected = content.replace(anchor, anchor + b"CONFIG_POWER_RESET_APPLE_D2365=y\n")
    assert (orchard / path).read_bytes() == expected, path

test_paths = [
    "tests/test_d2365_poweroff.py", "tests/fixtures/d2365/checks.c",
    "tests/fixtures/d2365/mock.h", "tests/fixtures/d2365/probe.c",
]
for path in test_paths:
    target = orchard / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(subprocess.check_output(["git", "-C", str(orchard), "show", CANDIDATE + ":" + path]))
changelog = orchard / "CHANGELOG.md"
content = changelog.read_text()
anchor = "### Hardware\n\n"
assert content.count(anchor) == 1
entry = "- Add experimental PMIC power-off handling for iPad (6th generation, Wi-Fi;\n  iPad7,5 / J71b).\n"
changelog.write_text(content.replace(anchor, anchor + entry))
run(sys.executable, "-m", "pip", "install", "-e", ".[validate]", cwd=orchard)
run(sys.executable, "-m", "pip", "check", cwd=orchard)
run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v", cwd=orchard)
# Source whitespace checks exclude mail-patch context lines.
run("git", "-C", linux, "diff", "--check", base, source_tip)
run("git", "-C", orchard, "diff", "--check", "--", "CHANGELOG.md", "kernel/configs", "tests")

expected_paths = sorted(generated + list(base_configs) + test_paths + ["CHANGELOG.md"])
actual = sorted(set(git(orchard, "diff", "--name-only").splitlines()) |
                set(git(orchard, "ls-files", "--others", "--exclude-standard").splitlines()))
assert actual == expected_paths, (actual, expected_paths)
run("git", "-C", orchard, "add", "--", *expected_paths)
tree = git(orchard, "write-tree")
receipt = {"orchard_base": SOURCE, "input_candidate": CANDIDATE,
           "kernel_base": base, "kernel_candidate": source_tip,
           "kernel_tree": git(linux, "rev-parse", source_tip + "^{tree}"),
           "orchard_tree": tree, "generated_patches": generated,
           "production_equal_linux": LINUX_SOURCE,
           "upstream_patches_unchanged": True, "configs_exact_delta": True,
           "host_tests_passed": True, "device_tested": False,
           "export_command": [str(x) for x in export_command]}
(out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print("EXPORT_RECEIPT " + json.dumps(receipt), flush=True)
for path in generated:
    data = {"path": path, "blob": git(orchard, "hash-object", orchard / path),
            "content": (orchard / path).read_text()}
    print("EXPORT_FILE " + json.dumps(data), flush=True)
    target = out / path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(orchard / path, target)
for path in list(base_configs) + test_paths + ["CHANGELOG.md"]:
    print("EXPORT_BLOB " + json.dumps({"path": path, "blob": git(orchard, "hash-object", orchard / path)}), flush=True)
run("git", "-C", orchard, "diff", "--cached", "--stat", SOURCE)
print("Documented export and host tests passed. No kernel/image build or device access was performed.", flush=True)

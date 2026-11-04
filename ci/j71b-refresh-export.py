#!/usr/bin/env python3
"""Run Orchard's documented export workflow for the J71b submission."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

SOURCE = "d3cf992b03c898f2ca46757046124e9cb84baac3"
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
# Refuse to export onto a stale base; this job never updates main.
remote_main = run("git", "ls-remote", "https://github.com/OrchardLinux/orchard.git",
                  "refs/heads/main", capture=True).split()[0]
assert remote_main == SOURCE, ("upstream advanced; refresh the source pin", remote_main)
assert git(workspace, "rev-parse", "origin/main") == SOURCE
run("git", "-C", orchard, "switch", "-c", "j71b-orchard-export-review")
# Regenerate fetches the declared public upstreams. Do not carry an unrelated
# shallow boundary from the separately published generated Linux main.
run("git", "init", linux)
run("git", "-C", linux, "remote", "add", "origin", "https://github.com/OrchardLinux/linux.git")
run("git", "clone", "--no-checkout", "https://github.com/OrchardLinux/m1n1.git", m1n1)
# Keep regeneration away from a checked-out branch; these repositories are disposable.
run("git", "-C", linux, "symbolic-ref", "HEAD", "refs/heads/export-workspace")
run("git", "-C", m1n1, "symbolic-ref", "HEAD", "refs/heads/export-workspace")

# Use the repository's unmodified regeneration command and toolchain.
run(sys.executable, orchard / "tools/kernel-tree/regenerate",
    "--linux", linux, "--m1n1", m1n1, SOURCE, cwd=orchard)
base = git(linux, "rev-parse", "main")
description = json.loads(run(sys.executable, orchard / "kernel/series.py",
                             "--platform", "apple-16k", capture=True))
upstream = dict(line.split("=", 1) for line in
                (orchard / description["upstream"]).read_text().splitlines()
                if "=" in line)
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
# Validation history follows the same logical split as the submission.
# These local commits are retained in the bundle, not pushed by this job.
logical_groups = [
    ("power: add J71b shutdown and restart preparation",
     "Add the D2365 sys-off preparation driver, same-PMIC GPIO event quiescing, "
     "bindings and the J71b device node. Enable CONFIG_POWER_RESET_APPLE_D2365=y "
     "in both apple-4k and apple-16k so the built-in handler is available at "
     "shutdown; only J71b instantiates it.",
     generated + list(base_configs)),
    ("tests: cover D2365 shutdown and provider lifetime",
     "Exercise the exported driver and GPIO helper with an in-memory bus and "
     "provider fixtures. Cover transaction failure, handler ordering and "
     "reference cleanup without device access.",
     test_paths),
    ("docs: note experimental J71b PMIC power-off support",
     "Record the experimental J71b power-off behavior under Unreleased.",
     ["CHANGELOG.md"]),
]
validation_commits = []
for subject, body, paths in logical_groups:
    run("git", "-C", orchard, "add", "--", *paths)
    run("git", "-C", orchard, "commit", "-m", subject, "-m",
        textwrap.fill(body, width=72) + "\n\nAssisted-by: LLM")
    validation_commits.append(git(orchard, "rev-parse", "HEAD"))
candidate = git(orchard, "rev-parse", "HEAD")
tree = git(orchard, "rev-parse", candidate + "^{tree}")
assert git(orchard, "status", "--porcelain") == ""
assert git(orchard, "rev-list", "--count", SOURCE + ".." + candidate) == "3"

# The exporter requires a second regeneration after committing, to verify
# the real repository series order rather than just export order.
run(sys.executable, orchard / "tools/kernel-tree/regenerate",
    "--linux", linux, "--m1n1", m1n1, candidate, cwd=orchard)
roundtrip = git(linux, "rev-parse", "main")
run("git", "-C", linux, "diff", "--exit-code", source_tip, roundtrip, "--", ".",
    ":(exclude,glob)arch/*/configs/orchard_*_defconfig")
# regenerate also checks each expanded defconfig against Orchard byte-for-byte.
assert git(orchard, "rev-parse", "HEAD^{tree}") == tree
assert git(orchard, "status", "--porcelain") == ""

# Retain replayable Git history with explicit, public prerequisites. Bundling
# only descendants avoids duplicating the upstream kernel's full history.
kernel_bundle = out / "kernel-source.bundle"
run("git", "-C", linux, "bundle", "create", kernel_bundle,
    "^" + upstream["commit"], "refs/heads/j71b-power-export", "refs/heads/main")
# Prove the bundle can restore the exact source and round-trip commits in a
# fresh repository seeded only with the declared public upstream prerequisite.
restored = scratch / "restored-kernel"
run("git", "init", "--bare", restored)
run("git", "-C", restored, "fetch", "--no-tags", "--depth=1",
    upstream["url"], upstream["commit"])
run("git", "-C", restored, "bundle", "verify", kernel_bundle)
run("git", "-C", restored, "fetch", kernel_bundle,
    "refs/heads/j71b-power-export:refs/heads/j71b-power-export",
    "refs/heads/main:refs/heads/main")
assert git(restored, "rev-parse", "j71b-power-export") == source_tip
assert git(restored, "rev-parse", "main") == roundtrip
assert git(restored, "rev-parse", source_tip + "^{tree}") == git(linux, "rev-parse", source_tip + "^{tree}")
shutil.rmtree(restored)
orchard_bundle = out / "orchard-export-review.bundle"
run("git", "-C", orchard, "bundle", "create", orchard_bundle,
    SOURCE + "..refs/heads/j71b-orchard-export-review")
run("git", "-C", orchard, "bundle", "verify", orchard_bundle)

# Preserve the complete export, not just the four patches.
files = []
for path in expected_paths:
    target = out / "files" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(orchard / path, target)
    files.append({"path": path, "blob": git(orchard, "rev-parse", candidate + ":" + path),
                  "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
source_history = []
for sha in [base] + source_commits + [source_tip, roundtrip]:
    source_history.append({"sha": sha, "commit": git(linux, "cat-file", "commit", sha)})
(out / "kernel-commit-lineage.json").write_text(json.dumps(source_history, indent=2) + "\n")
receipt = {"orchard_base": SOURCE, "input_candidate": CANDIDATE,
           "kernel_base": base, "kernel_candidate": source_tip,
           "kernel_tree": git(linux, "rev-parse", source_tip + "^{tree}"),
           "kernel_roundtrip": roundtrip,
           "kernel_roundtrip_tree": git(linux, "rev-parse", roundtrip + "^{tree}"),
           "kernel_bundle_prerequisite": upstream,
           "kernel_bundle_restoration_verified": True,
           "orchard_validation_commits": validation_commits,
           "orchard_validation_tip": candidate, "orchard_tree": tree,
           "files": files, "generated_patches": generated,
           "production_equal_linux": LINUX_SOURCE,
           "upstream_patches_unchanged": True, "configs_exact_delta": True,
           "host_tests_passed": True, "series_roundtrip_passed": True,
           "image_built": False, "device_tested": False,
           "export_command": [str(x) for x in export_command]}
(out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
(out / "README.txt").write_text(
    "J71b documented export for Orchard review\n\n"
    "This artifact contains all 11 candidate files under files/, the exact "
    "export receipt, kernel commit metadata, and two Git bundles. No ref was "
    "pushed, no PR was created, and no image/device test was performed.\n\n"
    "Kernel bundle prerequisite: fetch " + upstream["commit"] + " from "
    + upstream["url"] + ". Then git bundle verify kernel-source.bundle and "
    "git fetch kernel-source.bundle refs/heads/j71b-power-export:refs/heads/j71b-power-export. "
    "The bundle also retains the regenerated final main for round-trip inspection.\n\n"
    "Orchard bundle prerequisite: fetch " + SOURCE + " from "
    "https://github.com/OrchardLinux/orchard.git. Then git bundle verify "
    "orchard-export-review.bundle and git fetch orchard-export-review.bundle "
    "refs/heads/j71b-orchard-export-review:refs/heads/j71b-orchard-export-review.\n\n"
    "The three Orchard commits here are validation history only. Any final "
    "submission history must use exactly the recorded blobs/tree, preserve the "
    "logical split, and disclose its own SHA. Exact-revision image and device "
    "testing remain outstanding.\n")
manifest = []
for path in sorted(out.rglob("*")):
    if path.is_file():
        manifest.append(hashlib.sha256(path.read_bytes()).hexdigest()
                        + "  " + str(path.relative_to(out)))
(out / "SHA256SUMS").write_text("\n".join(manifest) + "\n")
print("EXPORT_RECEIPT " + json.dumps(receipt), flush=True)
for item in files:
    print("EXPORT_FILE " + json.dumps({**item,
        "content": (orchard / item["path"]).read_text()}), flush=True)
run("git", "-C", orchard, "diff", "--stat", SOURCE, candidate)
print("Documented export, series round trip, bundle restoration and host tests passed. "
      "No kernel/image build or device access was performed.", flush=True)

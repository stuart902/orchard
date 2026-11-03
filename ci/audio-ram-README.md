# J71b audio RAM check, November 3

For iPad 6 Wi-Fi (iPad7,5 / J71b / A1893 / T8010), apple-16k only.

This packages Linux draft PR #2 at 4d80a6b183d51565d442f745ea5e95160107e032:
upstream playback support plus the SmartIO submit/STOP ordering fix. It is not
microphone support, a volume fix, a desktop installation, or a hardware-tested
release. Existing loudness concerns remain. **Do not start playback with this
image.** Nothing plays or records automatically.

The payload is Orchard's unchanged hardware-check example: RAM-only, NVMe
read-only fencing, USB SSH and serial. USB serial exposes an unauthenticated root
shell: connect only to your trusted Mac. No installer or partitioning is involved.
Firmware is added from Apple's restore image by Orchard on your Mac, using its
private cache when available. Apple firmware is not in this download.

## Prepare on the Mac

Extract `j71b-audio-ram-nov3.tar.gz`. In Terminal, change into its `orchard`
directory. Use that checkout's launcher, not the `orchard` command on PATH.
Existing Orchard prerequisites (uv, libusb and palera1n) are needed. The launcher
may prepare a local Python environment through uv; it does not change the iPad.

```sh
./bin/orchard python ci/prepare-audio-ram.py
```

This verifies the immutable bundle and repacks the already-compiled kernel,
modules, loader and tools with the standard Orchard RAM assembler. It does not
compile a kernel, use Podman, contact the device or install anything on it. The
brief local repack records your extraction path for Orchard's firmware layer and
adds your Mac's Orchard RAM SSH public key. Private keys stay on the host.

When ready for one boot attempt, connect this iPad in DFU and run:

```sh
./bin/orchard run examples/hardware-check --no-build
```

Confirm only if Orchard identifies J71b. Do not override a device mismatch.
Do not repeat the boot automatically if its outcome is uncertain.

## Inspect without playback

From a second Mac terminal in this same `orchard` directory:

```sh
./bin/orchard exec -- /bin/busybox timeout -k 2 15 /bin/busybox sh -c 'uname -r; cat /proc/asound/cards; cat /proc/asound/pcm; dmesg | tail -n 100'
```

For a bounded touchscreen check, touch the screen while this runs:

```sh
./bin/orchard exec -- /bin/busybox timeout -k 2 35 /usr/bin/hardware-check touch
```

Send the output. ALSA card enumeration is not proof that playback or recording
works. No microphone test is expected to succeed from this change. A full audio
test image remains separate work.

## Finish the test

After saving the output, leave the RAM test by holding the iPad's Home and top
buttons together until the Apple logo appears, then release them. This is
[Apple's force-restart sequence for an iPad with a Home button](https://support.apple.com/en-us/102642).
No installed filesystem is mounted in this test. Do not select Restore in Finder.
Let iPadOS start and charge normally, or shut it down from iPadOS; do not leave
it sitting in recovery/DFU overnight. A dark panel alone does not prove power-off.
If the expected restart does not happen, stop and report what the device shows.

Source revisions, input CI runs and artifact SHA-256 digests are recorded in
`audio-test-provenance.json`. Matching Linux source is supplied separately as
`kernel-source-apple-16k.tar.gz`; Orchard source is included in `orchard/`.

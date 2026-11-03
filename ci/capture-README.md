# Experimental J71b microphone RAM test

Only for iPad 6 Wi-Fi, iPad7,5 / J71b / A1893 / T8010.

This uses Linux c40e165367f58182881c461cdbabdc0d1ff57e18. It is an experimental microphone test, not a desktop installation or an upstream-ready driver. The existing speaker path is unchanged; do not start playback. Nothing records or plays automatically.

The experiment assumes Linux is the only host high-power PDM requester. Firmware-wide exclusivity is not proven. A firmware or DMA ownership failure can permanently block capture close, suspend or shutdown until a physical reset. A timeout cannot guarantee killing a task blocked in the kernel. Do not retry capture, unload drivers or unbind devices after a hang.

The standard hardware-check payload runs in RAM and fences NVMe read-only. No installed filesystem is mounted. USB serial exposes an unauthenticated root shell: use only your trusted Mac. Capture output is saved in RAM, not to the installed disk.

Apple firmware and factory calibration are not distributed. Orchard adds firmware privately from its existing J71b recipe and host cache when booting. The driver reads calibration from the live ADT already exposed by the unchanged bootloader.

## Prepare on the Mac

First extract the downloaded GitHub artifact ZIP. It contains the runtime `j71b-capture-experiment-nov3.tar.gz` plus separate source archives. In Finder, create `j71b-capture-experiment-nov3` in Downloads and extract that named runtime tar.gz into the folder, so it contains `orchard/`. Do not use one of the source archives. In Mac Terminal, run:

```sh
cd "$HOME/Downloads/j71b-capture-experiment-nov3/orchard"
./bin/orchard python ci/prepare-capture-ram.py
```

This verifies bundle checksums and repacks precompiled components with the standard assembler. It does not compile a kernel, use Podman or access the iPad. It records the extraction path and includes the Mac's Orchard RAM SSH public key; private keys stay on the host. Existing uv, libusb and palera1n prerequisites are required. The launcher may prepare its local Python environment through uv. Use this checkout's launcher, not the global orchard command.

When ready for one boot attempt, connect this iPad in DFU:

```sh
./bin/orchard run examples/hardware-check --no-build
```

Confirm only if Orchard identifies J71b. Do not override a mismatch or repeat an uncertain boot.

## First inspect, without recording

In a second Mac terminal, in the same `orchard` directory:

```sh
./bin/orchard exec -- /bin/busybox timeout -k 2 15 /bin/busybox sh -c 'uname -r; cat /proc/asound/cards; cat /proc/asound/pcm; cat /proc/mtd; arecord -l; dmesg | tail -n 150'
```

Save and review that output before capture. Confirm a `J71b Microphones` capture device, the live `adt` MTD and successful AOP/SmartIO/PDM initialization. A card appearing alone does not prove recording works. Stop on a probe, firmware, DMA or clock error.

## One explicitly requested capture

Only after the first inspection is accepted, open the RAM shell from the Mac:

```sh
./bin/orchard shell
```

Inside the iPad RAM shell, select the card by its full name and request one ten-second recording. This stops if that name is missing or ambiguous:

```sh
card=$(awk '/: simple-card - J71b Microphones$/ { sub(/^[^[]*\[/, ""); sub(/\].*$/, ""); gsub(/[[:space:]]/, ""); print }' /proc/asound/cards)
if [ -n "$card" ] && [ "$(printf '%s\n' "$card" | wc -l)" -eq 1 ]; then
    timeout -k 2 20 arecord -D "hw:CARD=$card,DEV=0" -f S16_LE -c 2 -r 48000 -d 10 /run/j71b-mic.wav
else
    echo "Expected exactly one J71b Microphones card; no recording started."
fi
```

Speak briefly or tap near each microphone during the recording. Do not play the recording on the iPad. If the command hangs or fails, do not rerun it. Save available kernel output from a separate connection and use a physical reset if necessary.

After a normal completion, inspect `ls -l /run/j71b-mic.wav`, `/proc/asound/card*/pcm*c/sub*/status` and `dmesg`. In a separate Mac terminal, retrieve the recording and kernel log before restarting:

```sh
cd "$HOME/Downloads/j71b-capture-experiment-nov3/orchard"
./bin/orchard pull /run/j71b-mic.wav "$HOME/Downloads/j71b-mic.wav"
./bin/orchard exec -- dmesg > "$HOME/Downloads/j71b-capture-dmesg.txt"
```

RAM files disappear on reboot. Audio quality, channel separation, clean stop and repeatability remain tests, not assumptions.

## Finish

Save the output first. Hold Home and the top button together until the Apple logo appears, then release them. This is Apple's force-restart sequence for an iPad with a Home button. Do not choose Restore in Finder. Let iPadOS start and charge normally; do not leave the device in DFU or recovery overnight. A dark screen alone does not prove power-off.

The package contains source revisions and build provenance in `capture-test-provenance.json`. Corresponding Linux and capture-userspace sources are supplied alongside it. Orchard source is included in `orchard/`.

J71b one-shot speaker diagnostic components

Build-only candidate for iPad7,5 / J71b / T8010. This is not an installer,
production release, authorization to boot or play audio, or hardware-qualified
speaker support. Keep the installed microphone image unchanged.

Linux aaa2a29a93afe6fea3dbe70cb246642e525b210c extends the unchanged #20 audio
baseline 1b79f24831f78722e6c5fd205bc06646dd920b32, based on Orchard 79df400.
No later power or suspend changes are included. Expected full kernel release:
7.3.0-rc1-j71b-speaker-window-nov7-r1-orchard-apple-16k.

Normal TDM speaker topology is enabled, but the diagnostic codec defaults to
unarmed and muted on J71b. This package includes no arming configuration or
playback command. Explicit load-time arming, device access, each boot and any
playback require separate approval. Do not automatically reload, rebind, retry,
record or use desktop audio. Do not mix this kernel, DTB or modules with the
installed speaker-disabled microphone image.

The one module-lifetime START allowance requests GPIO-low at a 30 ms monotonic
software deadline. It does not stop MCA/DMA and is not a physical cutoff,
calibrated protection, hard real-time guarantee or proof of acoustic safety.
Read diagnostic-source-notes.rst for admission, teardown and fault limits.
Microphone source remains unchanged and experimental; uncertain DMA ownership
may block teardown. A userspace timeout does not make reset/shutdown safe.

Verify SHA256SUMS and read integration-receipt.json and reuse-receipt.json.
The full 16K build includes its modules and DTBs. The accompanying 4K checks
cover resolved configuration, selected objects and J71b DTB, not a full kernel.
Source/callback tests and native compilation do not establish boot, mapping,
volume, physical mute, timer latency, touch coexistence or cleanup acceptance.

Sources and exact reused loader/tool provenance are included. No private Apple
firmware, calibration, recording or device identifier is packaged. This build
performs no device operation, root rebuild, reinstall or release publication.

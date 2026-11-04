J71b current-upstream microphone test components

Build-only candidate for iPad7,5 / J71b / A1893 / T8010. This is not an installer,
production release or hardware-qualified image. The separate desktop assembly
must verify the same kernel, modules and DTB before any authorized device test.

The underlying current Orchard TDM speaker source is preserved. This temporary
variant disables /sound and MCA2 before desktop startup. That is a software
playback gate, not proven physical amplifier isolation. Microphones remain
experimental: an ownership/firmware/DMA fault can block teardown indefinitely.
After a fault, do not repeat capture, unload/unbind, or software reboot/shutdown.
A process timeout cannot make teardown safe; physical reset may be necessary.

Read integration-receipt.json and reuse-receipt.json for exact source and input
identity. Verify SHA256SUMS before use. The 4K artifact is focused object/config
coverage, not a full 4K kernel. Native compilation and mock tests are distinct
from boot, routing, cleanup, suspend/resume or playback acceptance.

No private Apple firmware, calibration, recording or device identifier is
included. No device operation or release publication is performed by this CI.

# J71b combined power and microphone candidate

Build-only integration for iPad7,5 / J71b / A1893 / T8010. This is a complete native 16K kernel, module and DTB component bundle, not an installer or hardware-qualified release. The desktop and menu are separately assembled from their existing pinned sources. No device access, boot, installation or playback is part of this workflow.

## Source and configuration

The exact Linux source is 38939748c8eba9c3331bfc6b5ac22c72e217499a. It combines:

- Final D2365 power source 778174c50d5fd6b36849f9eea728a6811b1b6e9e, including supplier lifetimes and scoped GPIO quiescing, unchanged.
- Recorded microphone candidate c410dc9c3f61fa12ca54c8fbf77f3e182e4e8d5f, including live ADT calibration, AOP/SmartIO integration and MCA error handling, unchanged.
- Every other source file from final-power Orchard a68aae672613176d203d4a3823f03f929bc84f5c, whose exact patched kernel tree is 317bf8b7f76b780cd5b74d4463718d2e9efe77cb. The source audit reverses only the declared audio, selftest and generated-config delta and must reproduce that entire tree hash.

Resolved configuration must equal the final power configuration with only three audio modules enabled (APPLE_AOP_AUDIO, SND_SOC_APPLE_T8010_PDM, SND_SOC_DMIC) and CONFIG_LOCALVERSION set to -j71b-power-mic-nov4-r1. Production RTC_SYSTOHC, NVME_APPLE and UDMABUF settings are preserved. Expected runtime release: 7.3.0-rc1-j71b-power-mic-nov4-r1-orchard-apple-16k. Receipts record the actual release and hashes of all modules, image and J71b DTB.

## Safety and qualification boundary

J71b /sound and MCA2 remain disabled in the actual packaged DTB. This is a software playback gate, not proof of physical amplifier isolation. No DSP, microphone gain, processing profile or new kernel ABI is included.

PDM ownership and teardown remain experimental. A firmware, transport or ownership fault may permanently block close, suspend or shutdown while retaining resources. A process timeout cannot safely resolve this. Do not retry recording, unbind drivers, unload modules or assume reset succeeded after a fault. No broader lifetime or hardware-gain qualification is claimed.

The four observed conditions of the installed final power-only image do not establish this combined kernel's hardware behavior. Independent controlled device qualification remains necessary and requires separate authorization.

## Reuse and provenance

Boot tools, m1n1 and Pongo are reused from exact successful final-power run 41734585711, artifact 13278797723, after ZIP digest, per-file receipt and recipe identity checks. The workflow builds only the changed kernel and its modules/DTBs. Corresponding source archives and original reuse receipts accompany the bundle. Private Apple firmware and user recordings are not included.

The full build runs the unchanged Orchard producer through this checkout's launcher and verifies RAM payload assembly without accessing hardware. It validates power built-ins and DT supply phandle, capture modules and alias/dependency closure, playback-disable gates, release/vermagic and exact configuration. DT compilation is not a claim of schema-clean device trees. This is not a production release and does not change normal branches or defaults.

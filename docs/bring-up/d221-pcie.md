# iPhone X (d221) A11 PCIe topology

The A11 (`t8015`) has a PCIe host bridge and Wi-Fi that no current device in
this repository describes. This file records the controller and DART topology
read from a physical iPhone X's runtime ADT (see `d221-bringup.md`), so the
driver and device-tree work has a single source. It mirrors what the T8010
PCIe bring-up did, but the A11 layout differs from it in several places.

The values below are from the runtime ADT of one `iPhone10,6` (`d221`),
firmware `iBoot-8422.142.2.700.1`. The property and node names used in this
file (`rc`, `phy`, `phy-ip`, `portN`) follow the driver and this
repository; they are not ADT properties, which are unnamed.

## Host bridge (`apcie`)

| Field | Value |
| --- | --- |
| `compatible` | `apcie,t8015` in the ADT; `apple,t8015-pcie` in the device tree |
| config | `0x610000000` (0x1000000) |
| `rc` | `0x600000000` (0x50000) |
| `phy` | `0x600080000` (0x4000) |
| `phy-ip` | `0x6000c0000` (0x40000) |
| port regs | `0x60N000000`, N = 1..4, each 0x4000 |
| interrupts (SPI) | 340, 343, 346, 349 (ports 0–3) |
| `clock-gates` | 56, 57, 58 |
| `power-gates` | 56 |
| MSI | address `0xbffff000`, vector offset 352 |
| `perst-to-refclk-delay-us` | 60 |

The ADT also lists a 0x4000 window at `0x60N004000` next to each port's
register block. Nothing identifies it: the ADT entries are unnamed and
"nvmmu" does not occur in the iOS 16.7 d221 kernelcache. The device tree
leaves it out until something uses it.

The ADT also carries the SoC tunables this controller needs:
`apcie-common-tunables`, `apcie-phy-tunables`, and per-bridge
`apcie-config-tunables` / `pcie-rc-tunables`. These are the A11-specific
PHY/config register programs; they are not transcribed here, and the h9p
driver's T8015 match data arrives with this series' `PCI: apple-h9p: Add T8015 support` patch.

## Wi-Fi port (pci-bridge3)

| Field | Value |
| --- | --- |
| `apcie-port` | 3 |
| `maximum-link-speed` | 2 |
| `msi-vector-base` | 24 |
| `function-clkreq` | GPIO 0xa3 |
| `function-device_wake` | GPIO 0x28 |
| `function-perst` | GPIO 0xa7 |
| endpoint | `wlan-pcie,bcm4357` (the `herculesk` module, see the d221 recipe), iommu-parent = the `dart-apcie3` mapper |

Bus numbering follows from what the driver does at runtime, not from the ADT:
it hides ports that are not enabled and the host bridge renumbers buses, so
with only port 3 enabled this port comes up as bus 1 and the endpoint's
requester ID is `0x100`. The board `iommu-map` entry uses that ID.

## DARTs

Both are siblings of the controller in the ADT, `compatible =
"apple,t8015-dart", "apple,s5l8960x-dart"`, page size 4096, `dart-options 7`,
`error-reflector 0x233ffc000`, `stt-idx-width 10`, `fetch-config 0xe0303`
and `diag-config 0x80000100` (the `0x80000100` differs from the `0x00000100`
of the s5l8960x, t7001 and s8003 DARTs).

The ADT `vm-offset` is `0x0800000080000000` and `vm-size` is `0x3ffff000`.
The board `iommu-map` uses a `0x80000000` aperture of `0x3ffff000` bytes,
the same pair the other Apple boards use; the meaning of bit 59 in
`vm-offset` is not established here.

| DART | reg | interrupt (SPI) | mapper |
| --- | --- | --- | --- |
| `dart-apcie2` | `0x603008000` | 347 | `mapper-apcie2` |
| `dart-apcie3` | `0x604008000` | 350 | `mapper-apcie3` (the Wi-Fi's iommu-parent) |

## Link bring-up

On one `d221` (kernel `7.3.0-rc1-orchard-apple-16k`), port 3 trains to L0
(LTSSM `0x11`, in 102 ms) and the endpoint enumerates as `0000:01:00.0`
`14e4:440a` (BCM4357) at 5.0 GT/s x1, behind root port `0000:00:03.0`
`106b:100a`. `link_present` reads 0 throughout; `BIT(3)` of LINKSTS is a
T8015 card-detect semantic, not a failure. The SMC `gP0e` rail is active-high.

## What remains for a working Wi-Fi port

1. Host wake: the endpoint's host-wake interrupt, alongside the
   `device-wake` line in the table above.
2. brcmfmac has no BCM4357 (`14e4:440a`) entry, so the Wi-Fi driver side is
   still missing; that is a linux-wireless topic and does not block the PCIe
   series.
3. DMA translation for the Wi-Fi port: at probe, `apple-dart 604008000.iommu`
   reports `translation setup for streams 1 failed: -5` and `blocking DMA for
   streams 1`, with an `iommu_setup_default_domain` warning from
   `apple_h9p_pcie_probe`. Enumeration is not affected, but the endpoint has
   no working DMA mapping, so this has to be fixed before brcmfmac can run
   (seen on a d221 with the series at a538a0f).

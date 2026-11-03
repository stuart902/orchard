# Diagnostic-only D2365 supplier lifecycle test

This branch is not a release or production patch export. The workflow boots the
exact unmodified Linux 778174c poweroff and GPIO drivers in ARM64 QEMU, with
KASAN, lockdep, DEBUG_ATOMIC_SLEEP and SMP. It adds a standalone KUnit fixture
and Kconfig/Makefile integration only in the CI checkout.

The fixture uses real OF nodes, platform drivers, device links, devres, a
registered power_supply and the kernel irq_sim framework. A RAM-backed regmap
and synthetic supply provide only the resources needed for actual driver
probe/removal. They are not a physical PMIC emulator. No shutdown, reboot,
standby, I2C timing or electrical behavior is tested.

Checks:
- Three supply unbind/rebind cycles and one real GPIO unbind/rebind cycle in
  both fw_devlink=off and permissive modes.
- Real devres tracepoint assertions: three sys-off handlers are released
  before the power-supply reference and the two supplier references.
- Supplier removal sees the consumer unbound and the supply use count back at
  its registration reference, before managed supplier data is freed.
- A separate linked blocker pauses real supplier removal. The target supplier
  is still driver-bound but its real device-link state is UNBINDING. Actual
  poweroff probe must reject that window, unwind its provider references, and
  bind successfully after supplier restoration.
- Exact supply-helper rejection is checked with fw_devlink=off. Permissive
  firmware links can instead defer in the core or protect an in-flight probe,
  so the fixture does not impose the off-mode supply-race expectation there.
  The GPIO-helper race runs in both modes.
- Tracepoint action names prove real helper/probe execution, not just an errno
  from a driver-core precheck.
- No access to standby or boot bookkeeping registers is allowed.

A passing run proves these kernel lifecycle scenarios with synthetic providers.
It does not replace hardware shutdown evidence, test the real Tristar driver's
remove path, or prove every concurrent interleaving.

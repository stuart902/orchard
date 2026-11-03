# Suspend (s2idle): what a board needs and how to prove it

How Linux suspend-to-idle was made to work on the iPad 6 (J71b, T8010) on
2026-11-04, and how to repeat it on another board. The evidence log is
`examples/suspend-check/RESULT.md` (local, not committed).

## What suspend needs on these SoCs

Linux suspends to idle (`/sys/power/mem_sleep` = `[s2idle]`): user space
freezes, drivers suspend, the CPUs idle until a wake interrupt. There is no
firmware sleep state. Three things must hold on every board:

1. **A wake source that survives.** The Power and Home buttons wake through
   the AP GPIO controller (`gpio-keys`, wake enabled). If PMGR powers the GPIO
   domain down, no wake interrupt arrives.
2. **Nothing that cannot come back loses power.** Today the display pipe
   (adopted from iBoot: timings and panel link the driver cannot program from
   scratch) and the GPU (firmware state the driver cannot restore yet) must
   keep their domains. Without that, the deeper PM tests leave the screen
   blank, or rendering dead after wake.
3. **No driver touches suspended hardware.** Periodic work must stop between
   the freezer and resume: queue it on `system_freezable_wq`, or cancel it in
   the driver's suspend callback. Buses without `dev_pm_ops` for their
   devices (1-Wire/HDQ, for instance) only have the first option.

## T8010 (A10) as done

All in the kernel, nothing in user space:

| What | Where | Why |
|---|---|---|
| `ps_gpio` always-on, manual PM | `t8010-pmgr.dtsi` | button wake |
| `ps_disp0_fe`, `ps_disp0_be` always-on, manual PM | `t8010-pmgr.dtsi` | adopted display pipe |
| `ps_dp` (iPads) / `ps_mipi_dsi` (iPhones, iPod) | `t8010-ipad6.dtsi` / `t8010-7.dtsi`, `t8010-n112.dts` | the panel link each family drives |
| `ps_gfx` always-on, manual PM | `t8010-pmgr.dtsi` | GPU firmware state |
| bq27xxx poll on `system_freezable_wq` | `drivers/power/supply/bq27xxx_battery.c` | the HDQ gauge poll reset the SoC in sleep |

`apple,always-on` keeps a domain on while awake too, so this keeps state
instead of saving power in suspend; the GPU domain stays on even when the
system renders in software. Each entry goes once its driver saves and
restores its own state. Sleep current has not been measured.

The gauge bug is general: on every HDQ gauge (iPad 5, 6, 7, Air 2) the poll
kept running into suspend and touched the suspended 1-Wire UART. The default
poll of 360 s rarely collides; orchard's `30-orchard-battery-poll.conf` sets
10 s, and then every sleep reset the tablet within 5 to 15 seconds.

## Bringing up another board

1. **Domains.** In the board's DT, find the domain of the GPIO controller the
   buttons use, the `power-domains` of the display node (front end, back end,
   panel link) and the GPU's. Same SoC family: the T8010 entries above apply
   as they are; another SoC needs its own, in its `-pmgr.dtsi` (shared) or the
   family `.dtsi` (panel link).
2. **Pollers.** Check the board's drivers for delayed work that requeues itself
   on a non-freezable workqueue (`system_wq`, `system_percpu_wq`,
   `schedule_delayed_work`). Gauges, chargers and sensors are the usual ones.
3. **Test in RAM first**, with `examples/suspend-check` or an equivalent
   `/init`: `pm_test=devices`, then `pm_test=platform`, then one real sleep.
   Load the board's drivers one at a time between real sleeps.
4. **Then the installed system**, with its default services and settings.
5. **Mark the feature**: `[features] suspend = "working"` in the board's
   `device.toml`, with the evidence (boot ID, sleep length, wake IRQ) in the
   change.

## Testing rules that mattered

- **Wait at least 45 s before pressing Power**, timed. Failures can take 5 to
  15 s; a sleep that is woken early proves nothing.
- **Launch detached** (`setsid … &` with a short delay): USB disappears in
  sleep, and a dropped SSH session must not look like a failed command.
- **A pass** is the same boot ID after wake, `pm_wakeup_irq` naming the button
  interrupt, `suspend_stats/fail` unchanged, and the user seeing the screen
  return. printk times across s2idle are wall time.
- **Split, don't toggle.** When one configuration passes and another fails,
  swap halves (boot path, command line, user space, udev, kernel settings)
  instead of disabling services one at a time. On J71b, six such splits found
  the gauge poll after a day of single-service toggles had not.
- **Keep helpers and their output apart:** a helper copied to the path of its
  own output directory fails before any test.

## Enabling it in an installed system

Whether a board can suspend is device data, not a distribution's choice:
`[features] suspend` in the board's `device.toml`. orchard's platform layer
turns it into the installed system's sleep configuration:

- `usr/lib/orchard/suspend-boards` lists the device-tree compatibles of the
  platform's boards whose suspend is `working`, generated when the layer is
  built (`orchard.image.platform`).
- At boot, `orchard-sleep.service` (pulled in by
  `orchard-sleep-generator`) runs `usr/lib/orchard/orchard-sleep`, which
  compares `/proc/device-tree/compatible` with that list and writes
  `/run/systemd/sleep.conf.d/50-orchard-board.conf` with `AllowSuspend=yes`
  or `AllowSuspend=no`. Every board that is not `working`, `untested` ones
  included, cannot be put to sleep by accident.

A new device state arrives with the next platform layer; nothing is
reinstalled. Distributions keep the policy: when to suspend (Power key,
idle) and locking first. They must not set `AllowSuspend` themselves; a
drop-in that sorts after `50-orchard-board.conf` would override the board's
decision. omarchy-a asks logind (`CanSuspend`) before it suspends.

To enable a board: prove it as above, set `suspend = "working"`, and the
next release allows it.

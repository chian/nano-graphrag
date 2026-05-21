# Remote Demo Host Runbook

Date: 2026-05-21

Purpose: preserve machine-specific continuity notes in-repo so a new session can
resume quickly after a reboot, crash, or loss of local agent state.

## Current host state

- Active OS is Ubuntu 24.04 on the current SATA install.
- Tailscale is up and the node is reachable.
- Wi-Fi autoconnect was corrected after a GPU-related hardware change forced the
  host onto integrated graphics and a different Wi-Fi interface name.
- The wireless regulatory domain is pinned to `US` via
  `/etc/modprobe.d/cfg80211-regdom.conf`.

## Boot-chain findings

- The active EFI/system root is the current Ubuntu install on the SATA disk.
- An older Linux Mint install still exists on the NVMe disk.
- GRUB currently generates Mint menu entries because `os-prober` sees the old
  NVMe root.
- UEFI also has a stale Ubuntu boot entry that points at the old NVMe EFI
  partition.

## Recommended next actions

1. Disable `os-prober` and regenerate GRUB so Mint no longer appears in the boot
   menu and GRUB returns to hidden fast boot.
2. Remove the stale UEFI boot entry that points to the old NVMe EFI partition.
3. Keep one previous Ubuntu kernel as rollback, but avoid accumulating more old
   kernel entries than necessary.
4. In firmware/BIOS, set power restore behavior to `Always On` so a physical
   power cycle can bring the host back without manual intervention.
5. Prefer wired Ethernet for the remote demo if feasible; the current ath12k
   Wi-Fi path is working, but Ethernet is the lower-risk transport for a
   headless recovery scenario.

## Notes for future sessions

- Avoid storing secrets in this file. Use it for operational breadcrumbs only.
- If the machine reboots into the wrong OS, inspect UEFI boot order first, then
  compare EFI partitions before modifying GRUB.

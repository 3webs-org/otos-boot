# otos-boot

A tiny, purpose-built bootloader for booting
[otos-coreinit](https://github.com/3webs-org/otos-coreinit)'s Mach-O-wrapped
kernel (`saski`) and init (`coreinit`) images on a known, fixed target --
formalizing what [`otos-coreinit/tools/mkstub.py`](https://github.com/3webs-org/otos-coreinit/blob/main/tools/mkstub.py)
does today (wrap a flat kernel image in a minimal EFI application that
copies it to its link address, drops the MMU, and jumps) into a real
bootloader project rather than a Python wrapper script.

## Relationship to otos-grub

[`otos-grub`](https://github.com/3webs-org/otos-grub) and this project
are two independent implementations of the *same* boot protocol (see that
repo's README for the protocol itself), not two different protocols:

- **otos-grub** parses firmware's machine description (DT or ACPI) and
  the kernel/init Mach-O images *at runtime*, because it's loaded by a
  generic, pre-existing GRUB installation that doesn't know ahead of time
  what it's booting.
- **otos-boot** does none of that parsing at runtime -- the
  machine-description object is baked in **at compile time**, since an
  embedded target's hardware is known ahead of time. This is one project
  covering multiple targets, not "EFI vs. bare metal" as separate things:
  an EFI build (what `mkstub.py` does today) is one target of it; a
  genuinely bare-metal board is another target of the same project, using
  the same compile-time-fixed-description approach.

Both hand the kernel the identical five values (a real FDT for
standard-protocol compatibility on aarch64, the two opaque Cap'n Proto
object pointers, the SaskiBootParams pointer, and the resolved entry
point) -- so `saski`'s kernel has exactly one receiving code path
regardless of which bootloader got it there. The full contract,
including the exact register mapping per architecture, is defined in
[`include/boot_protocol.h`](include/boot_protocol.h), vendored here
from [`otos-coreinit`](https://github.com/3webs-org/otos-coreinit), the
canonical owner -- see `otos-grub`'s README for a summary of the same
header, which applies here identically since both projects implement
one shared wire format. `include/capnp_list.h` is the matching
encoder (`capnp_build_list_root`) for the two real Cap'n Proto objects
(MachineDescription, InitDescription) -- same file, same reasoning as
`otos-grub`'s copy.

## Status: design stage, not yet implemented

This repository is currently scaffolding only -- the protocol contract
above is resolved and vendored, but nothing here yet actually builds a
real MachineDescription for a specific board, or implements the EFI or
bare-metal entry stub that would use it. That implementation is the
next step, not done here.

Additional open questions specific to this project, not yet resolved:
- How the compile-time machine-description object is actually produced
  for a given target board (by hand, or generated from some simpler
  per-board description).
- The exact boundary between the EFI target and a genuinely bare-metal
  target -- how much of the loader logic (Mach-O segment placement, entry
  resolution) is shared code with only the entry stub and memory-map
  discovery differing per target.

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

Both hand the kernel the identical four values (a real FDT for standard-
protocol compatibility, the two opaque Cap'n Proto object pointers, and
the resolved entry point) -- so `saski`'s kernel has exactly one receiving
code path regardless of which bootloader got it there.

## Status: design stage, not yet implemented

This repository is currently scaffolding only. See `otos-grub`'s README
for what's shared and still undecided (the Cap'n Proto schema field
lists, which repo hosts them, the Mach-O entry-point convention, x86_64's
register mapping) -- all of that applies here identically, since both
projects must agree on the same wire format.

Additional open questions specific to this project, not yet resolved:
- How the compile-time machine-description object is actually produced
  for a given target board (by hand, or generated from some simpler
  per-board description).
- The exact boundary between the EFI target and a genuinely bare-metal
  target -- how much of the loader logic (Mach-O segment placement, entry
  resolution) is shared code with only the entry stub and memory-map
  discovery differing per target.

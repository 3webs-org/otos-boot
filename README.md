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

## Status: one real, working target -- aarch64 QEMU virt EFI

`tools/build-stub.py` builds a complete, tested EFI stub for exactly
the target `saski/tools/qemu-boot-aarch64.sh` already exercises
(QEMU's `virt` machine, GICv3, AAVMF firmware), verified end to end:
boots real AAVMF, copies saski's own kernel image and coreinit's
*real* Mach-O (flattened by `tools/macho_flatten.py` -- actual
`LC_SEGMENT_64`/`LC_MAIN` parsing, not a placeholder) to their link
addresses, builds and places real `MachineDescription`/
`InitDescription`/`SaskiBootParams` objects (QEMU virt's own real
memory map -- UART `0x9000000`, GICv3 distributor `0x8000000`,
redistributor region `0x80a0000`/`0xf60000`, PSCI method `hvc` --
verified against QEMU's own DTB output, not recalled from memory),
turns the MMU off, and jumps to saski's new `boot_protocol_start`
entry point, which jumps to coreinit directly with no `macho_load`
call at all. coreinit boots to steady state -- every self-test
(job_exec, priority preemption, cross-core-signal, pagefault/COW)
passes.

What this specific target does NOT yet do: bring up more than the BSP
(the `MachineDescription` this build produces declares one core;
`SaskiBootParams`'s own AP pool is sized and reserved but nothing
bump-allocates from it yet -- that's saski's own side, scoped out of
this pass same as everywhere else in this project's boot-protocol
work), and `build-stub.py`'s own QEMU-virt field values are specific
to that one target, not yet generalized into a per-board description
format.

- `arch/aarch64/qemu_virt_stub.S` -- the stub itself, real assembly
  (not hand-encoded opcodes -- see the file's own top comment on why
  this diverges from `mkstub.py`'s original approach), assembled by a
  real toolchain. Three fixed destinations it copies to at runtime
  (its own position is firmware's choice, not fixed): saski's own
  kernel image, the three boot-protocol objects, and coreinit's
  flattened Mach-O.
- `tools/macho_flatten.py` -- reads a real Mach-O's `LC_SEGMENT_64`
  segments and `LC_MAIN` entry point into one flat, ready-to-copy
  image. The one piece of actual Mach-O parsing this protocol's
  loader side needs for coreinit, now that saski's own
  `boot_protocol_start` no longer calls `macho_load` itself.
  Excludes `__PAGEZERO` and `__LINKEDIT` by name (not by a filesize
  heuristic -- an earlier version of this function got that wrong:
  `__LINKEDIT` has a nonzero filesize too, and including it silently
  pulled symbol-table bytes into the runtime image as if they were
  BSS).
- `tools/encode_boot_protocol.py` -- Python port of
  `include/capnp_list.h`'s encoder. Cross-checked against
  otos-coreinit's own C decoder byte-for-byte
  (`tools/test_encode_boot_protocol.py`), not just internally
  self-consistent.
- `tools/build-stub.py` -- orchestrates all of the above into one
  `.efi` file. QEMU virt's own field values live here, not in the
  shared headers, since they're this one target's own facts, not part
  of the protocol.

Additional open questions specific to this project, not yet resolved:
- How the compile-time machine-description object is actually produced
  for a *different* target board (by hand, same as this one, or
  generated from some simpler per-board description) -- this repo has
  exactly one target so far, so there's no second data point yet to
  generalize from.
- The exact boundary between the EFI target and a genuinely bare-metal
  target -- how much of the loader logic (now proven out for EFI --
  `macho_flatten.py`, `encode_boot_protocol.py`, the three-destination
  copy pattern in `qemu_virt_stub.S`) is shared code with only the
  entry stub and memory-map discovery differing per target.
- Bringing up more than the BSP under this protocol (SaskiBootParams's
  own AP pool exists and is reserved on the coreinit side, but nothing
  allocates from it yet -- real, separate follow-on work).

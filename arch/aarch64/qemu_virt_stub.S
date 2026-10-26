/* SPDX-License-Identifier: 0BSD */
/*
 * otos-boot: aarch64 EFI stub for a known, fixed QEMU-virt target,
 * implementing the new boot protocol (see otos-coreinit's own
 * include/boot_protocol.h). Formalizes what saski/tools/mkstub.py did
 * as hand-encoded opcodes in a Python script into a real assembly
 * source, assembled by a real toolchain -- this repo's own README's
 * "a real bootloader project rather than a Python wrapper script."
 *
 * Entered by UEFI firmware per the standard AArch64 EFI calling
 * convention: x0 = EFI_HANDLE ImageHandle, x1 = EFI_SYSTEM_TABLE*
 * SystemTable. Neither is read further -- a real EFI config-table walk
 * for the DTB/machine description is a documented follow-up in
 * mkstub.py's own history, not done here either. This stub hardcodes
 * everything for its one known target, same as its predecessor did,
 * and likewise does NOT call ExitBootServices before taking over
 * hardware directly -- matching mkstub.py's own existing behavior
 * exactly, not a new gap this port introduces.
 *
 * Every fixed value below (KERNEL_DST, KERNEL_LEN, BPO_LEN, DTB_PHYS,
 * MD_DEST, ID_DEST, SBP_DEST, INIT_ENTRY, COREINIT_DEST, COREINIT_LEN,
 * BOOT_PROTOCOL_START) is supplied via -D by tools/build-stub.py at
 * assemble time -- see that script for where each one actually comes
 * from (smp_layout.h's own constants, the saski binary's own real
 * boot_protocol_start symbol address via nm, coreinit.macho's own
 * real LC_MAIN entry point and segment layout via
 * tools/macho_flatten.py, and both payload blobs' own real lengths).
 * Nothing here is a guess hardcoded twice in two languages; this file
 * only names the values, build-stub.py computes them. */

.text
.global _start
_start:
    /* Copy the embedded kernel image to its fixed destination -- same
     * reasoning as mkstub.py's own kernel copy: an EFI stub's own
     * load address is firmware's choice, not fixed, but the kernel's
     * own link address is. */
    adrp x9, kernel_data
    add  x9, x9, :lo12:kernel_data
    ldr  x10, =KERNEL_LEN
    ldr  x11, =KERNEL_DST
copy_kernel:
    cbz  x10, copy_kernel_done
    ldrb w13, [x9], #1
    strb w13, [x11], #1
    sub  x10, x10, #1
    b    copy_kernel
copy_kernel_done:

    /* Copy the embedded boot-protocol objects (MachineDescription +
     * InitDescription + SaskiBootParams, concatenated by
     * tools/build-stub.py in that order) to their own fixed
     * destination -- same reasoning, same technique, as the kernel
     * copy above: these need to still be valid memory once saski (at
     * a different address) reads them, so they cannot stay wherever
     * firmware happened to load this stub. */
    adrp x15, bpo_data
    add  x15, x15, :lo12:bpo_data
    ldr  x16, =BPO_LEN
    ldr  x17, =MD_DEST
copy_bpo:
    cbz  x16, copy_bpo_done
    ldrb w19, [x15], #1
    strb w19, [x17], #1
    sub  x16, x16, #1
    b    copy_bpo
copy_bpo_done:

    /* Copy coreinit's own flattened Mach-O image (tools/macho_flatten.py
     * + tools/build-stub.py: every loadable segment's file bytes,
     * BSS already zero-filled by build-stub.py into this same blob)
     * to coreinit's own link address. saski's boot_protocol_start no
     * longer calls macho_load at all (the whole point of this
     * protocol), so this stub -- not saski -- is what places coreinit
     * in memory, the same way it already places saski itself above. */
    adrp x24, coreinit_data
    add  x24, x24, :lo12:coreinit_data
    ldr  x25, =COREINIT_LEN
    ldr  x26, =COREINIT_DEST
copy_coreinit:
    cbz  x25, copy_coreinit_done
    ldrb w28, [x24], #1
    strb w28, [x26], #1
    sub  x25, x25, #1
    b    copy_coreinit
copy_coreinit_done:

    /* Turn the MMU off -- the kernel's own boot path expects to start
     * with it off, exactly as QEMU's -kernel delivers it. Same
     * instructions, same reasoning as mkstub.py's own MMU-off
     * sequence, just real mnemonics instead of hand-encoded opcodes. */
    mov  x20, #0x1005             /* mask M|C|I */
    mrs  x21, CurrentEL
    lsr  x21, x21, #2
    and  x21, x21, #3
    cmp  x21, #2
    b.ne use_el1
    mrs  x22, sctlr_el2
    bic  x22, x22, x20
    msr  sctlr_el2, x22
    b    mmu_off_done
use_el1:
    mrs  x22, sctlr_el1
    bic  x22, x22, x20
    msr  sctlr_el1, x22
mmu_off_done:
    dsb  sy
    isb
    ic   ialluis
    dsb  sy
    isb

    /* The new boot protocol's own five values (see
     * otos-coreinit/include/boot_protocol.h): x0 = DTB, x1 =
     * MachineDescription's own fixed destination, x2 =
     * InitDescription's, x3 = SaskiBootParams's, x4 = init's
     * already-resolved entry point. x6 holds the branch target
     * (saski's own boot_protocol_start) only as a scratch register --
     * it is not part of the protocol itself, which is why it is not
     * x0-x4. */
    ldr  x0, =DTB_PHYS
    ldr  x1, =MD_DEST
    ldr  x2, =ID_DEST
    ldr  x3, =SBP_DEST
    ldr  x4, =INIT_ENTRY
    ldr  x6, =BOOT_PROTOCOL_START
    br   x6

.balign 16
kernel_data:
.incbin KERNEL_BIN_PATH
.balign 16
bpo_data:
.incbin BPO_BIN_PATH
.balign 16
coreinit_data:
.incbin COREINIT_BIN_PATH

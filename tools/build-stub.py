#!/usr/bin/env python3
# SPDX-License-Identifier: 0BSD
"""Builds the otos-boot aarch64 QEMU-virt EFI stub: assembles
arch/aarch64/qemu_virt_stub.S with every fixed value (destinations,
lengths, the real boot_protocol_start/coreinit entry addresses) baked
in via -D, then wraps the result in a minimal PE32+ EFI container --
the exact same container-building code mkstub.py already used (struct
packing, not hand-assembled opcodes, so reused verbatim rather than
re-derived).

Inputs:
  - saski's own ELF link (build-aarch64/saski.macho, the pre-objcopy
    artifact -- this script runs the same "Extracting the flat binary
    image" llvm-objcopy -O binary step saski/CMakeLists.txt's own
    mkstub.py path does, rather than trusting a separately-built
    saski.bin to match; it also needs saski.macho's own symbol table
    to find boot_protocol_start's real address, which saski.bin, the
    objcopy'd flat image, no longer has at all).
  - otos-coreinit's coreinit.macho (a real Mach-O -- read directly via
    tools/macho_flatten.py, not pre-flattened by the caller, since
    THIS is the one place in this protocol something has to parse it).

Usage:
    python3 tools/build-stub.py <saski.macho> <coreinit.macho> <out.efi>

Environment (all optional, matching mkstub.py's own KERNEL_DST
convention):
  KERNEL_DST   saski's own link address (default 0x41000000, matching
               saski/CMakeLists.txt's own AARCH64_LOAD_BASE -- NOT
               mkstub.py's own stale docstring default of 0x40080000,
               which the real build overrides via this same env var
               and this script must match, not mkstub.py's comment)
  CC           assembler/linker driver (default: clang)
  NM, OBJCOPY  symbol lookup / ELF-to-binary tools (default: nm, llvm-objcopy)
"""
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from encode_boot_protocol import (
    build_boot_allocator,
    build_init_description, BOOT_PROTO_ARCH_AARCH64,
)
from macho_flatten import read_macho_image

HERE = os.path.dirname(os.path.abspath(__file__))
ARCH_SRC = os.path.join(HERE, "..", "arch", "aarch64", "qemu_virt_stub.S")

# ---- QEMU virt's own real memory map, verified against QEMU's actual
# DTB output (dumpdtb), not recalled from memory -- see the design
# notes this was checked against: UART at 0x9000000, GICv3 distributor
# at 0x8000000, redistributor region at 0x80a0000/size 0xf60000, PSCI
# method "hvc", RAM base 0x40000000. The generic timer's own frequency
# is read from CNTFRQ_EL0 directly (timer_freq_hz=0), not from the DT --
# QEMU virt's own timer node carries no clock-frequency property. ----
DTB_PHYS = 0x40000000
RAM_SIZE = 0x20000000  # matches qemu-boot-aarch64.sh's own "-m 512" default
UART_BASE = 0x9000000
GICD_BASE = 0x8000000
GICR_BASE = 0x80a0000
GICR_SIZE = 0xf60000
PSCI_USE_HVC = 1

# ---- otos-coreinit/include/smp_layout.h's BOOT_ALLOCATOR_REGION (aarch64)
# other cross-repo wire-shape constant in this project; see that
# header's own comment for why these specific addresses. ----
BOOT_ALLOCATOR_REGION_BASE = 0x41880000
BOOT_ALLOCATOR_REGION_LEN = 0x00110000
ALLOCATOR_SRC = os.path.join(HERE, "..", "include", "boot_allocator_aarch64.S")


def nm_symbol_address(binary_path, symbol):
    nm = os.environ.get("NM", "nm")
    out = subprocess.run([nm, binary_path], capture_output=True, text=True,
                         check=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1] == symbol:
            return int(parts[0], 16)
    raise ValueError(f"{binary_path}: symbol {symbol!r} not found via nm")


def main():
    if len(sys.argv) != 4:
        sys.exit(f"usage: {sys.argv[0]} <saski.macho> <coreinit.macho> <out.efi>")
    saski_macho_path, coreinit_macho_path, out_path = sys.argv[1:4]

    kernel_dst = int(os.environ.get("KERNEL_DST", "0x41000000"), 16)
    cc = os.environ.get("CC", "clang")
    objcopy_tool = os.environ.get("OBJCOPY", "llvm-objcopy")

    # boot_protocol_start is saski's own new entry point (see
    # arch/boot_aarch64.S there) -- looked up in the REAL binary this
    # build is actually using, never hardcoded, since its offset
    # shifts whenever saski's own source does. Must come from the ELF
    # (saski.macho), not the flat image below -- objcopy -O binary
    # strips the symbol table entirely.
    boot_protocol_start = nm_symbol_address(saski_macho_path, "boot_protocol_start")

    with tempfile.TemporaryDirectory() as flatten_tmp:
        saski_flat_path = os.path.join(flatten_tmp, "saski.bin")
        subprocess.run([objcopy_tool, "-O", "binary", saski_macho_path,
                        saski_flat_path], check=True)
        kernel_bytes = open(saski_flat_path, "rb").read()

    coreinit_entry, coreinit_base, coreinit_image = read_macho_image(
        coreinit_macho_path)

    variants = [
        (BOOT_PROTO_ARCH_AARCH64, kernel_dst, len(kernel_bytes),
         coreinit_base, len(coreinit_image)),
    ]
    # The allocator address is stored in InitDescription itself. Its
    # value cannot affect the encoded size: the field is always one
    # fixed-width UInt64 data word. Build once with a placeholder to
    # determine the following aligned address, then fill that word.
    init_desc = build_init_description(variants, 0)
    id_dest = BOOT_ALLOCATOR_REGION_BASE

    with tempfile.TemporaryDirectory() as tmp:
        allocator_obj = os.path.join(tmp, "allocator.o")
        allocator_bin = os.path.join(tmp, "allocator.bin")
        subprocess.run([cc, "--target=aarch64-none-elf", "-c", ALLOCATOR_SRC,
                        "-o", allocator_obj], check=True)
        alloc_off = nm_symbol_address(allocator_obj, "otos_bump_alloc")
        finalize_off = nm_symbol_address(allocator_obj, "otos_bump_finalize")
        subprocess.run([objcopy_tool, "-O", "binary", allocator_obj,
                        allocator_bin], check=True)
        allocator_code = open(allocator_bin, "rb").read()
        allocator_dest = (id_dest + len(init_desc) + 7) & ~7
        final_init_desc = build_init_description(variants, allocator_dest)
        if len(final_init_desc) != len(init_desc):
            sys.exit("InitDescription size changed when allocator address "
                     "was filled; refusing an overlapping layout")
        init_desc = final_init_desc
        if allocator_dest < id_dest + len(init_desc):
            sys.exit("InitDescription overlaps the boot allocator")
        code_dest = (allocator_dest + 72 + 15) & ~15
        stack_bottom = (code_dest + len(allocator_code) + 15) & ~15
        entry_stack_top = stack_bottom + 0x10000
        used = entry_stack_top - BOOT_ALLOCATOR_REGION_BASE
        allocator = build_boot_allocator(
            alloc=code_dest + alloc_off, finalize=code_dest + finalize_off,
            region_base=BOOT_ALLOCATOR_REGION_BASE,
            region_len=BOOT_ALLOCATOR_REGION_LEN, used=used)
        bpo_blob = (init_desc + bytes(allocator_dest - id_dest - len(init_desc))
                    + allocator + bytes(code_dest - allocator_dest - len(allocator))
                    + allocator_code)
        if len(bpo_blob) > BOOT_ALLOCATOR_REGION_LEN:
            sys.exit("boot allocator metadata/code overflow its region")
        kernel_bin_path = os.path.join(tmp, "kernel.bin")
        bpo_bin_path = os.path.join(tmp, "bpo.bin")
        coreinit_bin_path = os.path.join(tmp, "coreinit.bin")
        open(kernel_bin_path, "wb").write(kernel_bytes)
        open(bpo_bin_path, "wb").write(bpo_blob)
        open(coreinit_bin_path, "wb").write(coreinit_image)

        obj_path = os.path.join(tmp, "stub.o")
        elf_path = os.path.join(tmp, "stub.elf")
        defines = {
            "KERNEL_DST": hex(kernel_dst),
            "KERNEL_LEN": hex(len(kernel_bytes)),
            "KERNEL_BIN_PATH": f'"{kernel_bin_path}"',
            "BPO_LEN": hex(len(bpo_blob)),
            "BPO_BIN_PATH": f'"{bpo_bin_path}"',
            "COREINIT_DEST": hex(coreinit_base),
            "COREINIT_LEN": hex(len(coreinit_image)),
            "COREINIT_BIN_PATH": f'"{coreinit_bin_path}"',
            "DTB_PHYS": hex(DTB_PHYS),
            "ID_DEST": hex(id_dest),
            "ALLOCATOR_DEST": hex(allocator_dest),
            "ENTRY_STACK_TOP": hex(entry_stack_top),
            "INIT_ENTRY": hex(coreinit_entry),
            "BOOT_PROTOCOL_START": hex(boot_protocol_start),
        }
        cc_args = [cc, "--target=aarch64-none-elf", "-c", ARCH_SRC, "-o", obj_path]
        for name, value in defines.items():
            cc_args += ["-D", f"{name}={value}"]
        subprocess.run(cc_args, check=True)
        subprocess.run([cc, "--target=aarch64-none-elf", "-nostdlib",
                        "-static", "-Wl,--entry=_start", "-Wl,-Ttext=0x0",
                        obj_path, "-o", elf_path], check=True)

        flat_path = os.path.join(tmp, "stub.bin")
        subprocess.run([objcopy_tool, "-O", "binary", elf_path, flat_path],
                      check=True)
        write_efi(open(flat_path, "rb").read(), out_path)


# ---- Below: mkstub.py's own PE32+ container builder, unchanged -- see
# saski/tools/mkstub.py for the original. Struct packing, not
# hand-assembled opcodes, so there is nothing architecture-specific
# left to re-derive; this stub's own code is the .S file above instead
# of mkstub.py's raw instruction array. ----
def write_efi(image, out_path):
    HDR = 0x1000
    FILE_ALIGN = 0x200
    SECTION_ALIGN = 0x1000
    text_raw = image
    if len(text_raw) % FILE_ALIGN:
        text_raw += b"\x00" * (FILE_ALIGN - len(text_raw) % FILE_ALIGN)
    imgsz = (HDR + len(text_raw) + SECTION_ALIGN - 1) & ~(SECTION_ALIGN - 1)

    dos = b"MZ" + b"\x00" * 58 + struct.pack("<I", 0x40) + b"PE\x00\x00"
    coff = struct.pack("<HHIIIHH", 0xAA64, 1, 0, 0, 0, 240, 0x0022)
    opt = struct.pack(
        "<HBBIIIIIQIIHHHHHHIIIIHHQQQQII",
        0x20B, 1, 0, len(image), 0, 0, 0x1000, 0x1000, 0,
        SECTION_ALIGN, FILE_ALIGN, 0, 0, 0, 0, 0, 0,
        0, imgsz, HDR, 0, 10, 0x1600,
        0x100000, 0x1000, 0x100000, 0x1000, 0, 16)
    opt += b"\x00" * 128
    sec = struct.pack("<8sIIIIIIHHI", b".text\x00\x00\x00",
                      len(image), 0x1000, len(text_raw), HDR, 0, 0, 0, 0,
                      0x60000020)
    pe = dos + coff + opt + sec
    pe += b"\x00" * (HDR - len(pe))
    open(out_path, "wb").write(pe + text_raw)
    print(f"wrote {out_path}: {len(pe) + len(text_raw)} bytes "
         f"(stub code+data {len(image)} bytes)")


if __name__ == "__main__":
    main()

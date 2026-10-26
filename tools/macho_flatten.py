"""Reads a 64-bit Mach-O's loadable segments and LC_MAIN entry point,
flattened into a single memory image ready to copy verbatim into RAM at
a known base address.

otos-boot's whole model is "the loader does the Mach-O parsing the
bootloader usually leaves to the kernel" (see ../README.md and
otos-coreinit's own include/boot_protocol.h: "x4 = init's already-
resolved entry point"). For coreinit specifically this is the one real
piece of actual Mach-O parsing this project's new boot protocol needs
on the loader side -- saski's own entry point no longer calls
macho_load at all (see saski's boot_protocol_start), so something has
to place coreinit's segments in memory and resolve its entry point
instead, and that something is this.

Deliberately minimal, not a general Mach-O loader: handles exactly the
shape this project's own build produces (a PIE Mach-O with
LC_SEGMENT_64 segments and an LC_MAIN entry, built by otos-coreinit's
CMakeLists.txt via ld64.lld) -- no dynamic linking, no relocations, no
LC_UNIXTHREAD fallback (that convention only ever existed to satisfy
GRUB's xnu loader, which plays no part in this protocol -- see
include/boot_protocol.h's own top comment). A segment whose file size
is 0 (__PAGEZERO, used only to set the image's base load address via
-pagezero_size) is skipped entirely: it has nothing to copy and no
permissions to map.
"""
import struct

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_MAIN = 0x80000028


def read_macho_image(path):
    """Returns (entry_vmaddr, base_vmaddr, image_bytes): image_bytes is
    the flattened content starting at base_vmaddr (the lowest non-
    __PAGEZERO segment's own vmaddr), covering every loadable segment
    up to the highest vmaddr+vmsize, with each segment's own file bytes
    copied to its own offset within that span and every byte outside
    any segment's file-backed range left zero (BSS, and any padding
    between segments). Copying image_bytes verbatim to base_vmaddr in
    target memory reproduces this Mach-O's own runtime layout exactly.
    """
    data = open(path, "rb").read()
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, reserved = (
        struct.unpack_from("<IiiIIIII", data, 0)
    )
    if magic != MH_MAGIC_64:
        raise ValueError(f"{path}: not a 64-bit little-endian Mach-O (magic 0x{magic:x})")

    # __PAGEZERO (vmsize only, no file content -- just a base-address
    # convention via -pagezero_size) and __LINKEDIT (symbol/dynamic-
    # linking metadata the dynamic linker consumes, never the runtime
    # image itself) are both well-known Mach-O segment names that a
    # real loader never maps as part of "the program," regardless of
    # their own filesize/protection bits -- __LINKEDIT in particular
    # DOES have a nonzero filesize, so filtering on that alone (an
    # earlier version of this function did) silently pulls in symbol
    # table bytes as if they were runtime BSS. Excluded by name, the
    # same way any real loader's special-casing of these two works.
    SKIP_SEGMENTS = (b"__PAGEZERO\x00\x00\x00\x00\x00\x00",
                     b"__LINKEDIT\x00\x00\x00\x00\x00\x00")
    segments = []  # (vmaddr, vmsize, fileoff, filesize)
    entry_off = None
    off = 32
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == LC_SEGMENT_64:
            (segname, vmaddr, vmsize, fileoff, filesize, maxprot, initprot,
             nsects, segflags) = struct.unpack_from("<16sQQQQiiII", data, off + 8)
            if segname not in SKIP_SEGMENTS and filesize != 0:
                segments.append((vmaddr, vmsize, fileoff, filesize))
        elif cmd == LC_MAIN:
            entry_off, _stacksize = struct.unpack_from("<QQ", data, off + 8)
        off += cmdsize

    if not segments:
        raise ValueError(f"{path}: no loadable (non-__PAGEZERO) LC_SEGMENT_64 found")
    if entry_off is None:
        raise ValueError(f"{path}: no LC_MAIN -- see this module's own top "
                         "comment on why LC_UNIXTHREAD isn't handled")

    base_vmaddr = min(s[0] for s in segments)
    end_vmaddr = max(s[0] + s[1] for s in segments)
    image = bytearray(end_vmaddr - base_vmaddr)
    for vmaddr, vmsize, fileoff, filesize in segments:
        image[vmaddr - base_vmaddr:vmaddr - base_vmaddr + filesize] = (
            data[fileoff:fileoff + filesize]
        )
        # Bytes from filesize..vmsize within this segment are BSS --
        # image[] is already zero there (bytearray's own default), so
        # nothing further to do.

    # LC_MAIN's entryoff is a FILE offset, not a vmaddr-relative one --
    # resolve it against whichever segment's own fileoff range contains
    # it, the same way a real Mach-O loader would (this project's build
    # always has __TEXT.fileoff == 0, so entry_off and the file offset
    # coincide for every binary it actually produces, but this doesn't
    # assume that).
    entry_vmaddr = None
    for vmaddr, vmsize, fileoff, filesize in segments:
        if fileoff <= entry_off < fileoff + filesize:
            entry_vmaddr = vmaddr + (entry_off - fileoff)
            break
    if entry_vmaddr is None:
        raise ValueError(f"{path}: LC_MAIN entryoff 0x{entry_off:x} is not inside "
                         "any loadable segment's file range")

    return entry_vmaddr, base_vmaddr, bytes(image)

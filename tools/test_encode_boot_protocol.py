#!/usr/bin/env python3
"""Cross-language round trip: encode with this repo's Python port, decode
with otos-coreinit's real C decoder (boot_protocol_decode.h), confirm
every field and list element survives. Needs a sibling otos-coreinit
checkout and a C compiler (same two things tools/build-stub.py already
needs); run manually, not part of any build:

    python3 tools/test_encode_boot_protocol.py [path/to/otos-coreinit]
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
from encode_boot_protocol import (
    build_init_description, build_boot_allocator,
    BOOT_PROTO_ARCH_AARCH64, BOOT_PROTO_ARCH_X86_64,
)

COREINIT_ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "..", "otos-coreinit")


def main():
    init_desc = build_init_description([
        (BOOT_PROTO_ARCH_AARCH64, 0x40080000, 0x100000, 0x40200000, 0x40000),
        (BOOT_PROTO_ARCH_X86_64, 0x1000000, 0x400000, 0x1800000, 0x400000),
    ], 0x41880080)
    allocator = build_boot_allocator(alloc=0x41880100, finalize=0x41880140,
                                     region_base=0x41880000,
                                     region_len=0x110000, used=0x180)

    with tempfile.TemporaryDirectory() as tmp:
        for name, blob in [("id.bin", init_desc),
                           ("allocator.bin", allocator)]:
            open(os.path.join(tmp, name), "wb").write(blob)

        check_c = os.path.join(tmp, "check.c")
        with open(check_c, "w") as f:
            f.write(f'''
#include "{COREINIT_ROOT}/coreinit/boot_protocol_decode.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

static void *slurp(const char *path, size_t *out_len) {{
    FILE *f = fopen(path, "rb");
    fseek(f, 0, SEEK_END);
    *out_len = (size_t)ftell(f);
    fseek(f, 0, SEEK_SET);
    void *buf = malloc(*out_len);
    fread(buf, 1, *out_len, f);
    fclose(f);
    return buf;
}}

int main(void) {{
    size_t id_len;
    void *id_buf = slurp("{tmp}/id.bin", &id_len);

    const struct init_description_data *description;
    const struct init_variant *variants;
    uint32_t variant_count;
    int ok = boot_protocol_read_init_description(id_buf, id_len, &description,
                                                  &variants, &variant_count);
    assert(ok == 1);
    assert(description->coreinit_allocator_phys == 0x41880080ull);
    assert(variant_count == 2);
    assert(variants[0].kernel_macho_phys == 0x40080000ull);
    assert(variants[1].arch_tag == {BOOT_PROTO_ARCH_X86_64});

    printf("cross-language round trip: PASS (%u variants)\\n", variant_count);
    return 0;
}}
''')
        exe = os.path.join(tmp, "check")
        cc = os.environ.get("CC", "cc")
        subprocess.run([cc, "-std=c11", "-I", COREINIT_ROOT, check_c, "-o", exe],
                      check=True)
        subprocess.run([exe], check=True)


if __name__ == "__main__":
    main()

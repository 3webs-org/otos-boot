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
    build_machine_description, build_init_description,
    build_saski_boot_params, BOOT_PROTO_ARCH_AARCH64, BOOT_PROTO_ARCH_X86_64,
)

COREINIT_ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "..", "otos-coreinit")


def main():
    md = build_machine_description(
        arch_tag=BOOT_PROTO_ARCH_AARCH64, ram_size=0x20000000,
        free_memory_base=0x54000000, free_memory_len=0x4000000,
        fdt_blob_phys=0x40000000, early_rsdp_phys=0, uart_base=0x9000000,
        lapic_base=0, gicd_base=0x8000000, gicr_base=0x80a0000,
        gicr_size=0xf60000, gic_cpu_base=0, gic_is_v2=0, timer_freq_hz=0,
        psci_use_hvc=1, cores=[(0, 1), (1, 1), (2, 0)])
    init_desc = build_init_description([
        (BOOT_PROTO_ARCH_AARCH64, 0x40080000, 0x100000, 0x40200000, 0x40000),
        (BOOT_PROTO_ARCH_X86_64, 0x1000000, 0x400000, 0x1800000, 0x400000),
    ])
    sbp = build_saski_boot_params(saski_pool_base=0x41890000,
                                  saski_pool_len=0x100000)

    with tempfile.TemporaryDirectory() as tmp:
        for name, blob in [("md.bin", md), ("id.bin", init_desc),
                           ("sbp.bin", sbp)]:
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
    size_t md_len, id_len;
    void *md_buf = slurp("{tmp}/md.bin", &md_len);
    void *id_buf = slurp("{tmp}/id.bin", &id_len);

    const struct core_entry *cores;
    uint32_t core_count;
    const struct machine_description_data *md =
        boot_protocol_read_machine_description(md_buf, md_len, &cores,
                                               &core_count);
    assert(md != NULL);
    assert(md->arch_tag == {BOOT_PROTO_ARCH_AARCH64});
    assert(md->ram_size == 0x20000000ull);
    assert(md->gicr_base == 0x80a0000ull);
    assert(md->psci_use_hvc == 1);
    assert(core_count == 3);
    assert(cores[0].target == 0 && cores[0].enabled == 1);
    assert(cores[2].target == 2 && cores[2].enabled == 0);

    const struct init_variant *variants;
    uint32_t variant_count;
    int ok = boot_protocol_read_init_description(id_buf, id_len, &variants,
                                                  &variant_count);
    assert(ok == 1);
    assert(variant_count == 2);
    assert(variants[0].kernel_macho_phys == 0x40080000ull);
    assert(variants[1].arch_tag == {BOOT_PROTO_ARCH_X86_64});

    printf("cross-language round trip: PASS (%u cores, %u variants)\\n",
          core_count, variant_count);
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

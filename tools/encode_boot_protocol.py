"""Python port of otos-coreinit's include/capnp_list.h encoder, plus the
exact field layouts include/boot_protocol.h defines -- see both for the
real documentation; this module is deliberately just enough to build the
three wire-format objects this stub needs; see those two headers
(vendored into include/ here) for the authoritative bit-packing and
field-order reference this must stay byte-for-byte consistent with.
"""
import struct


def build_list_root(data_words, elements, elem_data_words):
    """data_words: list[int] (root struct's plain data, written
    verbatim). elements: list[int], flattened elem_data_words-per-
    element (same convention capnp_list.h's own capnp_build_list_root
    takes). Returns the encoded message bytes."""
    n_data_words = len(data_words)
    n_elements = len(elements) // elem_data_words if elem_data_words else 0
    assert n_elements * elem_data_words == len(elements)

    element_words = n_elements * elem_data_words
    list_body_words = 1 + element_words  # tag word + elements
    seg_words = 1 + n_data_words + 1 + list_body_words

    out = bytearray()
    out += struct.pack("<I", 0)  # segment count - 1 = 0
    out += struct.pack("<I", seg_words)
    # root pointer: struct, offset 0, data_words=n_data_words, ptr_words=1
    out += struct.pack("<Q", (n_data_words << 32) | (1 << 48))
    for w in data_words:
        out += struct.pack("<Q", w)
    # list pointer: tag=1 (list), offset 0, element_size=7 (composite),
    # element_count=list_body_words
    out += struct.pack("<Q", 1 | (7 << 32) | (list_body_words << 35))
    # tag word: struct-shaped, "offset" repurposed as element count,
    # data_words=elem_data_words, ptr_words=0
    out += struct.pack("<Q", (n_elements << 2) | (elem_data_words << 32))
    for w in elements:
        out += struct.pack("<Q", w)
    return bytes(out)


# ---- boot_protocol.h field layouts (keep in exact sync by hand) ----

INIT_DESCRIPTION_MAGIC = 0x494E495444455343  # "INITDESC"
BOOT_ALLOCATOR_MAGIC = 0x424F4F54414C4F43  # "BOOTALOC"

BOOT_PROTO_ARCH_X86_64 = 0
BOOT_PROTO_ARCH_AARCH64 = 1


def build_init_description(variants, coreinit_allocator_phys):
    """variants: list of (arch_tag, kernel_macho_phys, kernel_macho_len,
    init_macho_phys, init_macho_len) -- see struct init_variant."""
    elements = []
    for v in variants:
        assert len(v) == 5  # BOOT_PROTO_INIT_VARIANT_WORDS
        elements += list(v)
    return build_list_root(
        [INIT_DESCRIPTION_MAGIC, coreinit_allocator_phys], elements, 5)


def build_boot_allocator(*, alloc, finalize, region_base, region_len, used):
    """Flat seven-word Cap'n Proto boot_allocator object."""
    return struct.pack(
        "<IIQ7Q", 0, 8, 7 << 32, BOOT_ALLOCATOR_MAGIC, alloc, finalize,
        region_base, region_len, used, 0)

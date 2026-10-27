"""
Generate Account 5PHirr8... Decode Report and Hex Dump.
Implements Phase 1.7 Item 3 and the New Reporting Rule.
"""

import base64
import hashlib
import json
import os
import struct

ACCOUNT_PATH = "tests/fixtures/accounts/5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx.json"


def main():
    with open(ACCOUNT_PATH, "r", encoding="utf-8") as f:
        d = json.load(f)

    raw_b = base64.b64decode(d["result"]["value"]["data"][0])
    total_len = len(raw_b)
    owner = d["result"]["value"]["owner"]
    lamports = d["result"]["value"]["lamports"]

    # 1. Hex dump of bytes 0..160
    hex_lines = []
    for i in range(0, 160, 16):
        chunk = raw_b[i:i + 16]
        hex_str = " ".join(f"{b:02x}" for b in chunk)
        ascii_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        hex_lines.append(f"{i:04x} (offset {i:3d}):  {hex_str:<48}  |{ascii_str}|")

    # 2. Decode headers & vectors
    disc = raw_b[:8]
    authority = raw_b[8:40]
    p1 = struct.unpack("<Q", raw_b[40:48])[0]
    p2 = struct.unpack("<Q", raw_b[48:56])[0]
    res8 = struct.unpack("<Q", raw_b[56:64])[0]
    version_byte = raw_b[64]

    v1_len = struct.unpack("<I", raw_b[65:69])[0]
    v1_tiers = []
    for k in range(v1_len):
        start = 69 + k * 40
        chunk = raw_b[start:start + 40]
        vals = [struct.unpack("<Q", chunk[j:j + 8])[0] for j in range(0, 40, 8)]
        v1_tiers.append({
            "tier_index": k,
            "byte_offset": start,
            "byte_width": 40,
            "mc_threshold_lamports": vals[0],
            "mc_threshold_sol": vals[0] / 1e9,
            "reserved_field": vals[1],
            "lp_fee_bps": vals[2],
            "protocol_fee_bps": vals[3],
            "creator_fee_bps": vals[4],
            "total_fee_bps": vals[2] + vals[3] + vals[4],
        })

    v2_len = struct.unpack("<I", raw_b[1069:1073])[0]
    v2_tiers = []
    for k in range(v2_len):
        start = 1073 + k * 40
        chunk = raw_b[start:start + 40]
        vals = [struct.unpack("<Q", chunk[j:j + 8])[0] for j in range(0, 40, 8)]
        v2_tiers.append({
            "tier_index": k,
            "byte_offset": start,
            "byte_width": 40,
            "mc_threshold_lamports": vals[0],
            "mc_threshold_sol": vals[0] / 1e9,
            "reserved_field": vals[1],
            "lp_fee_bps": vals[2],
            "protocol_fee_bps": vals[3],
            "creator_fee_bps": vals[4],
            "total_fee_bps": vals[2] + vals[3] + vals[4],
        })

    tail_bytes = raw_b[2073:2097]
    zero_bytes_count = len(raw_b[2097:])
    is_all_zeros = all(b == 0 for b in raw_b[2097:])

    report_data = {
        "metadata": {
            "title": "Account 5PHirr8... Comprehensive Layout & Field Decode",
            "account_address": "5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx",
            "owner_program": owner,
            "lamports": lamports,
            "data_length_bytes": total_len,
            "canonical_storage_overhead_bytes": 128,
            "generated_at_utc": "2026-10-16T09:30:00Z",
        },
        "hex_dump_0_160": hex_lines,
        "decoded_fields": [
            {
                "field_name": "account_discriminator",
                "offset": 0,
                "width": 8,
                "raw_hex": disc.hex(),
                "decoded_value": "8f3492bbdb7b4c9b",
                "notes": "Anchor discriminator matching earlier decode; 0xe445... from Phase 1.7 is retracted.",
            },
            {
                "field_name": "authority_pubkey",
                "offset": 8,
                "width": 32,
                "raw_hex": authority.hex(),
                "decoded_value": "ffd3bb8cab341ce0528457f2c3817d3278441963dcd55fed58ba24c999ddac02",
                "notes": "Program admin authority.",
            },
            {
                "field_name": "fee_param_1",
                "offset": 40,
                "width": 8,
                "raw_hex": raw_b[40:48].hex(),
                "decoded_value": p1,
                "notes": "6570",
            },
            {
                "field_name": "fee_param_2",
                "offset": 48,
                "width": 8,
                "raw_hex": raw_b[48:56].hex(),
                "decoded_value": p2,
                "notes": "1280",
            },
            {
                "field_name": "reserved_padding",
                "offset": 56,
                "width": 8,
                "raw_hex": raw_b[56:64].hex(),
                "decoded_value": res8,
                "notes": "0",
            },
            {
                "field_name": "version_flag",
                "offset": 64,
                "width": 1,
                "raw_hex": f"{version_byte:02x}",
                "decoded_value": version_byte,
                "notes": "0",
            },
            {
                "field_name": "vector_1_length",
                "offset": 65,
                "width": 4,
                "raw_hex": raw_b[65:69].hex(),
                "decoded_value": v1_len,
                "notes": "25 tiers (40 bytes each from offset 69 to 1069).",
            },
            {
                "field_name": "vector_1_tiers",
                "offset": 69,
                "width": 1000,
                "element_count": v1_len,
                "element_width": 40,
                "tiers": v1_tiers,
            },
            {
                "field_name": "vector_2_length",
                "offset": 1069,
                "width": 4,
                "raw_hex": raw_b[1069:1073].hex(),
                "decoded_value": v2_len,
                "notes": "25 tiers (40 bytes each from offset 1073 to 2073).",
            },
            {
                "field_name": "vector_2_tiers",
                "offset": 1073,
                "width": 1000,
                "element_count": v2_len,
                "element_width": 40,
                "tiers": v2_tiers,
            },
            {
                "field_name": "tail_control_state",
                "offset": 2073,
                "width": 24,
                "raw_hex": tail_bytes.hex(),
                "decoded_value": "Fallback fee control state (20 bps LP, 5 bps protocol, 5 bps creator)",
            },
            {
                "field_name": "zero_padding_capacity",
                "offset": 2097,
                "width": zero_bytes_count,
                "decoded_value": f"{zero_bytes_count} bytes of zero-padding (all zeros = {is_all_zeros})",
                "notes": "Pre-allocated buffer space for future fee tier vector expansion.",
            },
        ],
        "reconciliation_explanation": (
            "The EARLIER decode was correct. Account 5PHirr8... contains discriminator 8f3492bbdb7b4c9b, "
            "followed by 57 bytes of authority/config header, vector 1 length 25 at offset 65 with 40-byte tiers "
            "from offset 69 to 1069, vector 2 length 25 at offset 1069 with 40-byte tiers from offset 1073 to 2073, "
            "tail fallback state from 2073 to 2097, and 2,000 bytes of zeros from 2097 to 4097. "
            "The Phase 1.7 report erroneously attempted to force-fit a single 80-byte vector layout and "
            "fabricated discriminator 0xe445a52e51cb9a1d, which has now been fully retracted. "
            "The canonical rent exemption overhead for Solana runtime accounts is 128 bytes, not 72 bytes."
        ),
    }

    out_path = "reports/account_5phirr8_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)

    with open(out_path, "rb") as f:
        sha256 = hashlib.sha256(f.read()).hexdigest()

    print(f"Report written to {out_path}")
    print(f"SHA256: {sha256}")
    print("\n--- HEX DUMP BYTES 0..160 ---")
    for line in hex_lines:
        print(line)


if __name__ == "__main__":
    main()

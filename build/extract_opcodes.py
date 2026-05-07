#!/usr/bin/env python3
"""
extract_opcodes.py
==================
Extract raw opcode hex from a dis6x disassembly file.
Replicates what the regex101.com/r/yTVMQv tool does, locally.

Usage
-----
    python3 extract_opcodes.py  INPUT_dis.asm  opcodes.hex  [SECTION]

    INPUT_dis.asm  – output of:  dis6x foo.obj foo_dis.asm
    opcodes.hex    – output file (plain hex string, no spaces)
    SECTION        – section name to extract (default: .audio)

Only the named section's opcodes are extracted.  The hex is written as a
continuous lowercase string with no spaces or line breaks, ready for patch_zdl.py.
"""

import sys
import re


def extract(asm_path: str, section: str = '.audio') -> bytes:
    """
    dis6x output format (no '-b' flag, which is what we use):

        00000000       784c           LDW.D1T2  ...   ← 16-bit compact (4 hex digits)
        00000004   0d902267           LDW.D1T2  ...   ← 32-bit full    (8 hex digits)

    Addresses may be followed by '||' for parallel slots.
    We emit bytes in little-endian order, same as they appear in memory.
    """
    result = bytearray()
    in_section = False

    # Match:  <8-digit-addr>   <4 or 8 hex digits>   <whitespace>
    op_re = re.compile(r'^([0-9a-fA-F]{8})\s+([0-9a-fA-F]{4,8})\s')

    with open(asm_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            # Section header:  "TEXT Section .audio (Little Endian), 0x... bytes at 0x..."
            if re.search(r'Section\s+' + re.escape(section), line, re.IGNORECASE):
                in_section = True
                continue
            # Any other section header ends our target section
            if re.match(r'^(TEXT|DATA|BSS)\s+Section\s+', line) and in_section:
                break

            if not in_section:
                continue

            m = op_re.match(line)
            if not m:
                continue

            addr_str = m.group(1)
            op_str   = m.group(2)

            addr = int(addr_str, 16)
            op   = int(op_str, 16)

            if len(op_str) == 4:
                # 16-bit compact instruction – 2 bytes LE
                result[addr:addr+2] = op.to_bytes(2, 'little')
            else:
                # 32-bit instruction – 4 bytes LE
                result[addr:addr+4] = op.to_bytes(4, 'little')

    if not result:
        raise ValueError(f"Section '{section}' not found or empty in {asm_path}")

    return bytes(result)


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    asm_in   = sys.argv[1]
    hex_out  = sys.argv[2]
    section  = sys.argv[3] if len(sys.argv) > 3 else '.audio'

    data = extract(asm_in, section)
    hex_str = data.hex()

    with open(hex_out, 'w') as f:
        f.write(hex_str)

    print(f"Extracted {len(data)} bytes from '{section}' → {hex_out}")


if __name__ == '__main__':
    main()

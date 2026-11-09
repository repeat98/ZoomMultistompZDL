"""Regression checks for calls in dynamically loaded init code."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import linker


class InitCalls(unittest.TestCase):
    def test_calls_follow_text_rebase(self):
        init_va = 0x7A0
        targets = [0x380, 0x3CC, 0x1800]
        body = linker._init_materialize_body(targets, init_va)
        for i, target in enumerate(targets):
            off = len(linker._INIT_MAT_PROLOGUE) + i * linker._INIT_MAT_STRIDE
            off += linker._INIT_MAT_BRANCH_OFF
            word = struct.unpack_from('<I', body, off)[0]
            self.assertEqual(word & ~(0x1FFFFF << 7), 0x12)  # direct B.S2
            delta = (word >> 7) & 0x1FFFFF
            if delta & (1 << 20):
                delta -= 1 << 21
            for load_base in [0, 0x10000000, 0x11820000]:
                pc = (load_base + init_va + off) & ~31
                self.assertEqual(pc + delta * 4, load_base + target)

    def test_zero_call_probe_keeps_frame(self):
        self.assertEqual(linker._init_materialize_body([], 0x7A0),
                         linker._INIT_MAT_PROLOGUE + linker._INIT_MAT_EPILOGUE)

    def test_rejects_invalid_branch_layout(self):
        for targets, base in [([0x380], 1), ([0x381], 0x7A0), ([0x800000], 0x7A0)]:
            with self.assertRaises(ValueError):
                linker._init_materialize_body(targets, base)


if __name__ == '__main__':
    unittest.main()

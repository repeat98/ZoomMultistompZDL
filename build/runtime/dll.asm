; dll.asm - Dll_<Name> for custom ZDLs, written from the documented host contract
; (SDK/TAP_TEMPO.md, ZDL_ABI.md): the host calls Dll_<Name>(A4 = output struct) and
; expects +0 = descriptor row count (byte), +4 = descriptor address, +8 = image-info
; address. Replaces the stock NoiseGate-derived 200-byte body (whose tail is an unrelated
; unsigned-division routine).
;
; Assemble with --no_compress (no fetch-packet header). The linker places it 32-byte
; aligned; every store sits in the five delay slots of B B3 and no execute packet
; crosses a fetch-packet boundary (the rule of the hardware-proven tempo variant).
; zdl_desc / zdl_info are resolved by the linker through the ABS_L16/ABS_H16
; relocations; the row count is patched into MVK.L1 (signed 5-bit, rows <= 15).

        .sect   ".text"
        .ref    zdl_desc, zdl_info
zdl_dll:
        B.S2    B3
||      MVKL.S1 zdl_desc,A1
||      MVK.L1  0,A0                    ; row count (patched by the linker)
        MVKH.S1 zdl_desc,A1
||      MVKL.S2 zdl_info,B0
||      STB.D1T1 A0,*+A4[0]
        MVKH.S2 zdl_info,B0
||      STW.D1T1 A1,*+A4[1]
        STW.D1T2 B0,*+A4[2]
        NOP     2

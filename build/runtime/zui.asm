; Third-party license notice (scope: zui_stub / zui_stub_ret,
; zui_push_rts and zui_pop_rts only).
; Adapted from TI C6000 CGT 8.5.0.LTS lib/src/call_stub.asm and push.asm.
; Changes in this file: local zui_* labels and placement in a combined section.
; The following TI terms are preserved for these portions. This notice does not
; assign a license to the other portions of this file or to the whole SDK.
;******************************************************************************
;* call_stub                                                                  *
;*                                                                            *
;* Copyright (c) 2000 Texas Instruments Incorporated                          *
;* http://www.ti.com/                                                         *
;*                                                                            *
;*  Redistribution and  use in source  and binary forms, with  or without     *
;*  modification,  are permitted provided  that the  following conditions     *
;*  are met:                                                                  *
;*                                                                            *
;*     Redistributions  of source  code must  retain the  above copyright     *
;*     notice, this list of conditions and the following disclaimer.          *
;*                                                                            *
;*     Redistributions in binary form  must reproduce the above copyright     *
;*     notice, this  list of conditions  and the following  disclaimer in     *
;*     the  documentation  and/or   other  materials  provided  with  the     *
;*     distribution.                                                          *
;*                                                                            *
;*     Neither the  name of Texas Instruments Incorporated  nor the names     *
;*     of its  contributors may  be used to  endorse or  promote products     *
;*     derived  from   this  software  without   specific  prior  written     *
;*     permission.                                                            *
;*                                                                            *
;*  THIS SOFTWARE  IS PROVIDED BY THE COPYRIGHT  HOLDERS AND CONTRIBUTORS     *
;*  "AS IS"  AND ANY  EXPRESS OR IMPLIED  WARRANTIES, INCLUDING,  BUT NOT     *
;*  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR     *
;*  A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT     *
;*  OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,     *
;*  SPECIAL,  EXEMPLARY,  OR CONSEQUENTIAL  DAMAGES  (INCLUDING, BUT  NOT     *
;*  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,     *
;*  DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY     *
;*  THEORY OF  LIABILITY, WHETHER IN CONTRACT, STRICT  LIABILITY, OR TORT     *
;*  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE     *
;*  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.      *
;*                                                                            *
;******************************************************************************

; zui.asm - Zoom UI runtime for custom ZDLs, written from the documented edit-handler
; ABI (SDK/reference/upstream/ZoomMultistompZDL/docs/EDIT-HANDLER-ABI.md), not copied
; from firmware files. TI C6000 assembler, C674x, EABI, position independent: every
; branch/call target is a local label in this one section, so the object has no
; relocations and the linker places the bytes as they are.
;
; Firmware contract (per handler call): A4 = per-slot UI state (uint32_t state[53]),
; B3 = return address. state[0] = first argument for the read callback, state[1] =
; parameter table base, state[31] = read-knob callback, state[21] = value-conversion
; callback, state[7] = write-parameter callback. Callbacks are reached through
; zui_stub (__c6xabi_call_stub semantics: call B31, preserve A0-A2/A6/A7/B0-B7).
;
; Generated entries (appended by SDK/build/zui_runtime.py) set B4 = knob id and
; A1 = byte offset of the parameter in the table, then branch to zui_knob.

        .sect   ".text"

; ---------------------------------------------------------------------------
; OnOff handler: v = state[31](state[0], 0); write 0.0 or 1.0 to params[0].
; ---------------------------------------------------------------------------
zui_onf:
        STW.D2T2    B3,*B15--[2]            ; push return address
        MV.L1       A4,A6                   ; A6 = state
        LDW.D1T2    *+A6[31],B31            ; read-knob callback
        LDW.D1T1    *+A6[1],A0              ; parameter table base
        LDW.D1T1    *+A6[0],A4              ; callback argument 0
        MVK.L2      0,B4                    ; knob id 0 = OnOff
        NOP         4
        CALLP.S2    zui_stub,B3             ; A4 = on/off state
        MV.L2X      A4,B0
        NOP         1
  [B0]  B.S1        zui_onf_on
        NOP         5
        ; OFF: state[7](params, B4 = 0.0, A6 = K), then return
        LDW.D1T1    *+A6[7],A3
        MVKL.S1     0x44306666,A6
        MVKH.S1     0x44306666,A6
        MV.L1       A0,A4
        NOP         2
        B.S2X       A3
        ADDKPC.S2   zui_onf_ret,B3,4
zui_onf_ret:
        LDW.D2T2    *++B15[2],B3            ; pop return address
        NOP         4
        B.S2        B3
        NOP         5
zui_onf_on:
        ; ON: tail call state[7](params, B4 = 1.0, A6 = K)
        LDW.D1T1    *+A6[7],A3
        LDW.D2T2    *++B15[2],B3            ; pop return address
        MVKL.S1     0x44306666,A6
        MVKH.S1     0x44306666,A6
        MVKL.S2     0x3F800000,B4
        MVKH.S2     0x3F800000,B4
        MV.L1       A0,A4
        NOP         2
        B.S2X       A3
        NOP         5

; ---------------------------------------------------------------------------
; Knob handler body. In: A4 = state, B4 = knob id, A1 = parameter byte offset.
;   v = state[31](state[0], knob id)
;   r = state[21](A4 = 255 << 22, B4 = 0, A6 = 151, B6 = 0, A8 = v)
;   tail call state[7](params + offset, B4 = r, A6 = K)
; ---------------------------------------------------------------------------
zui_knob:
        STW.D2T2    B3,*B15--[2]            ; push return address
        MV.L1       A4,A7                   ; A7 = state (kept by zui_stub)
        LDW.D1T2    *+A7[31],B31            ; read-knob callback
        LDW.D1T1    *+A7[1],A0              ; parameter table base (kept by zui_stub)
        LDW.D1T1    *+A7[0],A4              ; callback argument 0
        NOP         4
        CALLP.S2    zui_stub,B3             ; A4 = raw knob value
        MV.L1       A4,A8
        MVK.S1      151,A6
        MVK.S1      255,A4
        LDW.D1T2    *+A7[21],B31            ; value-conversion callback
        SHL.S1      A4,22,A4
        MVK.L2      0,B4
        MVK.L2      0,B6
        NOP         2
        CALLP.S2    zui_stub,B3             ; A4 = converted value
        LDW.D1T1    *+A7[7],A3              ; write-parameter callback
        LDW.D2T2    *++B15[2],B3            ; pop return address
        MVKL.S2     0x44306666,B5
        MVKH.S2     0x44306666,B5
        MV.L2X      A4,B4
        ADD.L1      A0,A1,A4                ; &params[offset]
        MV.L1X      B5,A6
        NOP         1
        B.S2X       A3                      ; tail call
        NOP         5

; ---------------------------------------------------------------------------
; Call stub: same code as TI RTS lib/src/call_stub.asm (__c6xabi_call_stub).
; Calls B31, preserves A0-A2, A6, A7, B0-B7 for the caller.
; ---------------------------------------------------------------------------
        .align  32
zui_stub:
        STW.D2T1    A2,*B15--[2]
        B.S2        B31
||      STDW.D2T1   A7:A6,*B15--
        STDW.D2T1   A1:A0,*B15--
        STDW.D2T2   B7:B6,*B15--
        STDW.D2T2   B5:B4,*B15--
        STDW.D2T2   B1:B0,*B15--
        STDW.D2T2   B3:B2,*B15--
||      ADDKPC.S2   zui_stub_ret,B3,0
zui_stub_ret:
        LDDW.D2T2   *++B15,B3:B2
        LDDW.D2T2   *++B15,B1:B0
        LDDW.D2T2   *++B15,B5:B4
        LDDW.D2T2   *++B15,B7:B6
        LDDW.D2T1   *++B15,A1:A0
        B.S2        B3
||      LDDW.D2T1   *++B15,A7:A6
        LDW.D2T1    *++B15[2],A2
        NOP         4

; ---------------------------------------------------------------------------
; Register save/restore helpers called by code compiled for size: same code as
; TI RTS lib/src/push.asm (__c6xabi_push_rts / __c6xabi_pop_rts).
; ---------------------------------------------------------------------------
        .align  32
zui_push_rts:
        STW.D2T2    B14,*B15--[2]
        B.S2X       A3
||      STDW.D2T1   A15:A14,*B15--
        STDW.D2T2   B13:B12,*B15--
        STDW.D2T1   A13:A12,*B15--
        STDW.D2T2   B11:B10,*B15--
        STDW.D2T1   A11:A10,*B15--
        STDW.D2T2   B3:B2,*B15--

        .align  32
zui_pop_rts:
        LDDW.D2T2   *++B15,B3:B2
        LDDW.D2T1   *++B15,A11:A10
        LDDW.D2T2   *++B15,B11:B10
        LDDW.D2T1   *++B15,A13:A12
        LDDW.D2T2   *++B15,B13:B12
        B.S2        B3
||      LDDW.D2T1   *++B15,A15:A14
        LDW.D2T2    *++B15[2],B14
        NOP         4

; ---------------------------------------------------------------------------
; Generated per-knob entries follow (zui_k<index>).
; ---------------------------------------------------------------------------

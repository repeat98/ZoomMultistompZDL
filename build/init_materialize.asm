;* Relocation correction, 2026-09-10: the former MVKL/MVKH target was an
;* absolute link-time address with no dynamic relocation. Use a PC-relative B
;* at block+0x20, followed by the existing ADDKPC return setup. Both the call
;* and return now follow the loaded text base. Hardware verification pending.
;* init_materialize.asm -- the _init body that materializes params on load.
;*
;* THE BUG (docs/INIT-MATERIALIZATION.md): after a patch load the whole param
;* block reads ZERO, so params[0] -- the bypass flag -- is zero too and the audio
;* function returns on its first instruction. The slot passes dry audio through
;* while the pedal's screen shows the saved knob values, until you touch a knob.
;* Stock effects escape it because their _init calls their own edit handlers at
;* load; ours has always emitted a NOP_RETURN.
;*
;* This costs us slots 4-6 entirely. There the firmware ignores live 0x31 param
;* edits, so the editor's replay workaround cannot reach a running effect and the
;* only update path is store+reload -- which is exactly what an effect with a
;* NOP _init cannot survive. Fixing _init is the only route to working 4-6.
;*
;* ---------------------------------------------------------------------------
;* WHY THE CALLEE-SAVED SET IS PUSHED (added 2026-09-07)
;*
;* v1 (ctx in A10) and v2 (ctx on the stack) BOTH froze the pedal on boot, and
;* both run clean in the Ziddle emulator -- init_completed=true, params correctly
;* materialized. So the fault was never the instruction sequence; it is something
;* the emulator does not model, and the register file is the obvious candidate.
;*
;* Disassembling stock MS-70CDR effects settled it. Every stock _init brackets
;* itself with __push_rts / __c6xabi_pop_rts, e.g. Fx_MOD_VintageCE_init:
;*
;*     CALLP __push_rts, A3
;*     CALLP __call_stub  ->  ctx[34](ctx[1], table, 180)
;*     CALLP __call_stub  ->  ctx[35](ctx[2], 0, 16)
;*     CALLP __call_stub  ->  ctx[35](ctx[2]+16, 0, 84)
;*     CALLP Fx_MOD_VintageCE_comp_edit, B3      <- own handlers, direct CALLP
;*     CALLP Fx_MOD_VintageCE_rate_edit, B3
;*     CALLP Fx_MOD_VintageCE_mix_edit, B3
;*     CALLP Fx_MOD_VintageCE_outLv_edit, B3
;*     CALLP __c6xabi_pop_rts, A3
;*
;* and __push_rts saves B14, A15:A14, B13:B12, A13:A12, B11:B10, A11:A10, B3:B2
;* -- the whole callee-saved set, B14 (the data-page pointer) included. v2 saved
;* B3 and A4. If any handler clobbers B14 or an A1x/B1x register, the firmware
;* resumes with a corrupted data pointer, which is a freeze on boot.
;*
;* We inline the same pushes instead of calling __push_rts: the RTS helper would
;* be an external symbol and therefore a RELOCATION, and this loader tolerates
;* exactly zero of those (docs/SAFE-DSP-RULES.md).
;*
;* STILL UNMODELLED, and the reason this is a candidate and not a certainty: the
;* ctx[34]/ctx[35] setup calls above run BEFORE the handlers in every stock _init.
;* If ctx[34] is what makes the param block valid, our handlers run against an
;* uninitialised one. Ziddle leaves ctx[34]/[35] unmodelled (Unmodeled::Zero), so
;* the emulator cannot answer this. Flash on MatProbe first.
;*
;* WHY THE CTX LIVES ON THE STACK, not in A10:
;*   Each edit handler tail-branches into ctx[7] -- a FIRMWARE routine, under no
;*   obligation to honour our ABI -- so A10 is not ours to rely on even now that
;*   we save it. Reloading before every call costs four cycles and removes the
;*   whole class of failure. (Stock keeps ctx in A10; stock's handlers are also
;*   stock's own code.)
;*
;* Assembled by TI's own toolchain rather than hand-encoded, and turned into the
;* byte templates in build/linker.py by build/gen_init_materialize.py: a wrong
;* _init needs an Effect Manager rewrite to recover, and hand-punched machine
;* code is how you get a wrong _init.
;*
;* LAYOUT: prologue, one call block per knob, epilogue -- every chunk 32-byte
;* ALIGNED. The alignment is load-bearing: ADDKPC resolves against the FETCH
;* PACKET base, not the instruction, so "return to the next block" is only a
;* constant if every block starts on a packet boundary. Chunk SIZES are measured
;* from the symbol table by the generator, not assumed, so the prologue is free
;* to need more than one packet.

;* No compact (16-bit) instructions. The assembler is free to compact, and did:
;* the epilogue came out 24 bytes, breaking the 32-byte packet invariant the
;* ADDKPC return depends on. Fixed-width encodings make every chunk's size a
;* simple count of instructions, and cost nothing here -- this runs once, at load.
        .nocmp

        .global _zdl_init_materialize
        .global _zdl_init_call_block
        .global _zdl_init_epilogue
        .global _zdl_init_end

;* ---- prologue: save the callee-saved set, then push the ctx ---------------
;* Push order (deepest first) must be mirrored exactly by the epilogue.
;* Every slot is 8 bytes, so B15 stays doubleword-aligned for the STDWs.
        .align 32
_zdl_init_materialize:
        STW.D2T2    B14, *B15--[2]      ; data-page pointer
        STDW.D2T1   A15:A14, *B15--[1]
        STDW.D2T2   B13:B12, *B15--[1]
        STDW.D2T1   A13:A12, *B15--[1]
        STDW.D2T2   B11:B10, *B15--[1]
        STDW.D2T1   A11:A10, *B15--[1]
        STDW.D2T2   B3:B2, *B15--[1]    ; return address (+ B2)
        STW.D2T1    A4, *B15--[2]       ; ctx, pushed LAST -> reads back at *+B15[2]
        NOP         5

;* ---- one call block per knob; the linker repeats and patches this ---------
;*
;* GUARDED, and this is the whole point of v4.
;*
;* P0 (this frame with ZERO calls between prologue and epilogue) boots fine on
;* hardware, in every slot. So the frame is sound and all three earlier freezes
;* happened in the handler calls. Disassembling our own generated handler says
;* why they might:
;*
;*     Fx_DLY_MatProb_Gain_edit:
;*         MV    A4,A7               ; A7 = ctx
;*         LDW   *+A7[31],B31        ; B31 = ctx[31]  -- a FIRMWARE pointer
;*         CALLP __call_stub         ; -> ctx[31](...)
;*         CALLP __call_stub         ; -> ctx[31](...)
;*
;* EVERY edit handler indirect-calls ctx[31]. If the firmware has not filled that
;* slot in by the time _init runs, the handler branches to whatever is there --
;* freeze on boot. Ziddle cannot see this: it models ctx[31] as always present
;* (callback_ctx31_readknob), so the emulator has no null to trip over.
;*
;* So: load ctx[31] and skip the call when it is zero. A skipped call materializes
;* nothing -- the old, known, survivable failure -- while a branch into a null
;* pointer is a brick. Strictly safer in both directions, which is why the guard
;* belongs in the shipping version too and not just the probe.
;*
;* The predicate must be A1/A2/B0/B1/B2 -- A5 and friends cannot predicate.
        .align 32
_zdl_init_call_block:
        LDW.D2T1    *+B15[2], A4        ; reload ctx -- 4 delay slots before use
        NOP                             ; preserve block layout
        NOP
        NOP         2                   ; ctx lands in A4 here
        LDW.D1T1    *+A4[31], A1        ; A1 = ctx[31], the callback the handler calls
        NOP         4                   ; A1 lands here
 [!A1]  B.S2        _zdl_init_next      ; firmware table not ready -> skip, do not brick
        NOP         5                   ; the skip's delay slots
        B.S2        _zdl_init_call_block ; patched PC-relative handler target
        ADDKPC.S2   _zdl_init_next, B3, 0 ; delay 1: return addr, PC-relative
        NOP         4                   ; delays 2-5
_zdl_init_next:

;* ---- epilogue: pop everything in reverse, then return ---------------------
        .align 32
_zdl_init_epilogue:
        LDW.D2T1    *++B15[2], A4       ; pop ctx (value unused from here)
        LDDW.D2T2   *++B15[1], B3:B2
        LDDW.D2T1   *++B15[1], A11:A10
        LDDW.D2T2   *++B15[1], B11:B10
        LDDW.D2T1   *++B15[1], A13:A12
        LDDW.D2T2   *++B15[1], B13:B12
        LDDW.D2T1   *++B15[1], A15:A14
        LDW.D2T2    *++B15[2], B14
        NOP         4                   ; B14 (and B3) land before the branch
        B.S2        B3
        NOP         5
        .align 32
_zdl_init_end:

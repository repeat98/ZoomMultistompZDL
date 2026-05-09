/*
 * gain.c — minimal 1-knob "GAIN" plugin for Zoom MS-70CDR
 *
 * The simplest possible custom-built ZDL: pass-through with a Level knob.
 * Used to validate the v2 full-ELF builder pipeline end-to-end and to
 * settle the open ABI question of whether the firmware auto-populates
 * params[5] (the first knob) when handlers are NOP_RETURN stubs.
 *
 *
 * Audio context layout (verified against three from-scratch effects in
 * zoom-fx-modding-ref/diy/{rainsel,rtfm,div0}.asm — see ABI.md §5.3.a):
 *
 *   A4 = ctx (state pointer; arg 0)
 *     ctx[1]   →  parameters table (float*)
 *     ctx[4]   →  Dry buffer    (float*) — raw guitar input
 *     ctx[5]   →  Fx  buffer    (float*) — upstream-modified signal
 *     ctx[6]   →  Output buffer (float*) — accumulator (ADD into this)
 *     ctx[11]  →  "magic dst"   — must shuttle bytes from ctx[12]
 *     ctx[12]  →  "magic src"   — purpose unknown; preserve to be safe
 *
 *   params[0]  on/off (1.0 or 0.0 float)
 *   params[4]  level multiplier (= 1/max; 0.01 for max=100)
 *   params[5]  raw knob value (0..max as float)
 *
 *   Block size: 8 samples per channel × 2 channels = 16 floats per call,
 *   channel-interleaved as LLLLLLLL RRRRRRRR.
 *
 * DSP:
 *   gain = params[5] * params[4] * params[0]    // normalized 0..1, 0 when off
 *   for each sample s in Fx:  Output[s] += s * gain
 *
 * Build (from the v2 root):
 *   cl6x --c99 --opt_level=2 --opt_for_space=3 -mv6740 --abi=eabi \
 *        --mem_model:data=far -c gain/gain.c -o gain/gain.obj
 *   dis6x gain/gain.obj gain/gain.dis.asm
 *   python3 build/extract_opcodes.py gain/gain.dis.asm gain/gain.opcodes.hex
 *   python3 gain/build.py
 */

#include <stdint.h>

/* Place the audio function in its own .audio section so the linker
 * knows which bytes to splice into the ZDL's audio segment. */
#pragma CODE_SECTION(Fx_FLT_GAIN, ".audio")

#define ZDL_PTR(type, word)  ((type)(uintptr_t)(word))

/* REAL DSP BUILD: knob-controlled additive gain.
 *
 * Spliced LineSel onf + EfxLvl_edit + OutLvl_edit handlers populate:
 *   params[0]  = on/off mult (1.0 / 0.0)        ← onf handler
 *   params[5]  = Level knob  (raw, scaling TBD) ← knob1_edit handler
 *   params[6]  = Mix knob    (raw, scaling TBD) ← knob2_edit handler
 *
 * params[4] (the level multiplier) is NOT populated because we skip the
 * init handler (LineSel's init has unresolved Coe-table references). So
 * we ignore params[4] here and read the raw values.
 *
 * DSP: out += fx * params[5] * params[0]
 *   Bypass-on  : params[0]=0 → no contribution.
 *   Knob at 0  : params[5]=0 → no contribution.
 *   Knob at max: scaled by whatever range the LineSel handler emits.
 */
void Fx_FLT_GAIN(unsigned int *ctx)
{
    float        *params   = ZDL_PTR(float        *, ctx[1]);
    float        *fxBuf    = ZDL_PTR(float        *, ctx[5]);
    float        *outBuf   = ZDL_PTR(float        *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    /* params[5] from LineSel's EfxLvl_edit handler is divided by an
     * undocumented host-side scale (~ the magic float 0x44306666).
     * Without running init (which would populate params[4] as the
     * compensating multiplier), the value here is small — observed ~0.14
     * at full knob, giving a barely-audible boost. We scale by 8x as a
     * first guess; tune until full-knob == full pass-through doubling. */
    float onoff = params[0];
    float lvl   = params[5] * onoff * 8.0f;

    int i;
    for (i = 0; i < 16; i++) {
        outBuf[i] += fxBuf[i] * lvl;
    }
}

#ifndef ZOOM_EDIT_HANDLERS_H
#define ZOOM_EDIT_HANDLERS_H

/*
 * Generic Zoom edit handler.
 *
 * The firmware calls this when a knob changes. This stock-derived sequence
 * asks the host for knob_id and writes the raw float to params at
 * param_byte_off. params[5] is byte offset 20, params[6] is 24, etc.
 */
asm("        .ref __c6xabi_call_stub");
asm("        .sect \".text\"");

#define ZOOM_EDIT_HANDLER(sym, knob_id, param_byte_off) \
asm("        .global " #sym); \
asm(#sym ":"); \
asm("        STW.D2T2      B3,*B15--[2]"); \
asm("        MV.L1         A4,A7"); \
asm("        LDW.D1T2      *+A7[31],B31"); \
asm("        LDW.D1T1      *A7[1],A0"); \
asm("        LDW.D1T1      *A7[0],A4"); \
asm("        CALLP.S2      __c6xabi_call_stub,B3"); \
asm("        MVK.L2        " #knob_id ",B4"); \
asm("        MVK.S1        151,A6"); \
asm("        MV.L1         A4,A8"); \
asm("        MVK.S1        255,A4"); \
asm("        CALLP.S2      __c6xabi_call_stub,B3"); \
asm("        LDW.D1T2      *+A7[21],B31"); \
asm("        SHL.S1        A4,0x16,A4"); \
asm("        MVK.L2        0,B4"); \
asm("        MVK.D2        0,B6"); \
asm("        LDW.D1T1      *A7[7],A3"); \
asm("        LDW.D2T2      *++B15[2],B3"); \
asm("        MVK.S2        0x6666,B5"); \
asm("        MVKH.S2       0x44300000,B5"); \
asm("        MV.L2X        A4,B4"); \
asm("        B.S2X         A3"); \
asm("        MVK.S1        " #param_byte_off ",A4"); \
asm("        ADD.L1        A0,A4,A4"); \
asm("        MV.L1X        B5,A6"); \
asm("        NOP           2")

#endif

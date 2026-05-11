#include <stdint.h>

asm("        .ref __c6xabi_call_stub");
asm("        .sect \".text\"");
asm("        .global Fx_FLT_HELLO_Knob3_edit");
asm("Fx_FLT_HELLO_Knob3_edit:");
asm("        STW.D2T2      B3,*B15--[2]");
asm("        MV.L1         A4,A7");
asm("        LDW.D1T2      *+A7[31],B31");
asm("        LDW.D1T1      *A7[1],A0");
asm("        LDW.D1T1      *A7[0],A4");
asm("        CALLP.S2      __c6xabi_call_stub,B3");
asm("        MVK.L2        4,B4");
asm("        MVK.S1        151,A6");
asm("        MV.L1         A4,A8");
asm("        MVK.S1        255,A4");
asm("        CALLP.S2      __c6xabi_call_stub,B3");
asm("        LDW.D1T2      *+A7[21],B31");
asm("        SHL.S1        A4,0x16,A4");
asm("        MVK.L2        0,B4");
asm("        MVK.D2        0,B6");
asm("        LDW.D1T1      *A7[7],A3");
asm("        LDW.D2T2      *++B15[2],B3");
asm("        MVK.S2        0x6666,B5");
asm("        MVKH.S2       0x44300000,B5");
asm("        MV.L2X        A4,B4");
asm("        B.S2X         A3");
asm("        MVK.S1        28,A4");
asm("        ADD.L1        A0,A4,A4");
asm("        MV.L1X        B5,A6");
asm("        NOP           2");

#pragma CODE_SECTION(Fx_FLT_Hello, ".audio")
void Fx_FLT_Hello(uint32_t *ctx) {
    // ctx[4/5/6] = dry/fx/out buffers
    float *fx  = (float *)ctx[5];
    float *out = (float *)ctx[6];
    
    // params[0] is On/Off
    float *params = (float *)ctx[1];
    float onoff = params[0];

    // Pass audio through, scaled by on/off
    for (int i = 0; i < 16; i++) {
        out[i] += fx[i] * onoff;
    }
}

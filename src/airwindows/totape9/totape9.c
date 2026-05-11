/*
 * totape9_zoom.c
 *
 * ToTape9 by Chris Johnson (airwindows) – MIT licence
 * Ported to TI TMS320C674x for Zoom Multistomp (MS-50G / MS-60B / MS-70CDR)
 *
 * Assumptions
 * -----------
 *  - Sample rate is 44100 Hz  →  overallscale = 1.0, spacing = 1, slewsing = 2
 *    Only the avg2 stage of TapeHack2 is active; avg4/8/16/32 stages are dead code
 *    at this sample rate and are omitted entirely.
 *  - Single instance.  All state is static.
 *  - The Zoom firmware calls this function with a pointer to a context structure
 *    in register A4 (first argument by C674x calling convention).
 *  - Knobs are on three pages, three knobs each (IDs 2-10):
 *
 *    Page 1  ID2 = Input     A3[5]   0-1  → gain 0-4×
 *            ID3 = Tilt      A3[6]   0-1  → dubly encode/decode amount
 *            ID4 = Shape     A3[7]   0-1  → IIR frequency for dubly
 *    Page 2  ID5 = Flutter   A3[8]   0-1  → tape flutter depth
 *            ID6 = FlutSpd   A3[9]   0-1  → flutter LFO speed
 *            ID7 = Bias      A3[10]  0-1  → tape bias (0=dark, 0.5=neutral, 1=bright)
 *    Page 3  ID8 = HeadBump  A3[11]  0-1  → head-bump resonance amount
 *            ID9 = HeadFrq   A3[12]  0-1  → head-bump freq (maps 0-1 → 25-200 Hz)
 *            ID10= Output    A3[13]  0-1  → output gain 0-2×
 *
 *    A3[0]  = on/off multiplier (1.0 when on, 0.0 when off)
 *    A3[4]  = knob level multiplier  (so knob value 100 → 1.0)
 *
 * Build (TI Code Composer Studio, Generic C674x device, compiler 8.3.x, Release)
 * -------------------------------------------------------------------------------
 *   cl6x -o3 -mv6740 --abi=eabi --mem_model:data=far \
 *         -c totape9_zoom.c -o totape9_zoom.obj
 *   dis6x totape9_zoom.obj totape9_zoom_dis.asm
 *   python3 totape9/apply_relocs.py          → produces totape9/TOTAPE9.ZDL
 *
 *   NOTE: --mem_model:data=far is REQUIRED.  Without it the compiler places
 *   small static variables in .bss and accesses them via B14-relative (SBR)
 *   addressing.  The Zoom firmware does not set B14 to a valid address before
 *   calling .audio, so all state accesses would hit garbage memory.
 *   With --mem_model:data=far every variable goes into a .far:* section and
 *   is addressed with an absolute MVKL/MVKH pair – safe and linker-independent.
 */

/* #include <math.h>  -- replaced with inline implementations below */
#include <stdint.h>

/* =========================================================================
 * Inline math functions
 *
 * The Zoom ZDL runtime does not provide sinf/logf/tanf.  No stock Zoom
 * effect uses them, so they are not in the firmware's RTS.  We provide
 * lightweight inline versions here so the compiler folds them into the
 * .audio section and no external symbol reference is generated.
 *
 * __c6xabi_divf (float divide) IS available – we extract it from stock
 * ZDL binaries where it's statically linked.  So the `/` operator is fine.
 *
 * Accuracy targets:  ~20-bit mantissa (sufficient for audio, IEEE single
 * has 24-bit mantissa).  These are NOT fully IEEE-754 compliant – no
 * special-case handling for NaN/Inf/denormals.
 * ====================================================================== */

/* --- sinf: Bhaskara I approximation, max error ~0.0016 --------------- */
static float zoom_sinf(float x)
{
    /* Reduce x to [0, 2*pi) */
    const float TWO_PI  = 6.2831853f;
    const float PI      = 3.1415927f;
    const float INV_2PI = 0.15915494f;

    /* Range reduction: x = x mod 2*pi, result in [0, 2*pi) */
    x = x - TWO_PI * (float)(int)(x * INV_2PI);
    if (x < 0.0f) x += TWO_PI;

    /* Use symmetry to map to [0, pi] */
    float sign = 1.0f;
    if (x > PI) { x -= PI; sign = -1.0f; }

    /* Bhaskara I: sin(x) ≈ 16x(pi-x) / (5*pi^2 - 4x(pi-x))
       Max error ~0.0016 over [0, pi] */
    float pmx = PI - x;
    float xpmx = x * pmx;
    return sign * (16.0f * xpmx) / (49.348f - 4.0f * xpmx);
}

/* --- logf: bit-hack + polynomial correction -------------------------- */
static float zoom_logf(float x)
{
    /* Fast log2 via IEEE 754 float bit layout + correction polynomial.
       log(x) = log2(x) * ln(2) */
    union { float f; uint32_t u; } conv;
    conv.f = x;
    /* Extract exponent and mantissa */
    int exp = (int)((conv.u >> 23) & 0xFF) - 127;
    conv.u = (conv.u & 0x007FFFFFu) | 0x3F800000u;  /* m in [1, 2) */
    float m = conv.f;

    /* Minimax polynomial for log2(m) over [1, 2), ~20-bit accuracy */
    float log2_m = -1.7417939f + m * (2.8212026f + m * (-1.4699568f + m * 0.44717955f));

    /* log(x) = (exp + log2_m) * ln(2) */
    return ((float)exp + log2_m) * 0.6931472f;
}

/* --- tanf: sin/cos via paired Bhaskara ------------------------------- */
static float zoom_tanf(float x)
{
    /* tan(x) = sin(x) / cos(x) */
    const float HALF_PI = 1.5707963f;
    return zoom_sinf(x) / zoom_sinf(x + HALF_PI);
}

/* Redirect standard names */
#define sinf(x) zoom_sinf(x)
#define logf(x) zoom_logf(x)
#define tanf(x) zoom_tanf(x)

#pragma CODE_SECTION(Fx_FLT_ToTape9, ".audio")

/*
 * On the TI C674x (32-bit target) sizeof(unsigned int) == sizeof(void*) == 4,
 * so the pointer casts below are correct.  On a 64-bit host (used only for
 * syntax-checking) the compiler will warn; those warnings are expected and safe
 * to ignore.
 */
#define ZDL_PTR(type, word)  ((type)(uintptr_t)(word))

/* -------------------------------------------------------------------------
 * Constants
 * ---------------------------------------------------------------------- */

#define FLUTTER_BUF  502   /* must be > max flutter depth (498) + 2 */
#define PHI          1.6180339887498948f

/* -------------------------------------------------------------------------
 * gslew layout: 9 stages × 3 words = [prevL, prevR, threshold]  (27 words)
 * ---------------------------------------------------------------------- */
#define GSLEW_TOTAL  27

/* -------------------------------------------------------------------------
 * Head-bump biquad field indices  (hdb_total = 11)
 * ---------------------------------------------------------------------- */
#define HDB_FREQ  0
#define HDB_RESO  1
#define HDB_A0    2
#define HDB_A1    3
#define HDB_A2    4
#define HDB_B1    5
#define HDB_B2    6
#define HDB_SL1   7
#define HDB_SL2   8
#define HDB_SR1   9
#define HDB_SR2   10
#define HDB_TOTAL 11

/* =========================================================================
 * Persistent state (single-instance)
 * ====================================================================== */

/* Dubly encode */
static float iirEncL, iirEncR;
static float compEncL, compEncR;
static float avgEncL, avgEncR;

/* Dubly decode */
static float iirDecL, iirDecR;
static float compDecL, compDecR;
static float avgDecL, avgDecR;

/* Flutter */
static float dL[FLUTTER_BUF];
static float dR[FLUTTER_BUF];
static float sweepL  = 3.14159265358979f;  /* start at π, matching reference */
static float sweepR  = 3.14159265358979f;
static float nextmaxL = 0.5f;              /* must be non-zero or sweep never advances */
static float nextmaxR = 0.5f;
static int   gcount;

/* Bias slew */
static float gslew[GSLEW_TOTAL];

/* Hysteresis */
static float hysteresisL, hysteresisR;

/* TapeHack2 – avg2 only at 44100 Hz */
static float avg2L[2],  avg2R[2];
static float post2L[2], post2R[2];
static int   avgPos;
static float lastDarkL, lastDarkR;

/* Head bump */
static float headBumpL,  headBumpR;
static float hdbA[HDB_TOTAL], hdbB[HDB_TOTAL];

/* ClipOnly3  (spacing = 1) */
static float lastSampL, lastSampR;
static float intermedL, intermedR;
static float slewArrL[2], slewArrR[2];
static int   wasPosClipL, wasNegClipL;
static int   wasPosClipR, wasNegClipR;

/* =========================================================================
 * Head-bump biquad coefficient calculation
 * ====================================================================== */

static void computeHDB(float *hdb, float normalizedFreq, float reso)
{
    hdb[HDB_FREQ] = normalizedFreq;
    hdb[HDB_RESO] = reso;
    hdb[HDB_A1]   = 0.0f;
    float K    = tanf(3.14159265358979323f * normalizedFreq);
    float norm = 1.0f / (1.0f + K / reso + K * K);
    hdb[HDB_A0] =  K / reso * norm;
    hdb[HDB_A2] = -hdb[HDB_A0];
    hdb[HDB_B1] =  2.0f * (K * K - 1.0f) * norm;
    hdb[HDB_B2] =  (1.0f - K / reso + K * K) * norm;
}

/* =========================================================================
 * Main entry point
 *
 * ctx layout (words, matching existing Zoom .audio asm):
 *   ctx[1]  – parameter structure pointer
 *   ctx[4]  – Dry buffer pointer
 *   ctx[5]  – Fx  buffer pointer
 *   ctx[11] – magic destination (indirected, write once)
 *   ctx[12] – magic source      (read once per loop iteration)
 * ====================================================================== */

void Fx_FLT_ToTape9(unsigned int *ctx)
{
    /* --- Decode context structure --- */
    unsigned int *params   = ZDL_PTR(unsigned int *, ctx[1]);
    float        *fxBuf    = ZDL_PTR(float *,        ctx[5]);  /* L:[0..7] R:[8..15] */

    /* Magic pass-through (bookkeeping value the firmware expects) */
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);

    /* --- Load knob values (all 0-1 after multiplying by levelMul) --- */
    float levelMul = *(float *)&params[4];

    float pInput   = *(float *)&params[5]  * levelMul;  /* Page 1 */
    float pTilt    = *(float *)&params[6]  * levelMul;
    float pShape   = *(float *)&params[7]  * levelMul;
    float pFlutter = *(float *)&params[8]  * levelMul;  /* Page 2 */
    float pFlutSpd = *(float *)&params[9]  * levelMul;
    float pBias    = *(float *)&params[10] * levelMul;
    float pHeadBmp = *(float *)&params[11] * levelMul;  /* Page 3 */
    float pHeadFrq = *(float *)&params[12] * levelMul;
    float pOutput  = *(float *)&params[13] * levelMul;
    float onoff    = *(float *)&params[0];               /* 1.0 on / 0.0 off */

    /* --- Derive algorithm parameters (matching ToTape9 formulas exactly)
     *     overallscale = 1.0 throughout                                  --- */

    float inputGain    = pInput * 2.0f; inputGain = inputGain * inputGain;

    float dublyAmount  = pTilt * 2.0f;
    float outlyAmount  = (1.0f - pTilt) * -2.0f;
    if (outlyAmount < -1.0f) outlyAmount = -1.0f;

    float iirEncFreq   = 1.0f - pShape;
    float iirDecFreq   = pShape;

    /* pow(D,6)*50, clamped to FLUTTER_BUF-2 */
    float fd = pFlutter * pFlutter;
    fd = fd * fd * fd;                           /* D^6 */
    float flutDepth    = fd * 50.0f;
    if (flutDepth > (float)(FLUTTER_BUF - 2)) flutDepth = (float)(FLUTTER_BUF - 2);

    float flutFreq     = 0.02f * pFlutSpd * pFlutSpd * pFlutSpd;

    float bias         = pBias * 2.0f - 1.0f;   /* –1 … +1 */
    float underBias    = bias * bias; underBias = underBias * underBias * 0.25f;
    float overBias     = (1.0f - bias); overBias = overBias * overBias * overBias;
    if (bias > 0.0f) underBias = 0.0f;
    if (bias < 0.0f) overBias  = 1.0f;

    /* Cascade gslew thresholds (every 3rd slot = threshold slot).
     * Reference assigns threshold9 (gslew[26]) the smallest value and
     * threshold1 (gslew[2]) the largest, so early stages are most permissive. */
    {
        float ob = overBias;
        gslew[26] = ob; ob *= PHI;   /* threshold9 – smallest */
        gslew[23] = ob; ob *= PHI;
        gslew[20] = ob; ob *= PHI;
        gslew[17] = ob; ob *= PHI;
        gslew[14] = ob; ob *= PHI;
        gslew[11] = ob; ob *= PHI;
        gslew[8]  = ob; ob *= PHI;
        gslew[5]  = ob; ob *= PHI;
        gslew[2]  = ob;              /* threshold1 – largest  */
    }

    float headBumpDrive = pHeadBmp * 0.1f;
    float headBumpMix   = pHeadBmp * 0.5f;

    /* HeadFrq: 0-1 → 25-200 Hz, normalised by 44100 */
    float hfA = (25.0f + pHeadFrq * 175.0f) / 44100.0f;
    float hfB = hfA * 0.9375f;
    float reso = 0.6180339887498948f;
    computeHDB(hdbA, hfA, reso);
    computeHDB(hdbB, hfB, reso);

    float outputGain = pOutput * 2.0f;

    /* --- Process 8 stereo sample-pairs --- */
    float *fxL = fxBuf;       /* samples 0-7  */
    float *fxR = fxBuf + 8;   /* samples 8-15 */

    for (int i = 0; i < 8; i++)
    {
        *magicDst = magicSrc[i];
        float sL = fxL[i];
        float sR = fxR[i];

        /* == Input gain == */
        sL *= inputGain;
        sR *= inputGain;

        /* ================================================================
         * Dubly encode
         * ============================================================= */
        {
            /* Left */
            iirEncL = iirEncL * (1.0f - iirEncFreq) + sL * iirEncFreq;
            float hpL = (sL - iirEncL) * 2.848f + avgEncL;
            avgEncL   = (sL - iirEncL) * 1.152f;
            if (hpL >  1.0f) hpL =  1.0f;
            if (hpL < -1.0f) hpL = -1.0f;
            float dubL = hpL < 0.0f ? -hpL : hpL;
            if (dubL > 0.0f) {
                float adj = logf(1.0f + 255.0f * dubL) / 2.40823996531f;
                if (adj > 0.0f) dubL /= adj;
                compEncL = compEncL * (1.0f - iirEncFreq) + dubL * iirEncFreq;
                sL += hpL * compEncL * dublyAmount;
            }
            /* Right */
            iirEncR = iirEncR * (1.0f - iirEncFreq) + sR * iirEncFreq;
            float hpR = (sR - iirEncR) * 2.848f + avgEncR;
            avgEncR   = (sR - iirEncR) * 1.152f;
            if (hpR >  1.0f) hpR =  1.0f;
            if (hpR < -1.0f) hpR = -1.0f;
            float dubR = hpR < 0.0f ? -hpR : hpR;
            if (dubR > 0.0f) {
                float adj = logf(1.0f + 255.0f * dubR) / 2.40823996531f;
                if (adj > 0.0f) dubR /= adj;
                compEncR = compEncR * (1.0f - iirEncFreq) + dubR * iirEncFreq;
                sR += hpR * compEncR * dublyAmount;
            }
        }

        /* ================================================================
         * Flutter  (shared gcount write pointer, per original)
         * ============================================================= */
        if (flutDepth > 0.0f) {
            if (gcount < 0 || gcount >= FLUTTER_BUF) gcount = FLUTTER_BUF - 1;

            dL[gcount] = sL;
            dR[gcount] = sR;

            /* Left read */
            {
                float offset = flutDepth + flutDepth * sinf(sweepL);
                sweepL += nextmaxL * flutFreq;
                if (sweepL > 6.28318530718f) {
                    sweepL -= 6.28318530718f;
                    nextmaxL = 0.5f; /* simplified: drop random variation */
                }
                int cnt = gcount + (int)offset;
                if (cnt >= FLUTTER_BUF) cnt -= FLUTTER_BUF;
                int cnt1 = cnt + 1;
                if (cnt1 >= FLUTTER_BUF) cnt1 -= FLUTTER_BUF;
                float frac = offset - (float)(int)offset;
                sL = dL[cnt] * (1.0f - frac) + dL[cnt1] * frac;
            }
            /* Right read */
            {
                float offset = flutDepth + flutDepth * sinf(sweepR);
                sweepR += nextmaxR * flutFreq;
                if (sweepR > 6.28318530718f) {
                    sweepR -= 6.28318530718f;
                    nextmaxR = 0.5f;
                }
                int cnt = gcount + (int)offset;
                if (cnt >= FLUTTER_BUF) cnt -= FLUTTER_BUF;
                int cnt1 = cnt + 1;
                if (cnt1 >= FLUTTER_BUF) cnt1 -= FLUTTER_BUF;
                float frac = offset - (float)(int)offset;
                sR = dR[cnt] * (1.0f - frac) + dR[cnt1] * frac;
            }

            gcount--;
        }

        /* ================================================================
         * Bias  (9-stage slew limiter, gslew[x]=prevL, [x+1]=prevR, [x+2]=thresh)
         * ============================================================= */
        if (bias < -0.001f || bias > 0.001f) {
            for (int x = 0; x < GSLEW_TOTAL; x += 3) {
                float thr = gslew[x + 2];

                if (underBias > 0.0f) {
                    float stuck;
                    stuck = (sL - gslew[x]   / 0.975f);
                    if (stuck < 0.0f) stuck = -stuck;
                    stuck /= underBias;
                    if (stuck < 1.0f) sL = sL * stuck + (gslew[x]   / 0.975f) * (1.0f - stuck);

                    stuck = (sR - gslew[x+1] / 0.975f);
                    if (stuck < 0.0f) stuck = -stuck;
                    stuck /= underBias;
                    if (stuck < 1.0f) sR = sR * stuck + (gslew[x+1] / 0.975f) * (1.0f - stuck);
                }

                if ((sL - gslew[x])   >  thr) sL = gslew[x]   + thr;
                if ((gslew[x]   - sL) >  thr) sL = gslew[x]   - thr;
                gslew[x]   = sL * 0.975f;

                if ((sR - gslew[x+1]) >  thr) sR = gslew[x+1] + thr;
                if ((gslew[x+1] - sR) >  thr) sR = gslew[x+1] - thr;
                gslew[x+1] = sR * 0.975f;
            }
        }

        /* ================================================================
         * Tiny hysteresis
         * ============================================================= */
        {
            float abL = sL < 0.0f ? -sL : sL;
            float apL = (1.0f - abL) * (1.0f - abL) * 0.012f;
            hysteresisL += sL * abL;
            if (hysteresisL >  0.011449f) hysteresisL =  0.011449f;
            if (hysteresisL < -0.011449f) hysteresisL = -0.011449f;
            hysteresisL *= 0.999f;
            sL += hysteresisL * apL;

            float abR = sR < 0.0f ? -sR : sR;
            float apR = (1.0f - abR) * (1.0f - abR) * 0.012f;
            hysteresisR += sR * abR;
            if (hysteresisR >  0.011449f) hysteresisR =  0.011449f;
            if (hysteresisR < -0.011449f) hysteresisR = -0.011449f;
            hysteresisR *= 0.999f;
            sR += hysteresisR * apR;
        }

        /* ================================================================
         * TapeHack2 – pre-distortion smoothing  (avg2 only at 44100 Hz)
         * ============================================================= */
        {
            int pos = avgPos & 1;

            /* Left */
            float darkL = sL;
            avg2L[pos]  = darkL;
            darkL       = (avg2L[0] + avg2L[1]) * 0.5f;
            float slewL = (lastDarkL - sL) < 0.0f ? (sL - lastDarkL) : (lastDarkL - sL);
            slewL *= 0.12f;
            if (slewL > 1.0f) slewL = 1.0f;
            slewL   = 1.0f - (1.0f - slewL) * (1.0f - slewL);
            sL      = sL * (1.0f - slewL) + darkL * slewL;
            lastDarkL = darkL;

            /* Right */
            float darkR = sR;
            avg2R[pos]  = darkR;
            darkR       = (avg2R[0] + avg2R[1]) * 0.5f;
            float slewR = (lastDarkR - sR) < 0.0f ? (sR - lastDarkR) : (lastDarkR - sR);
            slewR *= 0.12f;
            if (slewR > 1.0f) slewR = 1.0f;
            slewR   = 1.0f - (1.0f - slewR) * (1.0f - slewR);
            sR      = sR * (1.0f - slewR) + darkR * slewR;
            lastDarkR = darkR;

            /* ============================================================
             * TapeHack – Taylor-series sin() approximation  (clamp ±2.306)
             * ========================================================== */
            /* Left */
            if (sL >  2.305929007734908f) sL =  2.305929007734908f;
            if (sL < -2.305929007734908f) sL = -2.305929007734908f;
            {
                float a2 = sL * sL;
                float em = sL * a2;          /* x^3  */  sL -= em / 6.0f;
                em *= a2;                    /* x^5  */  sL += em / 69.0f;
                em *= a2;                    /* x^7  */  sL -= em / 2530.08f;
                em *= a2;                    /* x^9  */  sL += em / 224985.6f;
                em *= a2;                    /* x^11 */  sL -= em / 9979200.0f;
            }
            /* Right */
            if (sR >  2.305929007734908f) sR =  2.305929007734908f;
            if (sR < -2.305929007734908f) sR = -2.305929007734908f;
            {
                float a2 = sR * sR;
                float em = sR * a2;          sR -= em / 6.0f;
                em *= a2;                    sR += em / 69.0f;
                em *= a2;                    sR -= em / 2530.08f;
                em *= a2;                    sR += em / 224985.6f;
                em *= a2;                    sR -= em / 9979200.0f;
            }

            /* TapeHack2 – post-distortion smoothing (avg2 only) */
            post2L[pos] = sL;
            float postDL = (post2L[0] + post2L[1]) * 0.5f;
            sL = sL * (1.0f - slewL) + postDL * slewL;

            post2R[pos] = sR;
            float postDR = (post2R[0] + post2R[1]) * 0.5f;
            sR = sR * (1.0f - slewR) + postDR * slewR;

            avgPos++;
        }

        /* ================================================================
         * Head bump  (nonlinear accumulator + two cascaded biquads)
         * ============================================================= */
        if (headBumpMix > 0.0f) {
            /* Left */
            headBumpL += sL * headBumpDrive;
            headBumpL -= headBumpL * headBumpL * headBumpL * 0.0618f;
            float biqL  = headBumpL * hdbA[HDB_A0] + hdbA[HDB_SL1];
            hdbA[HDB_SL1] = headBumpL * hdbA[HDB_A1] - biqL * hdbA[HDB_B1] + hdbA[HDB_SL2];
            hdbA[HDB_SL2] = headBumpL * hdbA[HDB_A2] - biqL * hdbA[HDB_B2];
            float hbsL  = biqL * hdbB[HDB_A0] + hdbB[HDB_SL1];
            hdbB[HDB_SL1] = biqL * hdbB[HDB_A1] - hbsL * hdbB[HDB_B1] + hdbB[HDB_SL2];
            hdbB[HDB_SL2] = biqL * hdbB[HDB_A2] - hbsL * hdbB[HDB_B2];
            sL += hbsL * headBumpMix;

            /* Right */
            headBumpR += sR * headBumpDrive;
            headBumpR -= headBumpR * headBumpR * headBumpR * 0.0618f;
            float biqR  = headBumpR * hdbA[HDB_A0] + hdbA[HDB_SR1];
            hdbA[HDB_SR1] = headBumpR * hdbA[HDB_A1] - biqR * hdbA[HDB_B1] + hdbA[HDB_SR2];
            hdbA[HDB_SR2] = headBumpR * hdbA[HDB_A2] - biqR * hdbA[HDB_B2];
            float hbsR  = biqR * hdbB[HDB_A0] + hdbB[HDB_SR1];
            hdbB[HDB_SR1] = biqR * hdbB[HDB_A1] - hbsR * hdbB[HDB_B1] + hdbB[HDB_SR2];
            hdbB[HDB_SR2] = biqR * hdbB[HDB_A2] - hbsR * hdbB[HDB_B2];
            sR += hbsR * headBumpMix;
        }

        /* ================================================================
         * Dubly decode
         * ============================================================= */
        {
            /* Left */
            iirDecL = iirDecL * (1.0f - iirDecFreq) + sL * iirDecFreq;
            float hpL = (sL - iirDecL) * 2.628f + avgDecL;
            avgDecL   = (sL - iirDecL) * 1.372f;
            if (hpL >  1.0f) hpL =  1.0f;
            if (hpL < -1.0f) hpL = -1.0f;
            float dubL = hpL < 0.0f ? -hpL : hpL;
            if (dubL > 0.0f) {
                float adj = logf(1.0f + 255.0f * dubL) / 2.40823996531f;
                if (adj > 0.0f) dubL /= adj;
                compDecL = compDecL * (1.0f - iirDecFreq) + dubL * iirDecFreq;
                sL += hpL * compDecL * outlyAmount;
            }
            /* Right */
            iirDecR = iirDecR * (1.0f - iirDecFreq) + sR * iirDecFreq;
            float hpR = (sR - iirDecR) * 2.628f + avgDecR;
            avgDecR   = (sR - iirDecR) * 1.372f;
            if (hpR >  1.0f) hpR =  1.0f;
            if (hpR < -1.0f) hpR = -1.0f;
            float dubR = hpR < 0.0f ? -hpR : hpR;
            if (dubR > 0.0f) {
                float adj = logf(1.0f + 255.0f * dubR) / 2.40823996531f;
                if (adj > 0.0f) dubR /= adj;
                compDecR = compDecR * (1.0f - iirDecFreq) + dubR * iirDecFreq;
                sR += hpR * compDecR * outlyAmount;
            }
        }

        /* == Output gain == */
        sL *= outputGain;
        sR *= outputGain;

        /* ================================================================
         * ClipOnly3  (spacing = 1, so intermediate[] and slew[] are depth-1)
         * ============================================================= */
        /* Left */
        {
            float noise = 0.962f; /* simplified: omit PRNG, use fixed noise factor */
            if (wasPosClipL) {
                if (sL < lastSampL) lastSampL = 0.9085097f * noise + sL * (1.0f - noise);
                else                lastSampL = 0.94f;
            }
            wasPosClipL = 0;
            if (sL > 0.9085097f)  { wasPosClipL = 1; sL = 0.9085097f * noise + lastSampL * (1.0f - noise); }
            if (wasNegClipL) {
                if (sL > lastSampL) lastSampL = -0.9085097f * noise + sL * (1.0f - noise);
                else                lastSampL = -0.94f;
            }
            wasNegClipL = 0;
            if (sL < -0.9085097f) { wasNegClipL = 1; sL = -0.9085097f * noise + lastSampL * (1.0f - noise); }

            slewArrL[1] = slewArrL[0];
            slewArrL[0] = lastSampL - sL;
            if (slewArrL[0] < 0.0f) slewArrL[0] = -slewArrL[0];
            intermedL   = sL;
            sL          = lastSampL;
            lastSampL   = intermedL;

            float fs = slewArrL[0] > slewArrL[1] ? slewArrL[0] : slewArrL[1];
            float pc = 0.94f / (1.0f + fs * 1.3986013f);
            if (sL >  pc) sL =  pc;
            if (sL < -pc) sL = -pc;
        }
        /* Right */
        {
            float noise = 0.962f;
            if (wasPosClipR) {
                if (sR < lastSampR) lastSampR = 0.9085097f * noise + sR * (1.0f - noise);
                else                lastSampR = 0.94f;
            }
            wasPosClipR = 0;
            if (sR > 0.9085097f)  { wasPosClipR = 1; sR = 0.9085097f * noise + lastSampR * (1.0f - noise); }
            if (wasNegClipR) {
                if (sR > lastSampR) lastSampR = -0.9085097f * noise + sR * (1.0f - noise);
                else                lastSampR = -0.94f;
            }
            wasNegClipR = 0;
            if (sR < -0.9085097f) { wasNegClipR = 1; sR = -0.9085097f * noise + lastSampR * (1.0f - noise); }

            slewArrR[1] = slewArrR[0];
            slewArrR[0] = lastSampR - sR;
            if (slewArrR[0] < 0.0f) slewArrR[0] = -slewArrR[0];
            intermedR   = sR;
            sR          = lastSampR;
            lastSampR   = intermedR;

            float fs = slewArrR[0] > slewArrR[1] ? slewArrR[0] : slewArrR[1];
            float pc = 0.94f / (1.0f + fs * 1.3986013f);
            if (sR >  pc) sR =  pc;
            if (sR < -pc) sR = -pc;
        }

        /* ================================================================
         * Write back, scaled by on/off
         * ============================================================= */
        fxL[i] = sL * onoff;
        fxR[i] = sR * onoff;
    }
    /* (no return value; jump to B3 handled by compiler epilogue) */
}

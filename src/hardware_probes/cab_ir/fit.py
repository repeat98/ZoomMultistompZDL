"""Fit a cabinet IR as a short minimum-phase FIR plus a cascade of biquads.

The HYBRID IR approach (github.com/Leemuzhko/HYBRID-IR): a long FIR is the
expensive, literal way to play a cabinet. Most of a cab's character is a few
broad features -- the low resonance, the high roll-off, two or three mid
bumps/dips -- which a handful of biquads reproduce at 5 multiplies each, and
the fine structure that remains is short once it is made minimum-phase.

    fit(ir, sr)       -> Fit (biquads, fir, gain, errors)
    response_db(...)  -> magnitude of any model on a frequency grid

Stage 1 fits HPF + LPF + peaking biquads to the 1/6-octave-smoothed target
magnitude (dB, log-frequency grid, least squares). Stage 2 designs an N-tap
minimum-phase FIR for what the biquads left (cepstral method), so the FIR only
carries fine detail. Phase is minimum, not the original: inaudible for a cab
in practice, and it is what lets the FIR be this short.
"""
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import least_squares
from scipy.signal import resample_poly, sosfreqz

FS = 44100
NFFT = 1 << 15


def load(path):
    import soundfile as sf
    x, sr = sf.read(str(path))
    if x.ndim > 1:
        x = x.mean(axis=1)
    if sr == 48000:
        x = resample_poly(x, 147, 160)
    elif sr != FS:
        raise SystemExit(f'{path}: {sr} Hz; supply 44.1 or 48 kHz')
    x = np.asarray(x, float)
    peak = np.max(np.abs(x))
    first = int(np.argmax(np.abs(x) > peak * 1e-3))      # trim silence before the onset
    return x[max(0, first - 2):]


def smooth_db(mag, frac=6):
    """Fractional-octave smoothing of |H| (power average), returned in dB."""
    f = np.arange(len(mag)) * FS / (2 * (len(mag) - 1))
    p = mag ** 2
    c = np.concatenate([[0], np.cumsum(p)])
    out = np.empty_like(mag)
    k = 2 ** (1 / (2 * frac))
    for i, fi in enumerate(f):
        lo = int(np.searchsorted(f, fi / k)); hi = max(lo + 1, int(np.searchsorted(f, fi * k)))
        out[i] = (c[hi] - c[lo]) / (hi - lo)
    return 10 * np.log10(np.maximum(out, 1e-20))


# --- biquads (RBJ cookbook), as [b0,b1,b2,1,a1,a2] sos rows ----------------
def _norm(b, a):
    return np.array([b[0] / a[0], b[1] / a[0], b[2] / a[0], 1.0, a[1] / a[0], a[2] / a[0]])


def peak(f, g, q):
    A = 10 ** (g / 40); w = 2 * np.pi * f / FS; al = np.sin(w) / (2 * q)
    return _norm([1 + al * A, -2 * np.cos(w), 1 - al * A], [1 + al / A, -2 * np.cos(w), 1 - al / A])


def lowpass(f, q):
    w = 2 * np.pi * f / FS; al = np.sin(w) / (2 * q); c = np.cos(w)
    return _norm([(1 - c) / 2, 1 - c, (1 - c) / 2], [1 + al, -2 * c, 1 - al])


def highpass(f, q):
    w = 2 * np.pi * f / FS; al = np.sin(w) / (2 * q); c = np.cos(w)
    return _norm([(1 + c) / 2, -(1 + c), (1 + c) / 2], [1 + al, -2 * c, 1 - al])


def high_shelf(f, g, q=0.707):
    A = 10 ** (g / 40); w = 2 * np.pi * f / FS; al = np.sin(w) / (2 * q); c = np.cos(w); s = 2 * np.sqrt(A) * al
    return _norm([A * ((A + 1) + (A - 1) * c + s), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - s)],
                 [(A + 1) - (A - 1) * c + s, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - s])


def sos_db(sos, freqs):
    if len(sos) == 0:
        return np.zeros_like(freqs)
    _, h = sosfreqz(np.array(sos), worN=freqs, fs=FS)
    return 20 * np.log10(np.maximum(np.abs(h), 1e-12))


def _build(p, n_peaks):
    sos = [highpass(np.exp(p[0]), p[1]), lowpass(np.exp(p[2]), p[3])]
    for i in range(n_peaks):
        f, g, q = p[4 + 3 * i: 7 + 3 * i]
        sos.append(peak(np.exp(f), g, q))
    return sos


def minphase_fir(target_db_full, taps):
    """N-tap minimum-phase FIR whose magnitude follows target_db_full (rfft grid)."""
    logmag = target_db_full / 20 * np.log(10)
    cep = np.fft.irfft(logmag, NFFT)
    fold = np.zeros(NFFT); fold[0] = cep[0]; fold[1:NFFT // 2] = 2 * cep[1:NFFT // 2]; fold[NFFT // 2] = cep[NFFT // 2]
    h = np.fft.irfft(np.exp(np.fft.rfft(fold)), NFFT)[:taps].copy()
    fade = max(4, taps // 4)
    h[-fade:] *= 0.5 * (1 + np.cos(np.linspace(0, np.pi, fade)))
    return h


@dataclass
class Fit:
    sos: list
    fir: np.ndarray
    gain: float
    freqs: np.ndarray = field(repr=False)
    target_db: np.ndarray = field(repr=False)
    model_db: np.ndarray = field(repr=False)

    def diff(self, lo=80, hi=8000):
        """model - target, 1/3-octave smoothed, level offset removed (Level is a knob)."""
        m = (self.freqs >= lo) & (self.freqs <= hi)
        d = self.model_db[m] - self.target_db[m]
        return d - d.mean()

    def error_db(self, lo=80, hi=8000):
        return float(np.sqrt(np.mean(self.diff(lo, hi) ** 2)))

    def max_error_db(self, lo=80, hi=8000):
        return float(np.max(np.abs(self.diff(lo, hi))))


def target_of(ir):
    mag = np.abs(np.fft.rfft(ir, NFFT))
    return smooth_db(mag, 6)


def fit(ir, taps=32, n_peaks=4, headroom_db=-3.0, loudness_db=0.0):
    full_f = np.fft.rfftfreq(NFFT, 1 / FS)
    tgt_full = target_of(ir)
    grid = np.geomspace(40, 18000, 240)
    tgt = np.interp(grid, full_f, tgt_full)
    w = np.where(grid > 10000, 0.3, 1.0)                    # the top octave matters least behind a cab

    ref = float(np.max(tgt))                                 # fit the shape, add the level at the end
    t = tgt - ref
    p0 = [np.log(70), 0.7, np.log(5000), 0.7]
    for f in (110, 450, 1500, 3200, 800, 2400)[:n_peaks]:
        p0 += [np.log(f), 0.0, 1.0]
    lo = [np.log(20), 0.3, np.log(1500), 0.3] + [np.log(40), -24, 0.2] * n_peaks
    hi = [np.log(400), 3.0, np.log(16000), 3.0] + [np.log(12000), 24, 8.0] * n_peaks
    res = least_squares(lambda p: w * (sos_db(_build(p, n_peaks), grid) - t), p0, bounds=(lo, hi))
    sos = _build(res.x, n_peaks)

    # Stage 2: add the FIR and refine everything together. The FIR starts as a
    # unit impulse, so the joint fit can only improve on stage 1. (A cepstral
    # FIR for the residual, windowed to N taps, made things worse: truncating it
    # smears the low-frequency part of the residual that the biquads own.)
    from scipy.signal import freqz
    if taps:
        def split(q):
            return q[:len(res.x)], q[len(res.x):]
        def err(q):
            bp, h = split(q)
            _, hf = freqz(h, worN=grid, fs=FS)
            return w * (sos_db(_build(bp, n_peaks), grid) + 20 * np.log10(np.maximum(np.abs(hf), 1e-9)) - t)
        q0 = np.concatenate([res.x, np.eye(1, taps)[0]])
        big = np.full(taps, 4.0)
        res2 = least_squares(err, q0, bounds=(np.concatenate([lo, -big]), np.concatenate([hi, big])))
        bp, fir = split(res2.x)
        sos = _build(bp, n_peaks)
    else:
        fir = np.array([1.0])

    def model(freqs):
        _, hf = __import__('scipy.signal', fromlist=['freqz']).freqz(fir, worN=freqs, fs=FS)
        return sos_db(sos, freqs) + 20 * np.log10(np.maximum(np.abs(hf), 1e-12))

    # Level: loudness-matched (pink spectrum, 80 Hz-6 kHz, in = out), as
    # tools/cab_loader.js. Peak-at-headroom_db normalisation left playing 7-9 dB
    # quiet, because the cab's low resonance is far above its mids.
    band = np.geomspace(80, 6000, 400)
    gain = 10 ** ((loudness_db - 10 * np.log10(np.mean(10 ** (model(band) / 10)))) / 20)
    third = np.geomspace(40, 18000, 300)
    tgt3 = np.interp(third, full_f, smooth_db(np.abs(np.fft.rfft(ir, NFFT)), 3)) - ref + headroom_db - float(np.max(tgt - ref))
    mod_full = model(np.maximum(full_f, 1e-3)) + 20 * np.log10(gain)
    mod3 = np.interp(third, full_f, smooth_db(10 ** (mod_full / 20), 3))
    return Fit(sos=sos, fir=fir, gain=gain, freqs=third, target_db=tgt3, model_db=mod3)


def truncated_fit(ir, taps=256, headroom_db=-3.0):
    """The current CabIR approach, for comparison: first N taps, faded."""
    full_f = np.fft.rfftfreq(NFFT, 1 / FS)
    h = ir[:taps].copy(); h[-32:] *= np.linspace(1, 0, 32)
    ref = float(np.max(np.interp(np.geomspace(40, 18000, 240), full_f, target_of(ir))))
    third = np.geomspace(40, 18000, 300)
    tgt3 = np.interp(third, full_f, smooth_db(np.abs(np.fft.rfft(ir, NFFT)), 3)) - ref
    mod3 = np.interp(third, full_f, smooth_db(np.abs(np.fft.rfft(h, NFFT)), 3)) - ref
    return Fit(sos=[], fir=h, gain=1.0, freqs=third, target_db=tgt3, model_db=mod3)

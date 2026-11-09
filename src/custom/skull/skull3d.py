"""A small 3D skull, rendered for the pedal's 128x64 1-bit screen.

Signed-distance model (cranium, face, cheekbones, sockets, nose, teeth, hinged
jaw), raymarched in numpy from a three-quarter view, lit from the upper left
with soft occlusion, then dithered to 1 bit. Original art for the Skull effect.
"""
import numpy as np

ASPECT = 1.4            # the LCD's pixels are ~1.4x taller than wide


def _len(v):
    return np.sqrt((v ** 2).sum(-1))


def ellipsoid(p, c, r):
    q = (p - c) / r
    k0 = _len(q)
    k1 = _len(q / r)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-6)


def rbox(p, c, b, r):
    q = np.abs(p - c) - b + r
    return _len(np.maximum(q, 0.0)) + np.minimum(np.maximum(q[..., 0], np.maximum(q[..., 1], q[..., 2])), 0.0) - r


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def smax(a, b, k):
    return -smin(-a, -b, k)


def rot_x(p, angle, pivot):
    c, s = np.cos(angle), np.sin(angle)
    q = p - pivot
    y = q[..., 1] * c - q[..., 2] * s
    z = q[..., 1] * s + q[..., 2] * c
    return np.stack([q[..., 0], y, z], -1) + pivot


def skull(p, jaw=0.0):
    """Distance to the skull; +z faces the viewer, +y up. jaw = opening in radians."""
    x = np.abs(p[..., 0:1])
    ps = np.concatenate([x, p[..., 1:]], -1)                   # mirror for symmetric parts
    d = ellipsoid(p, np.array([0, 0.18, -0.05]), np.array([0.47, 0.47, 0.56]))       # cranium
    d = smin(d, rbox(p, np.array([0, -0.2, 0.22]), np.array([0.25, 0.17, 0.2]), 0.08), 0.12)   # face
    base = smin(ellipsoid(p, np.array([0, -0.1, -0.22]), np.array([0.36, 0.26, 0.34])),       # skull base: no
                ellipsoid(ps, np.array([0.3, -0.24, -0.1]), np.array([0.07, 0.1, 0.08])), 0.08)  # overhang side on
    d = smin(d, base, 0.1)
    d = smin(d, ellipsoid(ps, np.array([0.3, -0.12, 0.2]), np.array([0.1, 0.075, 0.16])), 0.06)  # cheekbones
    d = smax(d, -ellipsoid(ps, np.array([0.47, -0.02, 0.05]), np.array([0.08, 0.16, 0.2])), 0.05)  # temples
    d = smax(d, -ellipsoid(ps, np.array([0.17, -0.03, 0.40]), np.array([0.135, 0.12, 0.24])), 0.03)  # eye sockets
    nose = ellipsoid(p, np.array([0, -0.21, 0.42]), np.array([0.065, 0.1, 0.18]))
    d = smax(d, -nose, 0.02)
    # upper teeth: a row of small boxes along the front of the face
    teeth = np.full(d.shape, 9.0)
    for i in range(-4, 5):
        a = i * 0.13
        c = np.array([0.24 * np.sin(a), -0.39, 0.13 + 0.24 * np.cos(a)])
        teeth = np.minimum(teeth, rbox(p, c, np.array([0.024, 0.045, 0.03]), 0.01))
    d = smin(d, teeth, 0.005)
    # jaw, hinged near the ears
    pj = rot_x(p, -jaw, np.array([0, -0.22, -0.05]))
    xj = np.abs(pj[..., 0:1]); pjs = np.concatenate([xj, pj[..., 1:]], -1)
    mand = rbox(pj, np.array([0, -0.53, 0.15]), np.array([0.23, 0.07, 0.2]), 0.06)
    mand = smax(mand, -rbox(pj, np.array([0, -0.53, 0.02]), np.array([0.16, 0.2, 0.17]), 0.04), 0.03)  # U shape
    ramus = rbox(pjs, np.array([0.25, -0.38, 0.0]), np.array([0.045, 0.15, 0.08]), 0.035)
    mand = smin(mand, ramus, 0.08)
    lower = np.full(d.shape, 9.0)
    for i in range(-3, 4):
        a = i * 0.14
        c = np.array([0.2 * np.sin(a), -0.47, 0.13 + 0.2 * np.cos(a)])
        lower = np.minimum(lower, rbox(pj, c, np.array([0.022, 0.035, 0.028]), 0.01))
    mand = smin(mand, lower, 0.005)
    return np.minimum(d, mand)


def _camera(yaw, pitch):
    cyw, syw, cp, sp = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch)
    right = np.array([cyw, 0, -syw])
    up = np.array([syw * sp, cp, cyw * sp])
    fwd = np.array([-syw * cp, sp, -cyw * cp])
    return right, up, fwd


# The lamp sits with the camera: upper left of the three-quarter view (yaw 0.45,
# pitch 0.15), so the skull keeps its look when it turns, spins or rolls.
_LAMP = np.array([-0.55, 0.6, 0.6]) / np.linalg.norm([-0.55, 0.6, 0.6])
_LAMP_CAM = np.array([_LAMP @ a for a in _camera(0.45, 0.15)])


def render(w=128, h=45, jaw=0.0, yaw=0.45, pitch=0.15, scale=0.0245, cx=64, cy=21, roll=0.0):
    """Grey image (0 = black, 1 = white bone) of the skull, w x h pedal pixels.
    roll turns the skull in the screen plane (radians, counter-clockwise)."""
    ys, xs = np.mgrid[0:h, 0:w].astype(float)
    u0 = (xs - cx) * scale
    v0 = -(ys - cy) * scale * ASPECT
    cr, sr = np.cos(roll), np.sin(roll)
    u, v = u0 * cr + v0 * sr, -u0 * sr + v0 * cr
    # orthographic camera turned by yaw (around y) and pitch (around x)
    right, up, fwd = _camera(yaw, pitch)
    o = u[..., None] * right + v[..., None] * up - 2.0 * fwd
    t = np.zeros((h, w)); hit = np.zeros((h, w), bool)
    for _ in range(90):
        p = o + t[..., None] * fwd
        d = skull(p, jaw)
        hit |= d < 0.002
        t = np.where(hit, t, t + d * 0.9)
        if (t > 5).all() or hit.all():
            break
    p = o + t[..., None] * fwd
    e = 0.004
    n = np.stack([skull(p + np.array([e, 0, 0]), jaw) - skull(p - np.array([e, 0, 0]), jaw),
                  skull(p + np.array([0, e, 0]), jaw) - skull(p - np.array([0, e, 0]), jaw),
                  skull(p + np.array([0, 0, e]), jaw) - skull(p - np.array([0, 0, e]), jaw)], -1)
    n /= np.maximum(_len(n)[..., None], 1e-6)
    light = _LAMP_CAM[0] * right + _LAMP_CAM[1] * up + _LAMP_CAM[2] * fwd
    diff = np.clip((n * light).sum(-1), 0, 1)
    ao = np.ones((h, w))                          # cheap occlusion: sample along the normal
    for k in range(1, 5):
        dk = 0.03 * k
        ao -= (dk - skull(p + n * dk, jaw)) * (0.5 ** k) * 6
    ao = np.clip(ao, 0, 1)
    # cavities (sockets, nose, between teeth) go black through the occlusion
    img = np.clip((0.38 + 0.85 * diff) * ao ** 2.2, 0, 1)
    # sockets and nose read black: darken surface that lies inside those shapes
    x = np.abs(p[..., 0:1]); ps = np.concatenate([x, p[..., 1:]], -1)
    cav = np.minimum(ellipsoid(ps, np.array([0.17, -0.03, 0.40]), np.array([0.145, 0.13, 0.26])),
                     ellipsoid(p, np.array([0, -0.21, 0.42]), np.array([0.075, 0.11, 0.2])))
    img = np.where(cav < 0.0, img * 0.12, img)
    return np.where(hit, img, 0.0), hit


def tone(img, lo=0.16, hi=0.72):
    """Bone mostly white, a dithered band for shadows, cavities pure black."""
    return np.clip((img - lo) / (hi - lo), 0, 1)


def dither(img, mode="fs"):
    """1-bit (1 = white bone). 'fs' error diffusion or 'bayer' 4x4."""
    h, w = img.shape
    if mode == "bayer":
        b = np.array([[0, 2], [3, 1]])
        for _ in range(2):                         # 8x8 ordered dither
            b = np.block([[4 * b, 4 * b + 2], [4 * b + 3, 4 * b + 1]])
        m = (b + 0.5) / b.size
        return img > m[np.arange(h)[:, None] % 8, np.arange(w)[None, :] % 8]
    a = img.copy(); out = np.zeros((h, w), bool)
    for y in range(h):
        for x in range(w):
            old = a[y, x]; new = old >= 0.5; out[y, x] = new; err = old - new
            if x + 1 < w: a[y, x + 1] += err * 7 / 16
            if y + 1 < h:
                if x > 0: a[y + 1, x - 1] += err * 3 / 16
                a[y + 1, x] += err * 5 / 16
                if x + 1 < w: a[y + 1, x + 1] += err * 1 / 16
    return out


def project(point, yaw=0.45, pitch=0.15, scale=0.0245, cx=64, cy=21):
    """Pedal pixel (x, y) of a model point, for the render() camera."""
    cyw, syw, cp, sp = np.cos(yaw), np.sin(yaw), np.cos(pitch), np.sin(pitch)
    right = np.array([cyw, 0, -syw]); up = np.array([syw * sp, cp, cyw * sp])
    p = np.asarray(point, float)
    return int(round(cx + (p @ right) / scale)), int(round(cy - (p @ up) / (scale * ASPECT)))

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 BOBI SAS, France
# Distributed under the GNU GPL v3 (or later); see the LICENSE file at the root.

# ─────────────────────────────────────────────────────────────────────────────
# HELLO WORLD — the EXECUTABLE reference for the plugin contract.
#
# It composes a picture: a coloured background, the video source as a PiP, level
# meters fed by the audio input, the timecode extracted from the ANC, and a
# "Hello World" panel with system information. It re-emits all three essences.
#
# Its function is of no use in production, and that is the point: what it shows
# is the CONTRACT, across all three essences at once.
#
#   1. the str.format template and its doubled braces;
#   2. SLICE MODE, mandatory for every new plugin;
#   3. VIDEO + AUDIO + ANC, on the way in as well as out;
#   4. exposure to MACROS (param_tree + actions), live option lists included;
#   5. the METRICS that say whether the stage does what it was asked to;
#   6. an OUTPUT INDEPENDENT OF ITS PRODUCER: with no input, it still emits;
#   7. recovery from SIGBUS and from a re-created input flow.
#
# Every section carries the WHY, and what breaks SILENTLY when it is left out.
# `tools/verif_plugin_hello_world.py` checks in CI that this file still honours
# those points: if the contract moves and the example does not follow, CI fails.
# That is what stops it becoming a museum piece, as any documentation nothing
# executes eventually does.
#
# ★ IT RUNS WITH NOTHING WIRED IN. An example that required an already-built
# chain would help nobody on installation day — and that is precisely the day
# you want to know whether "plugin → agent → MXL bus → metrics" works, on all
# three essences.
#
# ⚠ DELIBERATELY OUT OF SCOPE: fine genlock and INTERLACE. An interlaced plugin
# stays whole-frame (the documented exception to the slice-mode rule), and
# field-native handling is best read in `color_corrector`. An example that shows
# everything shows nothing.
#
# ⚠ str.format TEMPLATE: ONLY {config}, {hostname} and {plugin_version} are
# substitutions. EVERY other literal brace must be DOUBLED {{ }} — body,
# f-strings, AND comments. A missed brace does not fail at deploy time: the
# `plugins._scan()` guard DISCARDS the plugin, which vanishes from the registry.
# That takes far longer to diagnose than an outright error.
# ─────────────────────────────────────────────────────────────────────────────
import base64, time, threading, json, signal, platform, unicodedata, datetime
import numpy as np
import bobimxl
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont

# ─── Config injected by the orchestrator (plugin contract) ───────────────────
CONFIG         = {config}
HOSTNAME       = "{hostname}"
PLUGIN_VERSION = "{plugin_version}"

# ★ THE BURNT-IN LANGUAGE IS THE SYSTEM'S, NOT THE DEPLOYER'S. What is composited
# goes out in a stream several people watch, so it cannot follow the preference of
# whoever happened to press Deploy. `before_deploy` passes `ui_lang_default`; the
# container has no other way of knowing it. Defined HERE, before any label, so
# that every string on screen can go through it.
LANGUE = "en" if str(CONFIG.get("langue") or "fr").lower().startswith("en") else "fr"


def _t(fr, en):
    return en if LANGUE == "en" else fr


# What the orchestrator was configured to resolve. Shown ON SCREEN so that the
# origin of the label is VISIBLE — a mechanism you cannot observe is a mechanism
# you do not understand.
_COLS = {{0: _t("conteneur source", "source container"),
         1: _t("nom du flux MXL", "MXL flow name")}}
_NOM_COL = _t("libellé : %s", "label: %s") % _COLS.get(
    int(CONFIG.get("tally_label_col") or 0),
    _t("colonne %s", "column %s") % CONFIG.get("tally_label_col"))
# ★ THE LEVELS ARE NAMED, AND THEY ARE A LIST. A tally level is an entity of the site
# (Settings → Labels & Tally) with a name the operator wrote — "Antenne", "Plateau" — and a
# source can be followed on SEVERAL of them at once, because tally ACCUMULATES. Showing the
# raw number would send the reader off to another page to find out what it means, so
# `before_deploy` injects the names: the orchestrator is the only side that knows them.
_niv = CONFIG.get("tally_level") or []
if not isinstance(_niv, list):
    _niv = [_niv] if _niv else []            # a container configured before 0.2.0
_NOMS_NIV = CONFIG.get("tally_level_noms") or {{}}
_NOM_NIV = _t("niveaux : %s", "levels: %s") % (
    _t("ceux du projet", "the project's") if not _niv
    else ", ".join("%s — %s" % (n, _NOMS_NIV.get(str(n)) or "?") for n in _niv))

SHM_VIDEO = HOSTNAME + "_hello"
SHM_AUDIO = HOSTNAME + "_hello_audio"
SHM_ANC   = HOSTNAME + "_hello_anc"
DEMARRAGE = time.time()

CANAUX = 8
TAUX   = 48000

# Background colours, in YUV — the bus carries YUV: converting from RGB on every
# frame for a flat background would be paying compute for a constant.
# ─── Backgrounds ────────────────────────────────────────────────────────────
# ★ A GRADIENT, NOT A FLAT FILL. A saturated flat fill is unreadable under an
# overlay and reads as a fault on air; a gentle vertical ramp gives depth for
# free — a line's value depends only on its index, so it is LINE-LOCAL and
# perfectly compatible with slice mode.
# The hues are desaturated on purpose: we composite on top of them.
# (y_top, y_bottom, u, v) in 8 bits, legal video levels.
FONDS = {{
    "ardoise":  (58, 26, 128, 128),
    "nuit":     (46, 20, 140, 122),
    "foret":    (52, 22, 118, 120),
    "bordeaux": (52, 22, 122, 142),
    "graphite": (70, 34, 128, 128),
}}

# ─── Tally colours ──────────────────────────────────────────────────────────
# In YUV, computed from the intended RGB through the BT.709 matrix — not guessed
# values. "amber" is not decorative: it is the REAL case where a source is both
# on air (red) and in preview (green), which two separate lamps could not show
# on a single line.
#
# ⚠ AND LUMINANCE STAYS DISCRIMINATING. Red 85, green 151, amber 156: on a
# black-and-white monitor — or for anyone who does not tell red from green — the
# three states still read. Signalling that exists only as hue is signalling that
# fails part of the operators.
TALLY_COULEURS = {{
    "red":    (85, 109, 211),
    "green":  (151, 91, 63),
    "orange": (156, 60, 179),
}}

# ─── Layout: three normalised rectangles ────────────────────────────────────
# Every element is {{x, y, w, h}} as a fraction of the frame, 0..1. Same
# convention as the product's other editors (multiview, PiP, split) and as the
# shared engine `static/js/layout_engine.js` — so a layout reads from one editor
# to the next with no conversion.
DISPO_DEFAUT = {{
    "pip":     {{"x": 0.74, "y": 0.74, "w": 0.25, "h": 0.26}},
    "vu":      {{"x": 0.676, "y": 0.752, "w": 0.047, "h": 0.248}},
    # The panel is WIDE because it can afford to be: its render is capped at 10 Hz
    # (see `overlay_pour`), so its size is no longer paid 50 times a second. It was
    # briefly cut to 0.32 in the belief that its area was the cost — the cost was the
    # render FREQUENCY, not the size.
    "texte":   {{"x": 0.02, "y": 0.3, "w": 0.46, "h": 0.38}},
}}


def _dispo(brut):
    """Merge the received layout with the default, and clamp every rectangle.

    A persisted layout may come from an earlier version, an imported project or a
    hand-typed value: a missing key takes the default, an out-of-frame value is
    brought back inside. We do not REJECT an imperfect layout — a plugin that
    refuses to start because a rectangle overflows by three thousandths would be
    unbearable — but we do not let it produce a wrong picture either."""
    out = {{}}
    for cle, d in DISPO_DEFAUT.items():
        r = dict(d)
        v = (brut or {{}}).get(cle) or {{}}
        for k in ("x", "y", "w", "h"):
            try:
                r[k] = float(v[k])
            except (KeyError, TypeError, ValueError):
                pass
        r["w"] = max(0.02, min(1.0, r["w"]))
        r["h"] = max(0.02, min(1.0, r["h"]))
        r["x"] = max(0.0, min(1.0 - r["w"], r["x"]))
        r["y"] = max(0.0, min(1.0 - r["h"], r["y"]))
        out[cle] = r
    return out


def pip_tranchable(pip):
    """Can the PiP be served from the CURRENT frame?

    ★ THE GEOMETRY DECIDES. The PiP squeezes the whole source height into `h`: its
    output line `y` is fed by INPUT line `(y − y0) / h`. To write it as the band
    arrives, that line must ALREADY have been received — so `(y − y0)/h ≤ y` over
    the PiP's whole height. At worst (y = y0 + h) that gives `1 ≤ y0 + h`: **the
    PiP must touch the BOTTOM edge**.

    ⚠ WHAT THIS TEST DOES NOT SAY. It does NOT say "we can no longer slice". That
    was the first version's mistake, and it was expensive: off the bottom edge the
    stage fell back to whole-frame and added one frame of latency to the WHOLE
    output, for a thumbnail. The constraint is about WHICH FRAME THE INSET COMES
    FROM, not about slicing: take it from the PREVIOUS frame, which is complete,
    and the output stays published band by band.

    So the cost moves — from one frame on the entire signal to one frame on the
    thumbnail alone — and it is published (`pip_retard_trames`) instead of unsaid."""
    return (pip["y"] + pip["h"]) >= 0.999


# ─── Logging ────────────────────────────────────────────────────────────────
_NIVEAUX = ("debug", "info", "warning", "error")
_niveau = CONFIG.get("log_level") or "info"

def log(msg, niveau="info"):
    if _NIVEAUX.index(niveau) >= _NIVEAUX.index(_niveau):
        print("[%s] %s" % (niveau.upper(), msg), flush=True)

# ─── Hot-adjustable state ───────────────────────────────────────────────────
# A plugin is NOT reconfigured by redeploying: the operator turns a knob and the
# picture follows. Hence a lock-guarded state, re-read on every frame, and
# control routes that write to it.
state_lock = threading.Lock()
state = {{
    "input_shm":  CONFIG.get("input_shm"),
    "audio_shm":  CONFIG.get("audio_shm"),
    "anc_shm":    CONFIG.get("anc_shm"),
    "texte":      str(CONFIG.get("texte") or "Hello World"),
    "overlay_on": bool(CONFIG.get("overlay_on", True)),
    "pip_on":     bool(CONFIG.get("pip_on", True)),
    # ⚠ The fallback MUST be a key that exists. It read "bleu" after a palette
    # change: `state["fond"]` could then hold a name absent from FONDS, and only
    # the render's `.get(..., ardoise)` avoided the KeyError — an invalid value
    # that "works" is a value nobody ever fixes.
    "fond":       (CONFIG.get("fond") if CONFIG.get("fond") in FONDS else "foret"),
    "dispo":      _dispo(CONFIG.get("dispo")),
    "coefficient_omega": float(CONFIG.get("coefficient_omega") or 0),
}}
_CABLAGES = ("input_shm", "audio_shm", "anc_shm")
# The essence as the orchestrator sends it → the field declared in the
# manifest's `wiring.consumes[].state_field`. The two must stay in agreement:
# the manifest tells the orchestrator where to put it, this table tells the
# script where to read it.
_CHAMP_PAR_ESSENCE = {{"video": "input_shm", "audio": "audio_shm", "data": "anc_shm"}}
_DEFAUTS = {{k: v for k, v in state.items() if k not in _CABLAGES}}

# ─── Tally and live labels (TSL service) ────────────────────────────────────
# ⚠ THE SERVICE PUSHES ON PORT 8080 — the METRICS port, not the control one. A
# GET-only metrics server would answer 501 and the tally would never arrive,
# with nothing to signal it: the plugin would simply show empty labels for
# ever.
tally_lock = threading.Lock()
tally = {{}}          # key → {{"rouge": "red|off", "vert": "green|off", "texte": "…"}}
tally_ts = [None]     # time of the LAST packet received — None = never

metrics_lock = threading.Lock()
metrics = {{
    "fps": 0.0,
    "frame_index": 0,
    "plugin_version": PLUGIN_VERSION,
    # ★ WHAT MAKES THE STAGE OBSERVABLE. "fps" only says the loop is turning.
    # These three say whether it does what it was asked to:
    "slice_mode": False,       # is the output REALLY published in slices?
    "own_latency_ms": 0.0,     # compute time per frame → the margin available
    "source": "aucune",         # where the picture comes from
    # ★ PER INPUT, not one global boolean. With three essences, "nothing is
    # arriving" does not say WHICH one is missing — and "absent" is not "no signal".
    "inputs_latency_ms": {{}},
    "entrees": {{"video": "not wired", "audio": "not wired", "anc": "not wired"}},
    "timecode": None,
    "audio_crete_dbfs": None,
    "audio_freq_hz": None,
    "audio_canaux_dbfs": [],
    "slice_repli": None,        # WHY the render departs from the nominal path, if it does
    # ★ THE INSET'S DELAY, COUNTED. A PiP served from the previous frame is a
    # legitimate choice, not a fault — but an offset no counter displays is an
    # offset nobody finds again six months later.
    "pip_retard_trames": 0,
    "tally_age_s": None,        # age of the last TSL packet — None = NEVER received
    # ★ THE PARTIAL FRAME, COUNTED. When an input band does not arrive in time, we
    # publish the bands already valid and stop there: the BOTTOM of the picture
    # keeps the ring's previous content. On screen that reads as a jump backwards
    # or as combing — and no counter moved. This one moves: "fps on cadence" and
    # "truncated frames" coexist very comfortably.
    "slices_incompletes": 0,
    # ★ THE PANEL CACHE, COUNTED. This whole file explains that a render cached by
    # signature is what separates a held cadence from a deficit — and nothing said
    # whether THIS cache was doing anything. A signature that changes on every frame
    # gives a cache that never misses a chance not to serve, with no visible symptom.
    "overlay_rendus_par_s": 0.0,
}}

# ─── SLICE MODE (mandatory for every NEW plugin) ────────────────────────────
# We read the input band by band and publish the output by progressive commit,
# instead of waiting for the whole frame.
#
# ★ WHY THIS IS A RULE AND NOT A HABIT. A plugin that works whole-frame adds ONE
# FRAME of latency to every chain that crosses it — and that debt appears on NO
# counter: the plugin reports a perfect cadence. It is the textbook silent
# failure. Measured on the `scope` plugin: the compute left after the last line
# arrives drops from 5.09 to 1.48 ms, at equal cadence.
#
# ★ CONTRACT: k valid slices ⇔ lines [0, k × slice_height) written ON ALL THREE
# PLANES (Y, Cb, Cr). A consumer reading k slices must find the three planes
# consistent up to that line, or it tears at the chroma boundary.
#
# ★ ELIGIBILITY CONDITION: the processing must be LINE-LOCAL. Here the picture
# is copied as-is and the overlay is PRE-RENDERED once and for all: each output
# line depends only on the same input line and on the line number. A blur, a
# deinterlace, or anything that looks at neighbouring lines is NOT — stay
# whole-frame then, and write it down in the code, as interlace and line
# selection do.
#
# `slice_mode` is `hidden` in the manifest BY DESIGN: the setting that matters
# is the global switch under Settings → Video. A plugin exposing its own would
# leave a fleet configured at random.
_sm = CONFIG.get("slice_mode", True)
SLICE_MODE   = _sm if isinstance(_sm, bool) else str(_sm).strip().lower() in ("1", "true", "yes", "on")
SLICE_LINES  = max(1, int(CONFIG.get("slice_lines") or 36))
_SLICE_CIBLE = max(1, 1080 // SLICE_LINES)

def slice_height_pour(hauteur):
    """Smallest divisor of `hauteur` giving ~`_SLICE_CIBLE` slices (1080→36, 720→24).

    Returns 0 when no reasonable divisor exists (a prime height, for instance): the
    plugin then falls back to whole-frame. An EXPLICIT, logged fallback, never a
    lopsided slice — one acknowledged frame of latency beats an output whose band
    boundaries do not land squarely."""
    lo = max(1, hauteur // _SLICE_CIBLE)
    for sh in range(lo, hauteur // 2 + 1):
        if hauteur % sh == 0:
            return sh
    return 0


# ─── Memory layout of a video grain ─────────────────────────────────────────
# ⚠ WHAT A GRAIN IS NOT. `open_grain()` and `get_slice()` return
# `(index, grainInfo, view)` where the VIEW is a FLAT numpy array of bytes — not
# an object with `.y/.u/.v` planes. The format does not live in the grain: it
# comes from the `flow_def`, which `Reader.format()` exposes. Believing
# otherwise costs one `AttributeError` per frame, caught by the loop, hence a
# container that runs, answers on both its ports, and emits NOTHING — without a
# single counter complaining. That is this product's typical failure mode.
#
# ⚠ AND CHROMA DOES NOT ALWAYS HAVE HALF THE LINES. In 4:2:0 it does, in 4:2:2
# it does NOT: it has as many as luma, only the width is halved. Halving the
# line count "because it is chroma" shifts the colour by a factor of two over
# half the picture. Hence `ch` and `cw`, never a hard-coded 2.
def disposition(f):
    """Derive from a flow format everything needed to carve up a grain."""
    w = int(f["width"]) - int(f["width"]) % 2
    h = int(f["height"]) - int(f["height"]) % 2
    profondeur = int(f.get("bit_depth") or 8)
    chroma = f.get("chroma") or "422"
    bps = 2 if profondeur >= 10 else 1
    dt = np.uint16 if profondeur >= 10 else np.uint8
    cw = {{"420": 2, "422": 2, "444": 1}}.get(chroma, 2)
    ch = {{"420": 2, "422": 1, "444": 1}}.get(chroma, 1)
    uv_w, uv_h = w // cw, h // ch
    y_sz, uv_sz = w * h * bps, uv_w * uv_h * bps
    return dict(width=w, height=h, chroma=chroma, bit_depth=profondeur,
                fps_num=int(f.get("fps_num") or 25), fps_den=int(f.get("fps_den") or 1),
                bps=bps, dt=dt, cw=cw, ch=ch, uv_w=uv_w, uv_h=uv_h,
                y_sz=y_sz, uv_sz=uv_sz, taille=y_sz + 2 * uv_sz,
                blanc=(235 << (profondeur - 8)))


def plans(vue, lyt):
    """The three planes, as zero-copy VIEWS on the grain's flat buffer.

    Views, not copies: writing into them writes into the grain. That is the whole
    point of `open_grain` — copying would cost a full frame of memory per picture,
    for nothing."""
    o = vue if vue.dtype == np.uint8 else vue.view(np.uint8)
    y = o[:lyt["y_sz"]].view(lyt["dt"]).reshape(lyt["height"], lyt["width"])
    u = o[lyt["y_sz"]:lyt["y_sz"] + lyt["uv_sz"]].view(lyt["dt"]).reshape(lyt["uv_h"], lyt["uv_w"])
    v = o[lyt["y_sz"] + lyt["uv_sz"]:lyt["taille"]].view(lyt["dt"]).reshape(lyt["uv_h"], lyt["uv_w"])
    return y, u, v

# ─── ☕ Credits ──────────────────────────────────────────────────────────────
# The "omega coefficient" setting does nothing. Set to 10 — the team is ten
# people — it rolls the credits.
#
# ★ AND IT TEACHES SOMETHING. A naive animation would re-render the text on
# every frame, invalidating the signature cache 25 times a second for IDENTICAL
# content — the leading cause of cadence deficit in this product. Here the
# credits are rendered ONCE and only the vertical offset changes: the animation
# is a copy `offset`, not a re-render. The rule holds for any animated overlay,
# credits or not.
#
# ★ BILINGUAL, FOLLOWING THE SYSTEM'S DEFAULT LANGUAGE. What is burnt in goes
# out in a stream several people watch: the language cannot be that of whoever
# deployed it. `before_deploy` passes `ui_lang_default` — the container itself
# has no way of knowing it.
#
# Only the headings and the closing thanks are translated. Names of people,
# organisations and software never are: they are proper nouns, and "Intel Media
# Transport Library" has no French version.
# ★ THE CREDITS ARE ENCODED, AND THIS IS NOT SECURITY. They are a surprise:
# reading them in the file because you went looking is one thing; coming across
# them while reading the panel render is another. Base64 protects nothing and
# claims to protect nothing — it just stops a handful of proper names jumping out
# at whoever is skimming this script to understand slice mode.
#
# Format: [[style, [fr, en]], …] as UTF-8 JSON, then base64. The base64 alphabet
# has no braces, so there is nothing to double for the `str.format` template.
_GEN_B64 = (
    "W1sidGl0cmUiLFsiQk9CSS5TVFVESU8iLCJCT0JJLlNUVURJTyJdXSxbIiIsWyIiLCIiXV0sWyJzZWN0aW9u"
    "IixbIkTDqXZlbG9wcMOpIGV0IHRlc3TDqSBlbiB2ZXJzaW9uIDAgcGFyIiwiRGV2ZWxvcGVkIGFuZCB0ZXN0"
    "ZWQgaW4gdmVyc2lvbiAwIGJ5Il1dLFsibm9tIixbIkxvdWlzIEFsbGl6b24iLCJMb3VpcyBBbGxpem9uIl1d"
    "LFsibm9tIixbIlZhbGVudGluIERlYmxpcXVpIiwiVmFsZW50aW4gRGVibGlxdWkiXV0sWyJub20iLFsiVmlu"
    "Y2VudCBEZXdhc21lcyIsIlZpbmNlbnQgRGV3YXNtZXMiXV0sWyJub20iLFsiUGF1bCBHYWRpbiIsIlBhdWwg"
    "R2FkaW4iXV0sWyJub20iLFsiS2FyaW0gSGFtaWRvdSIsIkthcmltIEhhbWlkb3UiXV0sWyJub20iLFsiQW5n"
    "w6hsZSBKYW1hcnQiLCJBbmfDqGxlIEphbWFydCJdXSxbIm5vbSIsWyJNYXJpbmUgTGFoZWx5IiwiTWFyaW5l"
    "IExhaGVseSJdXSxbIm5vbSIsWyJBbnRvaW5lIE1hcmNoYWlzIiwiQW50b2luZSBNYXJjaGFpcyJdXSxbIm5v"
    "bSIsWyJDeXJpbCBNYXpvdWVyIiwiQ3lyaWwgTWF6b3VlciJdXSxbIm5vbSIsWyJLZXZpbiBSZW5pYSIsIktl"
    "dmluIFJlbmlhIl1dLFsiIixbIiIsIiJdXSxbInNlY3Rpb24iLFsic3DDqWNpZmljYXRpb25zIiwic3BlY2lm"
    "aWNhdGlvbnMiXV0sWyJub20iLFsiQU1XQSDigJQgTk1PUyIsIkFNV0Eg4oCUIE5NT1MiXV0sWyJub20iLFsi"
    "RUJVIC8gTkFCQSDigJQgRHluYW1pYyBNZWRpYSBGYWNpbGl0eSIsIkVCVSAvIE5BQkEg4oCUIER5bmFtaWMg"
    "TWVkaWEgRmFjaWxpdHkiXV0sWyJub20iLFsiU01QVEUg4oCUIFNUIDIxMTAsIFNUIDIwNTkiLCJTTVBURSDi"
    "gJQgU1QgMjExMCwgU1QgMjA1OSJdXSxbIiIsWyIiLCIiXV0sWyJzZWN0aW9uIixbImLDonRpIHN1ciIsImJ1"
    "aWx0IG9uIl1dLFsibm9tIixbIk1YTCBTREsgwrcgSW50ZWwgTWVkaWEgVHJhbnNwb3J0IExpYnJhcnkgwrcg"
    "RFBESyIsIk1YTCBTREsgwrcgSW50ZWwgTWVkaWEgVHJhbnNwb3J0IExpYnJhcnkgwrcgRFBESyJdXSxbIm5v"
    "bSIsWyJGRm1wZWcgwrcgR1N0cmVhbWVyIMK3IE1lZGlhTVRYIiwiRkZtcGVnIMK3IEdTdHJlYW1lciDCtyBN"
    "ZWRpYU1UWCJdXSxbIm5vbSIsWyJQeXRob24gwrcgRmxhc2sgwrcgTnVtUHkgwrcgUGlsbG93IMK3IEN1UHki"
    "LCJQeXRob24gwrcgRmxhc2sgwrcgTnVtUHkgwrcgUGlsbG93IMK3IEN1UHkiXV0sWyIiLFsiIiwiIl1dLFsi"
    "c2VjdGlvbiIsWyJwb3VyIiwiZm9yIl1dLFsibm9tIixbIkJPQkkgU0FTLCBGcmFuY2UiLCJCT0JJIFNBUywg"
    "RnJhbmNlIl1dLFsiIixbIiIsIiJdXSxbInNvdXN0aXRyZSIsWyJNZXJjaSwgb24gZXNww6hyZSBxdWUgbGUg"
    "cHJvamV0IHZvdXMgcGxhw650ICEiLCJUaGFuayB5b3Ug4oCUIHdlIGhvcGUgeW91IGVuam95IHRoZSBwcm9q"
    "ZWN0ISJdXSxbIm5vbSIsWyJOJ2jDqXNpdGV6IHBhcyDDoCBub3VzIMOpY3JpcmUgOiBjb250YWN0QGJvYi1p"
    "LnR2IiwiRmVlbCBmcmVlIHRvIHdyaXRlIHRvIHVzOiBjb250YWN0QGJvYi1pLnR2Il1dXQ=="
)

GENERIQUE = [(s, _t(t[0], t[1]))
             for s, t in json.loads(base64.b64decode(_GEN_B64).decode("utf-8"))]

# ★ A REAL FONT FOR THE NAMES, and a fallback that does not die. PIL's built-in
# bitmap font has no accented glyphs: "Angèle" becomes "Angele". On a technical
# panel that is acceptable, in credits it is not — a mangled first name is
# exactly what an alphabetical listing sets out to avoid. DejaVu is installed in
# the compute image; if it is missing we fall back to the built-in font rather
# than crash, because an example must never depend on a file that might not be
# there.
_POLICES = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

_police_cache = {{}}

def _police(taille, gras=False):
    """Font memoised by (size, weight).

    ⚠ `ImageFont.truetype` RE-READS AND RE-PARSES THE FILE on every call: 0.133 ms
    measured. Negligible once, and not at all negligible on the panel rebuild path.

    The scale fit made it worse without anyone seeing: it calls `_jeu()` up to three
    times, and `_jeu()` loads three fonts — so up to NINE loads, ~1.2 ms, on ONE frame
    out of the batch. A frame over budget is a frame lost, and the `own_latency_ms`
    average shows none of it. That is exactly the kind of cost that hides in a mean.

    Font objects are immutable and only read: sharing them is safe."""
    cle = (taille, bool(gras))
    f = _police_cache.get(cle)
    if f is None:
        try:
            f = ImageFont.truetype(_POLICES[1 if gras else 0], taille)
        except Exception:
            f = ImageFont.load_default()
        _police_cache[cle] = f
    return f

_gen_lock = threading.Lock()
_gen_cache = {{"signature": None, "y": None}}

_STYLES = {{
    "titre":     (0.030, True,  255),
    "soustitre": (0.018, False, 200),
    "section":   (0.015, False, 150),
    "nom":       (0.020, False, 235),
    "":          (0.012, False, 0),
}}

def generique_pour(largeur, hauteur):
    """Render the credits column ONCE. The animation never re-renders it."""
    signature = (largeur, hauteur, len(GENERIQUE))
    with _gen_lock:
        if _gen_cache["signature"] == signature:
            return _gen_cache["y"]
    interligne = max(8, int(hauteur * 0.030))
    col = Image.new("L", (largeur, interligne * len(GENERIQUE) + interligne), 0)
    d = ImageDraw.Draw(col)
    for i, (style, texte) in enumerate(GENERIQUE):
        if not texte:
            continue
        rel, gras, ton = _STYLES.get(style, _STYLES["nom"])
        f = _police(max(10, int(hauteur * rel)), gras)
        # Centred: PIL does not centre on its own, and left-aligned credits are not
        # credits.
        x = max(0, (largeur - int(d.textlength(texte, font=f))) // 2)
        d.text((x, i * interligne), texte, font=f, fill=ton)
    y = np.asarray(col, dtype=np.uint8)
    with _gen_lock:
        _gen_cache.update({{"signature": signature, "y": y}})
    return y


def derouler(plan_y, ligne0, hauteur, colonne, offset):
    """Copy the slice of the credits visible at this screen height.

    `offset` rises from one frame to the next: that is ALL that moves. Line-local,
    so slice-mode compatible like the rest of the render.

    ★ VECTORISED, and that is not a flourish. The first version looped in Python
    line by line: 1080 iterations per frame, on a stage with a 20 ms budget. numpy
    does the same thing in one operation — the carve-up reduces to a contiguous
    range, since the offset is uniform."""
    gh, gw = colonne.shape
    larg = min(gw, plan_y.shape[1])
    x0 = max(0, (plan_y.shape[1] - larg) // 2)
    # Range of SOURCE lines visible in this block, clamped to the column.
    d_src = ligne0 + offset
    a = max(0, -d_src)                                   # 1st line of the block to write
    b = min(plan_y.shape[0], gh - d_src)                 # 1st line no longer written
    if b <= a:
        return
    src = colonne[d_src + a:d_src + b, :larg]
    zone = plan_y[a:b, x0:x0 + larg]
    plan_y[a:b, x0:x0 + larg] = np.where(src > 0, src, zone)


# ─── The overlay ────────────────────────────────────────────────────────────
# ★ PRE-RENDERED AND CACHED, invalidated by a SIGNATURE. Redrawing the text on
# every frame would cost several milliseconds for an identical result 24 times
# out of 25. The signature holds everything that changes the render: if it
# moves, we redraw; otherwise we copy. It is the pattern used everywhere in the
# product, and forgetting it is the leading cause of cadence deficit.
#
# No external font: we use PIL's built-in bitmap font, enlarged nearest-
# neighbour. An example must depend on NO site file — the font library and the
# brand logo are operational data that may be absent on a fresh install.
def _ascii(t):
    """Strip accents before drawing.

    ⚠ FOUND BY TESTING THE RENDER, not by re-reading the code: PIL's built-in
    bitmap font has no accented glyphs — "générée" showed as "g□n□r□e". Text
    coming from the operator may contain them, so we degrade cleanly rather than
    display boxes. A real font from the library (ImageFont.truetype) would render
    them, but an example must not depend on any site file."""
    t = "".join(c for c in unicodedata.normalize("NFD", t)
                if unicodedata.category(c) != "Mn")
    # Diacritics are not the whole story: typographic punctuation (em dash, curly
    # apostrophe, French quotation marks) is not in the font either and rendered as
    # a box. We transliterate, then replace whatever is left outside ASCII — a
    # visible "?" beats a silent square.
    t = t.translate(str.maketrans({{
        "\u2014": "-", "\u2013": "-", "\u2019": "'", "\u2018": "'",
        "\u201c": '"', "\u201d": '"', "\u00ab": '"', "\u00bb": '"',
        "\u2026": "...", "\u00a0": " ", "\u2022": "*",
    }}))
    return t.encode("ascii", "replace").decode("ascii")

_ov_lock = threading.Lock()
# ★ THE CACHE HOLDS THE BLEND HALF DONE. What does NOT depend on the background
# picture — the product `source × alpha` and the complement `256 − alpha` — is
# computed once per panel change, not once per band per frame. Measured on an
# 883×410 panel: 2.63 ms → 0.32 ms, eight times faster. The earlier version redid
# two `astype` calls and an integer division by 255 on every band.
_ov_cache = {{"signature": None, "y": None, "inv": None, "u": None, "v": None,
              "haut": 0, "large": 0}}
_ov_stats = [0, 0, 0.0]   # [calls, real renders, instant of the last render]
_OV_INTERVALLE = 0.1      # 10 Hz: the panel's refresh cadence

def _logo(d, x, y, taille):
    """A PROCEDURAL logo — three bars and a dot, drawn, not loaded.

    Deliberately not `static/uploads/brand-logo.png`: that file is an operational
    upload, absent from a fresh install. An example that crashes for want of a site
    asset is an example that never gets used."""
    ep = max(2, taille // 7)
    for i, largeur in enumerate((taille, int(taille * 0.72), int(taille * 0.44))):
        haut = y + i * int(ep * 1.9)
        d.rounded_rectangle([x, haut, x + largeur, haut + ep], radius=ep // 2, fill=255)
    d.ellipse([x + taille + ep, y, x + taille + ep * 3, y + ep * 2], fill=255)


def _etat_tally():
    """How long since the distributor last spoke to us. None = NEVER.

    ★ ABSENCE MUST BE VISIBLE. Without this witness, "no label shown" is
    indistinguishable from "all is well, the source simply has no label". Which is
    exactly what happened here: the running orchestrator's plugin registry did not
    know about `hooks.py` yet, so the distributor skipped this container — and the
    plugin had no way to say so. A hook that never fires is a perfectly silent
    failure; adding or changing `hooks.py` requires a registry reload
    (Settings → Plugins, or POST /api/plugins/reload)."""
    with tally_lock:
        t = tally_ts[0]
    return None if t is None else max(0.0, time.time() - t)


def _tally_de(cle):
    """(live label, state) for one input. The state is 'red', 'green' or ''."""
    with tally_lock:
        t = dict(tally.get(cle) or {{}})
    r, v = t.get("rouge") == "red", t.get("vert") == "green"
    etat = "orange" if (r and v) else ("red" if r else ("green" if v else ""))
    return (t.get("texte") or ""), etat


_ORIGINE_TC = ["—"]     # where the displayed TC comes from — see the loop

# ─── Displayed time ─────────────────────────────────────────────────────────
# ★ IN THE ORCHESTRATOR'S TIME ZONE, NOT THE CONTAINER'S. A container runs in
# UTC: measured here, the host was at 20:39 CEST while the container displayed
# 18:39 UTC. A clock wrong by a ROUND number of hours is the worst case — it
# looks right, and nobody checks it. The zone arrives through the params, set by
# the `before_deploy` hook, which does run on the orchestrator side.
#
# Without seconds, by design: an information panel is not a studio clock, and a
# ticking second would invalidate the render cache on every frame. The "uptime"
# field already carries second-level precision.
_FUSEAU_NOM = str(CONFIG.get("fuseau") or "UTC")
try:
    from zoneinfo import ZoneInfo
    _FUSEAU = ZoneInfo(_FUSEAU_NOM)
except Exception:                                          # time-zone database missing
    _FUSEAU = datetime.timezone.utc
    _FUSEAU_NOM = "UTC (%s introuvable)" % _FUSEAU_NOM


def heure_locale():
    """The orchestrator's time, without seconds."""
    return datetime.datetime.now(_FUSEAU).strftime("%H:%M")


def _infos_systeme(largeur, hauteur, fps, entrees, tc, crete):
    """What you want to read on screen while checking a fresh install.

    ★ THE SOURCE'S LABEL, NOT JUST ITS FLOW NAME. "2110-io-dl360-1_1" tells an
    operator nothing; "CAM 2 STUDIO" tells them everything. The TSL service
    resolves that label from the source table and pushes it here. All three inputs
    carry it, which lets you check at a glance that they come from the SAME
    programme — the costliest confusion in three-essence cabling."""
    up = int(time.time() - DEMARRAGE)
    lv, tv = _tally_de("video")
    la, ta = _tally_de("audio")
    ld, td = _tally_de("anc")
    # The state values are a protocol (English); the screen follows the system's
    # language. We translate on DISPLAY, not at the source.
    _ETATS = {{"not wired": _t("non câblée", "not wired"),
              "no signal": _t("aucun signal", "no signal"),
              "waiting":   _t("en attente", "waiting")}}

    def _src(nom, label, etat):
        nom = _ETATS.get(nom, nom)
        return "%s%s" % (nom, ("   \u00ab %s \u00bb" % label) if label else "")
    return [
        (_t("heure", "time"), "%s   (%s)" % (heure_locale(), _FUSEAU_NOM), ""),
        (_t("conteneur", "container"), HOSTNAME, ""),
        ("plugin", "hello_world v%s" % PLUGIN_VERSION, ""),
        (_t("sorties", "outputs"), "%s · %s · %s" % (SHM_VIDEO, SHM_AUDIO, SHM_ANC), ""),
        (_t("format", "format"), "%d×%d @ %s %s" % (largeur, hauteur, fps,
                                                    _t("i/s", "fps")), ""),
        (_t("vidéo", "video"), _src(entrees["video"], lv, tv), tv),
        (_t("audio", "audio"), _src(entrees["audio"], la, ta)
                  + ("" if crete is None else "   %s %.1f dBFS"
                     % (_t("crête", "peak"), crete)), ta),
        ("ANC", _src(entrees["anc"], ld, td)
                + ("" if not tc else "   TC %s  (%s)" % (tc, _ORIGINE_TC[0])), td),
        (_t("tranches", "slices"), _t("oui", "yes") if SLICE_MODE else _t("non", "no"), ""),
        ("tally", (_t("aucun paquet reçu — le hook est-il chargé ?",
                      "no packet received — is the hook loaded?") if _etat_tally() is None
                   else _t("reçu il y a %ds   ·   %s   ·   %s",
                           "received %ds ago   ·   %s   ·   %s")
                        % (int(_etat_tally()), _NOM_COL, _NOM_NIV)), ""),
        (_t("hôte", "host"), "%s · python %s"
            % (platform.machine(), platform.python_version()), ""),
        (_t("en marche", "uptime"), "%dh %02dm %02ds"
            % (up // 3600, (up % 3600) // 60, up % 60), ""),
    ]


def overlay_pour(largeur, hauteur, fps, entrees, tc, crete, boite):
    """Render the panel: a translucent PANEL and text, as (luma, alpha).

    ★ TWO PLANES, NOT ONE. A binary mask ("pixel lit or nothing") gives text that
    vanishes on a light background and a panel with no footing. By rendering an
    ALPHA layer beside the luma, we get a semi-opaque panel behind the text:
    readable over any picture, the PiP included. The blend stays per-pixel, so
    line-local — slice mode is none the worse for it.

    ★ AND A REAL FONT. PIL's built-in bitmap font is unreadable as soon as you
    enlarge it, and has no accents. DejaVu is in the compute image; `_police` falls
    back to the built-in font if it is missing, in which case `_ascii`
    transliterates — an example must not depend on any site file."""
    with state_lock:
        texte = state["texte"]
    lignes = _infos_systeme(largeur, hauteur, fps, entrees, tc, crete)
    signature = (texte, largeur, hauteur, boite, tuple(lignes))
    # ★ A SIGNATURE THAT CHANGES EVERY FRAME IS NOT A CACHE KEY. The panel shows the
    # timecode and the audio peak: two values that move on EVERY picture. So the
    # signature moved too, and the cache missed 50 times a second — measured:
    # `overlay_rendus_par_s` was exactly the frame rate. This whole file explains that
    # caching by signature separates a held cadence from a deficit, and its own cache
    # was doing nothing.
    #
    # So we BOUND the refresh rate instead of submitting to it. Ten times a second is
    # ample for an information panel: nobody reads a timecode at 50 Hz. Whoever needs
    # a per-frame timecode — to measure latency, say — uses a PROBE, not an overlay.
    maintenant = time.time()
    with _ov_lock:
        _ov_stats[0] += 1
        frais = (maintenant - _ov_stats[2]) < _OV_INTERVALLE
        if _ov_cache["signature"] is not None and (frais or _ov_cache["signature"] == signature):
            return ((_ov_cache["y"], _ov_cache["u"], _ov_cache["v"]),
                    _ov_cache["inv"], _ov_cache["haut"], _ov_cache["large"])

    # ★ WE MEASURE THE TEXT, WE DO NOT GUESS IT. The width used to be a constant:
    # the full name of the outputs overflowed and got clipped at the panel edge.
    # `textlength` gives the real width in the real font — the only value that does
    # not go stale when a label grows longer.
    _mes = ImageDraw.Draw(Image.new("L", (1, 1)))

    def _jeu(k):
        """Fonts, margins and the width NEEDED at a given scale."""
        ft = _police(max(12, int(46 * k)), True)      # the title
        fc = _police(max(9, int(19 * k)))             # the keys
        fv = _police(max(9, int(19 * k)))             # the values
        natif = getattr(ft, "path", None) is not None  # real font available?
        T_ = (lambda x: x) if natif else _ascii
        col2, pad, lh = int(150 * k), int(26 * k), int(27 * k)
        besoin = max([_mes.textlength(T_(str(v)), font=fv) for _, v, _ in lignes] or [0])
        besoin = max(besoin + col2, _mes.textlength(T_(texte), font=ft) + int(78 * k))
        haut = int(pad * 2 + 64 * k + len(lignes) * lh)
        return ft, fc, fv, natif, T_, col2, pad, lh, besoin, haut

    # ★ THE SCALE COMES FROM THE RECTANGLE, no longer from a separate setting. A
    # panel you resize in the editor whose text size is set somewhere else is two
    # commands for one gesture — and two chances to get them out of step. The box
    # is authoritative.
    k = max(0.25, (boite["w"] * largeur) / 620.0)
    large = int(max(60, min(largeur, boite["w"] * largeur)))
    boite_h = max(20, int(boite["h"] * hauteur))
    ft, fc, fv, natif, T_, col2, pad, lh, besoin, haut = _jeu(k)

    # ⚠ THE TEXT OVERFLOWED ITS BOX. `620` is a yardstick, not a measurement: as
    # soon as the content grows (a flow name, a longer translation) or the box
    # shrinks, the width needed exceeds the width available and PIL clips at the
    # edge — no error, no counter, just a truncated line the operator reads as a
    # missing value. So we REDUCE the scale until the content fits, on both axes.
    # Two passes are enough (the second only confirms), and the panel is cached by
    # signature: this computation only runs again when something changes.
    for _ in range(2):
        fw = (large - 2 * pad) / besoin if besoin > (large - 2 * pad) > 0 else 1.0
        fh = boite_h / haut if haut > boite_h else 1.0
        f = min(fw, fh)
        if f >= 0.999:
            break
        k = max(0.25, k * f)
        ft, fc, fv, natif, T_, col2, pad, lh, besoin, haut = _jeu(k)
    # Last resort: at the floor scale we WIDEN the panel rather than clip. The
    # editor's rectangle then becomes a minimum — an unreadable panel would be a
    # worse lie than a slightly wider one.
    large = int(min(largeur, max(large, besoin + 2 * pad)))
    luma = Image.new("L", (large, haut), 0)
    alpha = Image.new("L", (large, haut), 0)
    # ★ CHROMA, FOR THE LAMPS ONLY. The rest of the panel is neutral (128/128): a
    # grey panel costs nothing to carry, and adding colour only to the few pixels
    # that need it avoids doubling the blend cost over the whole surface.
    chu = Image.new("L", (large, haut), 128)
    chv = Image.new("L", (large, haut), 128)
    dl, da = ImageDraw.Draw(luma), ImageDraw.Draw(alpha)
    du, dv = ImageDraw.Draw(chu), ImageDraw.Draw(chv)

    # The panel: rounded corners, measured opacity — enough to seat the text, not
    # enough to hide the picture.
    r = int(14 * k)
    da.rounded_rectangle([0, 0, large - 1, haut - 1], radius=r, fill=165)
    dl.rounded_rectangle([0, 0, large - 1, haut - 1], radius=r, fill=18)
    # A light hairline on top: the line that lifts the panel off the background.
    da.rounded_rectangle([0, 0, large - 1, haut - 1], radius=r, outline=210, width=max(1, int(k)))
    dl.rounded_rectangle([0, 0, large - 1, haut - 1], radius=r, outline=150, width=max(1, int(k)))

    _logo(dl, pad, pad + int(6 * k), int(30 * k))
    _logo(da, pad, pad + int(6 * k), int(30 * k))
    x_t = pad + int(78 * k)
    dl.text((x_t, pad), T_(texte), font=ft, fill=245)
    da.text((x_t, pad), T_(texte), font=ft, fill=255)
    y0 = pad + int(64 * k)
    for i, (cle, val, tal) in enumerate(lignes):
        yy = y0 + i * lh
        dl.text((pad, yy), T_(cle), font=fc, fill=140)
        da.text((pad, yy), T_(cle), font=fc, fill=235)
        dl.text((pad + col2, yy), T_(str(val)), font=fv, fill=235)
        da.text((pad + col2, yy), T_(str(val)), font=fv, fill=255)
        # Tally lamp: red = on air, green = ready. In luma alone the two are told
        # apart by BRIGHTNESS, not by hue — an overlay that only reads in colour is
        # unreadable on a black-and-white monitor, and for anyone who does not tell
        # red from green.
        if tal:
            cy_, cu_, cv_ = TALLY_COULEURS.get(tal, (235, 128, 128))
            r_ = int(6 * k)
            cy = yy + lh // 2 - r_
            box = [pad - int(18 * k), cy, pad - int(18 * k) + 2 * r_, cy + 2 * r_]
            dl.ellipse(box, fill=cy_)
            da.ellipse(box, fill=255)
            du.ellipse(box, fill=cu_)
            dv.ellipse(box, fill=cv_)

    # ★ ALPHA ON 0..256, NOT 0..255. The blend then ends on an 8-bit SHIFT instead of
    # an integer division by 255 — the most expensive operation in the loop. The
    # rendering difference is at worst ONE quantisation step out of 255 (measured: max
    # 1, mean 0.12), invisible, and the background stays perfectly opaque wherever
    # alpha is 255.
    with _ov_lock:
        _ov_stats[1] += 1
        _ov_stats[2] = time.time()
    a8 = (np.asarray(alpha, dtype=np.uint16) * 257) >> 8
    inv = (256 - a8).astype(np.uint16)
    pre_y = (np.asarray(luma, dtype=np.uint16) * a8).astype(np.uint16)
    pre_u = (np.asarray(chu, dtype=np.uint16) * a8).astype(np.uint16)
    pre_v = (np.asarray(chv, dtype=np.uint16) * a8).astype(np.uint16)
    with _ov_lock:
        _ov_cache.update({{"signature": signature, "y": pre_y, "inv": inv,
                          "u": pre_u, "v": pre_v, "haut": haut, "large": large}})
    return (pre_y, pre_u, pre_v), inv, haut, large


def incruster(plan_y, ligne0, hauteur_totale, ov, ova, ov_h, ov_w,
              plan_u=None, plan_v=None, lyt=None, boite=None):
    """Blend the panel over a BLOCK of lines starting at `ligne0`.

    ★ `ligne0` is the ABSOLUTE index of the block's first line: that is what lets
    the panel land in the right place whether we are processing one band or the
    whole picture. Code ignoring that offset would work whole-frame and drift in
    slices — with no error, just a wrong picture. It is the number one trap when
    moving to slice mode.

    The blend is a per-pixel `a·src + (1−a)·dst`: line-local, hence identical in
    bands and whole-frame."""
    with state_lock:
        if not state["overlay_on"]:
            return
    haut = int((boite or {{"y": 0.3}})["y"] * hauteur_totale)
    haut = max(0, min(max(0, hauteur_totale - ov_h), haut))
    marge = int((boite or {{"x": 0.02}})["x"] * plan_y.shape[1])
    marge = max(0, min(max(0, plan_y.shape[1] - ov_w), marge))
    d, f = haut - ligne0, haut + ov_h - ligne0            # coordinates LOCAL to the block
    dd, ff = max(0, d), min(plan_y.shape[0], f)
    if ff <= dd:
        return                                            # this block does not meet the panel
    larg = min(ov_w, plan_y.shape[1] - marge)
    oy_, ou_, ov_ = ov                 # `source × alpha`, already multiplied (see the cache)

    def _melange(dst, pre, x0, y0, y1):
        # `pre` already carries `source × alpha`; `inv` carries `256 − alpha`. All
        # that is left is one product, one sum and one shift — no per-band type
        # conversion, no division.
        z = dst[y0:y1, x0:x0 + pre.shape[1]]
        dst[y0:y1, x0:x0 + pre.shape[1]] = ((pre + z * inv) >> 8).astype(dst.dtype)

    inv = ova[dd - d:ff - d, :larg]
    _melange(plan_y, oy_[dd - d:ff - d, :larg], marge, dd, ff)

    # ★ CHROMA BLENDS AT ITS OWN RESOLUTION. We resample the mask and the panel's
    # planes at the `cw`/`ch` step — blending them at luma resolution would write
    # outside the plane, or shift the colour by a factor of two.
    if plan_u is not None and lyt is not None:
        chh, cww = lyt["ch"], lyt["cw"]
        cdd, cff = dd // chh, ff // chh
        cmarge, clarg = marge // cww, larg // cww
        if cff > cdd and clarg > 0:
            # ⚠ STRIDED SLICES, NOT `np.ix_`. The first version built two index
            # arrays per band and per frame: "fancy" indexing = a copy, and 30 bands
            # × 50 fps of throwaway arrays. Measured: 45.5 fps and 23.4 ms, ABOVE the
            # 20 ms budget. A constant-step slice is a VIEW — no allocation, no copy.
            sy0, sy1 = dd - d, dd - d + (cff - cdd) * chh
            inv = ova[sy0:sy1:chh, :clarg * cww:cww]
            _melange(plan_u, ou_[sy0:sy1:chh, :clarg * cww:cww], cmarge, cdd, cff)
            _melange(plan_v, ov_[sy0:sy1:chh, :clarg * cww:cww], cmarge, cdd, cff)


VU_CANAUX = 2

def vumetre(plan_y, ligne0, largeur, hauteur, niveaux, boite):
    """VERTICAL level meters, inside their rectangle. Line-local like the rest.

    ★ TWO CHANNELS, NOT EIGHT. The input carries eight, but a picture overlay is
    not an analyser: at the width you can give it without eating the picture, eight
    bars are three pixels each — you no longer read a level, you guess at a
    texture. Two bars read at a glance, and that is the question you ask a burnt-in
    meter: "is it making sound or not". All eight channels stay published in /state
    for whoever wants to measure them.

    ★ VERTICAL, AND BUTTED AGAINST THE PiP by default. A horizontal meter grows to
    the right, so it encroaches on the picture as soon as the level rises; a
    vertical one grows upwards inside a column of FIXED width, and the room it
    takes no longer depends on the signal. Placing it against the PiP makes the two
    read as a single block — the picture and its sound — instead of two unrelated
    overlays.

    ★ AND A TROUGH. Without it, a channel at -60 dBFS draws nothing: the absence of
    a bar is confused with the absence of a meter, and "no sound" with "no
    measurement". The trough makes silence VISIBLE."""
    if not niveaux:
        return
    n = min(VU_CANAUX, len(niveaux))
    x0 = int(boite["x"] * largeur)
    larg_tot = max(2 * n, int(boite["w"] * largeur))
    y0 = int(boite["y"] * hauteur)
    haut_tot = max(4, int(boite["h"] * hauteur))
    bas = y0 + haut_tot
    pas_x = larg_tot // n
    l_barre = max(1, int(pas_x * 0.75))
    # The band visible in THIS slice: everything below refers to it.
    dd_c, ff_c = max(0, y0 - ligne0), min(plan_y.shape[0], bas - ligne0)
    for i in range(n):
        bx = x0 + i * pas_x
        if bx >= plan_y.shape[1]:
            break
        bw = max(1, min(l_barre, plan_y.shape[1] - bx))
        if ff_c > dd_c:
            plan_y[dd_c:ff_c, bx:bx + bw] = 40           # the trough
        frac = max(0.0, min(1.0, (niveaux[i] + 60.0) / 60.0))  # -60 dBFS → 0 %, 0 → 100 %
        rempli = int(haut_tot * frac)
        if rempli <= 0:
            continue
        dd = max(0, (bas - rempli) - ligne0)
        ff = min(plan_y.shape[0], bas - ligne0)
        if ff > dd:
            plan_y[dd:ff, bx:bx + bw] = 235 if niveaux[i] < -6 else 180

# ─── SIGBUS: the MXL bus can vanish underfoot ───────────────────────────────
# A producer that re-creates its flow invalidates the readers' memory mapping.
# The trap: the dead generation stays READABLE — grains are served, the index
# frozen, no exception. Without this handler the process dies on a signal and
# Docker restarts it in a loop with nobody understanding why.
def _sigbus(signum, frame):
    log("SIGBUS: the input flow was re-created — reopening on the next turn", "warning")
    raise IOError("SIGBUS")

signal.signal(signal.SIGBUS, _sigbus)

# ─── HTTP: metrics (8080) and control (8082) ────────────────────────────────
class Metriques(BaseHTTPRequestHandler):
    def do_POST(self):
        # `/tally_bulk`: {{updates:[{{cle, shm, rouge, vert, texte}}], overlays:[…]}}
        # The distributor only pushes when the state has CHANGED (plus a resync
        # every 5 s) — no need for a value guard here.
        if self.path.split("?")[0] != "/tally_bulk":
            self.send_response(404); self.end_headers(); return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{{}}")
            with tally_lock:
                tally_ts[0] = time.time()
                tally.clear()
                for u in (data.get("updates") or []):
                    tally[str(u.get("cle"))] = {{
                        "rouge": u.get("rouge") or "off",
                        "vert": u.get("vert") or "off",
                        "texte": u.get("texte") or "",
                    }}
            self.send_response(200)
        except Exception as e:
            log("tally_bulk illisible : %r" % (e,), "warning")
            self.send_response(400)
        self.end_headers()

    def do_GET(self):
        with metrics_lock:
            charge = dict(metrics)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(charge).encode())
    def log_message(self, *a):
        pass

class Controle(BaseHTTPRequestHandler):
    def _repondre(self, code, obj):
        corps = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        chemin = self.path.split("?")[0]
        # ★ /state and /couleurs are declared in `control.read_endpoints`: that is
        # what makes them readable by the PUBLIC PAGE and usable as a macro
        # CONDITION. A state you do not publish is a state no automation can decide
        # on.
        if chemin == "/state":
            with state_lock:
                st = dict(state)
            with metrics_lock:
                st.update({{k: metrics[k] for k in
                           ("fps", "slice_mode", "source", "frame_index", "entrees",
                            "timecode", "audio_crete_dbfs", "inputs_latency_ms")}})
            st["plugin_version"] = PLUGIN_VERSION
            st["sorties"] = {{"video": SHM_VIDEO, "audio": SHM_AUDIO, "anc": SHM_ANC}}
            st["uptime_s"] = int(time.time() - DEMARRAGE)
            with tally_lock:
                st["tally"] = {{k: dict(v) for k, v in tally.items()}}
            # Exposed so the page can show the CURRENT value: they come from
            # CONFIG (deploy_config), not from the hot state.
            st["tranchable"] = pip_tranchable(st["dispo"]["pip"])
            # ⚠ /state AND metrics ARE TWO DISTINCT SURFACES. The console reads
            # /state; the measurement lived in metrics alone. Result: two catalogue
            # controls displayed nothing — no error, no trace, the operator
            # concluding the audio was dead when it was perfectly fine.
            with metrics_lock:
                st["audio_canaux_dbfs"] = list(metrics.get("audio_canaux_dbfs") or [])
            st["formats_dispo"] = list(CONFIG.get("formats_dispo") or [])
            st["format"] = CONFIG.get("format") or ""
            st["tally_label_col"] = int(CONFIG.get("tally_label_col") or 0)
            st["tally_level"] = int(CONFIG.get("tally_level") or 0)
            a = _etat_tally()
            st["tally_age_s"] = None if a is None else round(a, 1)
            return self._repondre(200, st)
        if chemin == "/dispo":
            with state_lock:
                d = {{k: dict(v) for k, v in state["dispo"].items()}}
            # We return the COST too: the editor can say "whole frame" without
            # reimplementing the rule. It is written in ONE place only, in the
            # script that applies it.
            return self._repondre(200, {{"dispo": d, "defaut": DISPO_DEFAUT,
                                        "tranchable": pip_tranchable(d["pip"])}})
        if chemin == "/couleurs":
            # ★ LIVE LIST for the macro editor (`options_endpoint`). An action with
            # choices does not freeze its values in the manifest: the day a colour is
            # added, the editor sees it without a redeployment.
            return self._repondre(200, {{"options": [{{"value": k, "label": k.capitalize()}}
                                                    for k in FONDS]}})
        return self._repondre(404, {{"error": "inconnu"}})

    def do_POST(self):
        chemin = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n) or b"{{}}")
        except Exception:
            return self._repondre(400, {{"error": "corps JSON illisible"}})

        if chemin == "/params":
            # Target of the `param_tree` AND of the manifest's "Change the text"
            # action: THIS endpoint is what the macro system calls.
            with state_lock:
                if "texte" in data:
                    state["texte"] = str(data["texte"])[:64]
                if data.get("fond") in FONDS:
                    state["fond"] = data["fond"]
                if "coefficient_omega" in data:
                    state["coefficient_omega"] = float(data["coefficient_omega"])
            return self._repondre(200, {{"ok": True}})

        if chemin == "/fond":
            # ★ EXPLICIT REFUSAL of an unknown value, with the list of accepted
            # ones. Accepting silently and falling back to a default would give a
            # macro that "succeeds" while changing nothing — the worst kind of reply.
            couleur = data.get("couleur") or data.get("fond")
            if couleur not in FONDS:
                return self._repondre(400, {{"error": "couleur inconnue",
                                            "connues": list(FONDS)}})
            with state_lock:
                state["fond"] = couleur
            return self._repondre(200, {{"ok": True, "fond": couleur}})

        if chemin == "/dispo":
            # The editor pushes the WHOLE layout, not a delta: a delta would force
            # both sides to agree on an intermediate state, and a lost packet would
            # leave the container in a layout nobody ever drew.
            with state_lock:
                state["dispo"] = _dispo(data.get("dispo") or data)
                d = {{k: dict(v) for k, v in state["dispo"].items()}}
            return self._repondre(200, {{"ok": True, "dispo": d,
                                        "tranchable": pip_tranchable(d["pip"])}})

        if chemin in ("/overlay", "/pip"):
            # Target of the `actions`: DISCRETE actions a trigger can fire without
            # going through the interface.
            with state_lock:
                state["overlay_on" if chemin == "/overlay" else "pip_on"] = bool(data.get("on", True))
            return self._repondre(200, {{"ok": True}})

        if chemin == "/reset":
            with state_lock:
                state.update(_DEFAUTS)
            return self._repondre(200, {{"ok": True}})

        if chemin == "/input":
            # ⚠ THE BODY IS KEYED BY ESSENCE, NOT BY FIELD NAME. The orchestrator
            # posts {{"essence": "video"|"audio"|"data", "shm": …, "slot"?, "format"?}}.
            # First version of this plugin: we looked for "audio_shm" in the body,
            # never found it, and fell back to a default that wrote EVERYTHING into
            # the video input. Seen on the Cabling page: wiring the audio replaced
            # the video. The fallback, in trying to be lenient, turned an unknown key
            # into a WRONG action rather than a refusal.
            essence = (data.get("essence") or "video").strip().lower()
            champ = _CHAMP_PAR_ESSENCE.get(essence)
            if not champ:
                return self._repondre(400, {{"error": "essence inconnue",
                                            "connues": list(_CHAMP_PAR_ESSENCE)}})
            with state_lock:
                # empty shm = UNWIRING that essence only. The other two do not move:
                # a POST on video must not cut the audio.
                state[champ] = (data.get("shm") or "").strip() or None
                cablage = {{c: state[c] for c in _CABLAGES}}
            log("câblage %s → %s : %s" % (essence, champ, cablage), "info")
            return self._repondre(200, {{"ok": True}})

        if chemin == "/log_level":
            global _niveau
            if data.get("niveau") in _NIVEAUX:
                _niveau = data["niveau"]
            return self._repondre(200, {{"ok": True, "niveau": _niveau}})

        return self._repondre(404, {{"error": "inconnu"}})

    def log_message(self, *a):
        pass

def _servir(port, handler):
    threading.Thread(target=lambda: HTTPServer(("0.0.0.0", port), handler).serve_forever(),
                     daemon=True).start()

_servir(8080, Metriques)
_servir(8082, Controle)

# ─── Main loop ──────────────────────────────────────────────────────────────
inst = bobimxl.Instance()
lec_v = lec_a = lec_d = None            # video / audio / ANC readers
fd_anc = [None]                         # flowDef of the ANC flow — read once per open
_pip_map = [None, None]                 # (signature, PiP index tables)
nom_v = nom_a = nom_d = None
ecr_v = ecr_a = ecr_d = None            # writers for the three outputs
fmt = None
lyt_out = None
dernier_idx = None
slice_h = 0
frame_index = 0
_fps_t0, _fps_i0 = time.time(), 0

log("hello_world v%s started — outputs %s / %s / %s, slice mode %s"
    % (PLUGIN_VERSION, SHM_VIDEO, SHM_AUDIO, SHM_ANC,
       "on" if SLICE_MODE else "off"), "info")


def _ouvrir(actuel, nom_actuel, voulu, fabrique, libelle):
    """Lazily open/close a reader. Returns (reader, name, state).

    ★ EACH INPUT IS INDEPENDENT. A missing essence must not hold up the other two:
    that is the difference between "the audio is not wired" and "the plugin does
    not work", which the operator cannot guess if we treat all three as one block."""
    if not voulu:
        if actuel is not None:
            try: actuel.close()
            except Exception: pass
        return None, None, "not wired"
    if actuel is not None and nom_actuel == voulu:
        return actuel, nom_actuel, voulu
    if actuel is not None:
        try: actuel.close()
        except Exception: pass
    try:
        r = fabrique(voulu)
        log("%s input opened on %s" % (libelle, voulu), "info")
        return r, voulu, voulu
    except Exception:
        return None, None, "waiting"   # the flow is not published yet


while True:
    try:
        with state_lock:
            v_voulu, a_voulu, d_voulu = state["input_shm"], state["audio_shm"], state["anc_shm"]
            fond_nom, pip_on = state["fond"], state["pip_on"]
            dispo = {{k: dict(v) for k, v in state["dispo"].items()}}
            omega = state["coefficient_omega"]
        # ★ THE DECISION IS TAKEN HERE, NOT AFTER THE READ. It depends only on the
        # PiP's placement — so we know it before touching the input, and it is what
        # says HOW to read: one slice, or the whole frame.
        tranchable = (not pip_on) or pip_tranchable(dispo["pip"])
        t0 = time.time()
        entrees = {{}}
        lat = {{}}

        lec_v, nom_v, entrees["video"] = _ouvrir(
            lec_v, nom_v, v_voulu, lambda n: bobimxl.Reader(inst, n), "video")
        lec_a, nom_a, entrees["audio"] = _ouvrir(
            lec_a, nom_a, a_voulu, lambda n: bobimxl.AudioReader(inst, n), "audio")
        _av_d = nom_d
        lec_d, nom_d, entrees["anc"] = _ouvrir(
            lec_d, nom_d, d_voulu, lambda n: bobimxl.Reader(inst, n), "ANC")
        if nom_d != _av_d:
            fd_anc[0] = None

        # ── Video: the format comes from the FLOW_DEF, never from the grain ───
        # ⚠ `Reader.format()` — NOT the grain. A grain carries bytes only; its
        # layout lives in the flow_def, written by the producer. That is the
        # source of truth on the data side: it cannot diverge from the bytes, as
        # a constant or an orchestrator parameter can.
        vue_in = idx = None
        lyt_in = None
        if lec_v is not None:
            tv = time.time()
            f_in = lec_v.format()
            if f_in:
                lyt_in = disposition(f_in)
                idx = lec_v.head_index()
                # ⚠ 1:1 INPUT LOCK. `get_slice` returns IMMEDIATELY if the head grain
                # already has the requested slice: without this test the loop
                # reprocesses the SAME source frame and publishes two outputs per
                # input. Measured before the fix: 100.1 fps out for a source at 49.8.
                # No error, no counter at fault — the output simply has a cadence that
                # lies, and downstream inherits duplicated indices. We wait for a NEW
                # index to appear.
                if idx == dernier_idx:
                    time.sleep(0.001)
                    continue
                # ⚠ READING ONE SLICE THEN COMPOSING THE WHOLE FRAME = A TORN
                # PICTURE. The test was on SLICE_MODE (the global setting) instead
                # of `tranchable` (what the geometry REALLY allows). Moving the PiP
                # off the bottom edge made the stage fall back to whole-frame — but
                # it kept asking for the FIRST SLICE of the source only. The rest of
                # the frame was whatever the ring still held: the BOTTOM of the
                # previous picture. On screen, combing and jumps backwards; on the
                # counters, nothing at all.
                got = (lec_v.get_slice(idx, 1, timeout_ns=40_000_000) if SLICE_MODE
                       else lec_v.get_latest())
                # ⚠ (index, grainInfo, view) — a TUPLE. Taking it for an object with
                # planes costs one exception per frame, caught by the loop: the
                # container runs, answers, and emits nothing.
                if got is not None:
                    idx, _gi_in, vue_in = got
                    # `get_latest` returns the last COMPLETE grain, which may be the
                    # one from the previous turn if the head is still being written.
                    # So the 1:1 lock applies to the index RECEIVED as well.
                    if idx == dernier_idx:
                        time.sleep(0.001)
                        continue
                    lat["video"] = round((time.time() - tv) * 1000.0, 2)
            if vue_in is None:
                # Wired but silent: this is NOT "not wired". Confusing the two sends
                # the operator to check cabling that is fine.
                entrees["video"] = "no signal"
                idx = None

        if lyt_in is not None and vue_in is not None:
            nouveau = (lyt_in["width"], lyt_in["height"], lyt_in["chroma"],
                       lyt_in["bit_depth"], lyt_in["fps_num"], lyt_in["fps_den"])
        else:
            nouveau = (int(CONFIG.get("width") or 1920), int(CONFIG.get("height") or 1080),
                       "422", 8, int(CONFIG.get("fps") or 25), 1)

        # ── The three outputs, (re)created when the format changes ───────────
        # ★ THE OUTPUT DOES NOT DEPEND ON ITS PRODUCER. All three flows are
        # published even with no input at all: a coloured background, audio
        # SILENCE, and a REGENERATED ATC. A subscribed downstream must not see its
        # chain go dark because an upstream source fell over — the rule holds for
        # an example as much as for an on-air engine.
        # ★ WHAT THE PiP'S PLACEMENT CHANGES IS THE FRAME IT COMES FROM — NOT
        # WHETHER WE SLICE. See `pip_tranchable`: off the bottom edge, the inset
        # needs input lines the current slice does not have yet. We do not give up
        # slicing for that — we take the PiP from the PREVIOUS frame, which is
        # complete. The output stays published band by band, and only the inset is
        # one frame behind.
        repli = None if tranchable else "PiP pris dans la trame precedente"
        if nouveau != fmt or ecr_v is None:
            fmt = nouveau
            w, h = fmt[0], fmt[1]
            slice_h = slice_height_pour(h) if SLICE_MODE else 0
            for e in (ecr_v, ecr_a, ecr_d):
                try:
                    if e is not None: e.close()
                except Exception: pass
            lyt_out = disposition({{"width": w, "height": h, "chroma": fmt[2],
                                   "bit_depth": fmt[3], "fps_num": fmt[4], "fps_den": fmt[5]}})
            ecr_v = bobimxl.Writer(inst, SHM_VIDEO, w, h, fmt[2], fmt[3], fmt[4], fmt[5],
                                   **({{"slice_height": int(slice_h)}} if slice_h else {{}}))
            ecr_a = bobimxl.AudioWriter(inst, SHM_AUDIO, CANAUX, TAUX)
            # ★ ANC AS RFC 8331, NOT AS A HOUSE FORMAT. A stock MXL SDK reading a
            # house-format grain deduces "0 ANC packets" and concludes WITHOUT ERROR
            # that the flow carries none: silent loss of timecode, tally and
            # subtitles. The normative format is the only interoperable one.
            ecr_d = bobimxl.Writer(inst, SHM_ANC, 0, 0,
                                   flow_def=bobimxl.build_data_flow_def(SHM_ANC, fmt[4], fmt[5]))
            log("outputs (re)created at %dx%d, slices of %s"
                % (w, h, ("%d lines" % slice_h) if slice_h else "— (whole frame)"), "info")

        w, h = fmt[0], fmt[1]
        fps_aff = round(fmt[4] / float(fmt[5] or 1), 2)

        # ── Audio: read, measure, re-emit ───────────────────────────────────
        n_ech = int(round(TAUX * fmt[5] / float(fmt[4])))
        audio = None
        if lec_a is not None:
            ta = time.time()
            # ⚠ TWO AUDIO TRAPS. `head_index` is ONE PAST THE END: the last samples
            # are [head − count, head), and `read_latest` handles that — asking for
            # [head, head+count) would return a window still being written, and the
            # meters would only ever return None. And an audio flow has NO
            # `lastWriteTime`: its freshness is not judged as a video's is, only the
            # index's progress tells it.
            audio = lec_a.read_latest(n_ech)
            if audio is None:
                entrees["audio"] = "no signal"
            else:
                lat["audio"] = round((time.time() - ta) * 1000.0, 2)
        if audio is None:
            # SILENCE, not "nothing": a downstream expecting audio must receive
            # some, or it stalls or infers a fault that does not exist.
            audio = np.zeros((n_ech, CANAUX), dtype=np.float32)
        try:
            ecr_a.write(audio)
        except Exception as e:
            log("audio write failed: %r" % (e,), "warning")

        pics = np.abs(audio).max(axis=0) if audio.size else np.zeros(CANAUX, np.float32)
        niveaux = [float(20.0 * np.log10(max(1e-6, float(p)))) for p in pics]
        crete = max(niveaux) if niveaux else None
        # ★ DOMINANT FREQUENCY, measured — not declared. An FFT over the frame's
        # window is enough for a readout: the resolution is rate / n_samples
        # (≈ 50 Hz at 50 fps), which is honest for a 1 kHz reference tone and wrong
        # for speech. So we only display it when a peak clearly dominates —
        # otherwise we return None, and the readout stays dark rather than invent a
        # number.
        freq = None
        try:
            if audio.size and crete is not None and crete > -50.0:
                mono = audio[:, int(np.argmax(pics))].astype(np.float32)
                spec = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
                if spec.size > 2:
                    spec[0] = 0.0
                    k = int(np.argmax(spec))
                    if spec[k] > 4.0 * float(np.median(spec) + 1e-9):
                        freq = round(k * TAUX / float(len(mono)), 1)
        except Exception:
            freq = None

        # ── ANC: decode the timecode, then RE-EMIT it ───────────────────────
        atc = None
        tc_origine = _t("horloge locale (TAI)", "local clock (TAI)")
        if lec_d is not None:
            td = time.time()
            g = lec_d.get_latest()
            if g is None:
                entrees["anc"] = "no signal"
            else:
                lat["anc"] = round((time.time() - td) * 1000.0, 2)
                # ⚠ TWO TRAPS HERE, AND BOTH WERE SPRUNG.
                #
                # 1. `get_latest()` returns (index, grainInfo, VIEW). Passing the tuple
                #    to `anc_unpack` raises — and an `except: atc = None` turned that
                #    into "no timecode", hence a silent regeneration from our own
                #    clock. The displayed TC followed real time and looked perfectly
                #    credible: it was the operator who eventually noticed that a
                #    ten-second loop could not be carrying UTC.
                #
                # 2. Without `flow_def`, `anc_unpack` picks the HOUSE decoder instead
                #    of RFC 8331. The grain then decodes to "zero packets" WITH NO
                #    error — silent loss of timecode, tally and subtitles. It is
                #    written in plain words in bobimxl, and I fell into it anyway.
                try:
                    _i_d, _gi_d, vue_d = g
                    if fd_anc[0] is None:
                        fd_anc[0] = inst.flow_def(nom_d)
                    paquets = bobimxl.anc_unpack(vue_d, fd_anc[0])
                    atc = bobimxl.anc_atc_decode(paquets)
                    if atc is not None:
                        tc_origine = _t("ANC de la source", "source ANC")
                    else:
                        entrees["anc"] = "%s (%s)" % (nom_d, _t("aucun ATC", "no ATC"))
                except Exception as e:
                    # ★ WE DO NOT FALL BACK IN SILENCE. A plausible fallback value is
                    # worse than an absence: it hides the fault. The state SAYS so, and
                    # the log gives the cause.
                    entrees["anc"] = "%s (%s)" % (nom_d, _t("ANC illisible", "ANC unreadable"))
                    log("ANC illisible sur %s : %r" % (nom_d, e), "warning")
                    atc = None
        if atc is None:
            # ── REGENERATED timecode: the server's time, but on the RIGHT clock ──
            # ★ THE QUESTION IS NOT "what time", IT IS "WHICH CLOCK". Deriving a
            # timecode from `time.time()` gives the container's system clock,
            # disciplined by NTP — tens of milliseconds away from the PTP grid that
            # paces the flows (we have already measured a grandmaster serving NTP
            # 100 ms behind its own PTP). The frame number would jump or repeat at
            # second boundaries, with no counter to signal it.
            #
            # So we take the CURRENT grain index on the TAI ST 2059 grid — exactly
            # the coordinate a Writer in "tai" mode would assign to a grain written
            # now. The frame number follows by modulo, so it is frame-aligned by
            # construction. Fall back to the system clock if the grid is not
            # available: an approximate timecode beats a silent ANC output.
            try:
                gi = bobimxl.current_index(fmt[4], fmt[5])
                cadence = max(1, int(round(fmt[4] / float(fmt[5] or 1))))
                secondes = gi // cadence
                trame = int(gi % cadence)
                # TAI → UTC: the offset is centralised in bobimxl (37 s), and
                # forgetting it would shift the timecode by half a minute in silence.
                lt = time.localtime(secondes - bobimxl.TAI_UTC_OFFSET_S)
                atc = (lt.tm_hour, lt.tm_min, lt.tm_sec, trame, False)
            except Exception:
                lt = time.localtime()
                atc = (lt.tm_hour, lt.tm_min, lt.tm_sec,
                       int((time.time() % 1.0) * fps_aff), False)
        tc = "%02d:%02d:%02d:%02d" % atc[:4]
        _ORIGINE_TC[0] = tc_origine
        try:
            blob = bobimxl.anc_pack_rfc8331([{{
                "did": 0x60, "sdid": 0x60, "line": 9, "hori": 0xFFF,
                "udw": bobimxl.anc_atc_encode(atc[0], atc[1], atc[2], atc[3]),
            }}])
            _i, gi_d, vue_d = ecr_d.open_grain(index=idx)
            src = np.frombuffer(blob, dtype=np.uint8)
            kk = min(src.size, vue_d.size)
            vue_d[:kk] = src[:kk]
            ecr_d.commit(gi_d)
        except Exception as e:
            # Diagnostics: NEVER break the video cadence for ANC.
            log("ANC write failed: %r" % (e,), "debug")

        # ── Video: composition ──────────────────────────────────────────────
        # ☕ 10, like the team. Nothing else.
        generique = generique_pour(w, h) if abs(omega - 10.0) < 1e-9 else None
        gen_offset = 0
        if generique is not None:
            # Only the offset advances: the column itself stays cached.
            #
            # ★ IN PIXELS PER SECOND, NOT PER FRAME. Counting frames tied the speed
            # to the cadence: the same credits rolled twice as fast at 50 fps as at
            # 25. We refer it to TIME, and express it relative to the height so that
            # UHD does not crawl.
            vitesse = h / 16.0                       # ≈ 68 px/s at 1080
            course = generique.shape[0] + h
            gen_offset = int(((time.time() - DEMARRAGE) * vitesse) % course) - h

        # ⚠ WE DO NOT RENDER WHAT WE ARE NOT GOING TO COMPOSITE. `incruster()` returned
        # early on `overlay_on` — but AFTER `overlay_pour()` had drawn everything. Turning
        # the overlay off therefore saved only the blend, never the render: the
        # "overlay OFF" measurement, taken as a reference, was comparing the same cost
        # twice. A switch that does not turn off what it claims to is worse than no switch
        # at all. Same when the credits roll: they cover everything, so we do not draw
        # underneath.
        with state_lock:
            _ov_on = state["overlay_on"]
        if generique is None and _ov_on:
            ov, ova, ov_h, ov_w = overlay_pour(w, h, fps_aff, entrees, tc, crete, dispo["texte"])
        else:
            ov = ova = None
            ov_h = ov_w = 0
        _, tal_video = _tally_de("video")
        fy_h, fy_b, fu, fv = FONDS.get(fond_nom, FONDS["ardoise"])
        if lyt_out["bit_depth"] > 8:      # the constants are 8-bit
            d_ = lyt_out["bit_depth"] - 8
            fy_h, fy_b, fu, fv = [c << d_ for c in (fy_h, fy_b, fu, fv)]
        # ★ PiP INDEX TABLES, memoised. They depend only on the SOURCE format, the
        # output format and the rectangle: recomputing them per band and per frame
        # cost 3 ms, when they change only as the operator moves the PiP — that is,
        # never during a transmission.
        _p = dispo["pip"]
        pip_x0, pip_y0 = int(_p["x"] * w), int(_p["y"] * h)
        pip_w, pip_h = max(2, int(_p["w"] * w)), max(2, int(_p["h"] * h))
        pip_x0 = min(pip_x0, max(0, w - pip_w))
        pip_y0 = min(pip_y0, max(0, h - pip_h))

        # ★ THE RECTANGLE IS A PLACE, NOT A DISTORTION. Stretching the source to
        # fill the box gives elongated or squashed faces — a WRONG picture no counter
        # flags and that ends up blamed on the source. So we fit the picture, at its
        # own ratio, INSIDE the box; the rest of the box keeps the background.
        #
        # ⚠ AND WE ANCHOR IT AT THE BOTTOM, never centred. If the fit shortens the
        # height, centring would lift the picture off the bottom edge — and slice
        # mode requires precisely that the PiP's last line falls on the output's last
        # line (otherwise it needs input lines not yet received). An "aesthetic"
        # centring would therefore silently push the stage back to whole-frame,
        # without `tranchable` — computed on the BOX — ever seeing it.
        #
        # ⚠ The ratio comes from the DIMENSIONS, so square pixels are assumed: an
        # anamorphic source would stay distorted. None of our inputs are; if that
        # changes, this is where the PAR belongs.
        if lyt_in:
            _ar_src = lyt_in["width"] / max(1, lyt_in["height"])
            _ar_box = pip_w / max(1, pip_h)
            if _ar_box > _ar_src:                      # box too wide → trim the width
                _nw = max(2, int(pip_h * _ar_src))
                pip_x0 += (pip_w - _nw) // 2           # horizontally centred
                pip_w = _nw
            elif _ar_box < _ar_src:                    # box too tall → trim the height
                _nh = max(2, int(pip_w / _ar_src))
                pip_y0 += (pip_h - _nh)                # anchored AT THE BOTTOM, see above
                pip_h = _nh

        # Build (or reuse) the PiP index tables.
        _sig_pip = (w, h, pip_x0, pip_y0, pip_w, pip_h,
                    lyt_in["width"] if lyt_in else 0, lyt_in["height"] if lyt_in else 0,
                    lyt_out["cw"], lyt_out["ch"])
        if _pip_map[0] != _sig_pip:
            if lyt_in:
                sh, sw = lyt_in["height"], lyt_in["width"]
                chh, cww = lyt_out["ch"], lyt_out["cw"]
                _map_y = np.clip((np.arange(pip_h) * sh) // max(1, pip_h), 0, sh - 1)
                _map_x = np.clip((np.arange(pip_w) * sw) // max(1, pip_w), 0, sw - 1)
                cph, cpw_ = max(1, pip_h // chh), max(1, pip_w // cww)
                _map_cy = np.clip((np.arange(cph) * lyt_in["uv_h"]) // cph, 0, lyt_in["uv_h"] - 1)
                _map_cx = np.clip((np.arange(cpw_) * lyt_in["uv_w"]) // cpw_, 0, lyt_in["uv_w"] - 1)
                _pip_map[0] = _sig_pip
                _pip_map[1] = (_map_y, _map_x, _map_cy, _map_cx)
            else:
                _pip_map[0], _pip_map[1] = None, None
        _map_y, _map_x, _map_cy, _map_cx = (_pip_map[1] or (None, None, None, None))

        # ★ PROPAGATE THE SOURCE INDEX when there is one: the frame leaves with its
        # original timestamp, which preserves inter-flow alignment and field parity.
        # A consequence worth knowing: this stage's index delta is then 0, and a
        # probe measuring latency by index difference would read 0 on a chain that
        # really is delayed.
        _gidx, grain, vue = ecr_v.open_grain(src_index=idx)
        oy, ou, ov_u = plans(vue, lyt_out)          # zero-copy VIEWS on the grain

        courant = {{"p": None}}
        if vue_in is not None and lyt_in is not None:
            courant["p"] = plans(vue_in, lyt_in)

        # ★ THE DELAYED PiP. When the geometry does not allow serving it from the
        # current frame, we read the PREVIOUS grain — `get` returns a complete grain,
        # so no line is missing and nothing is torn. Cost: one frame of delay on the
        # inset ALONE, against one frame of latency on the WHOLE output if we went
        # back to whole-frame. For a thumbnail the choice is easy; and it is
        # published (`pip_retard_trames`) rather than left unsaid.
        pip_ret = {{"p": None}}
        if pip_on and not tranchable and slice_h and lec_v is not None and idx is not None:
            try:
                gprec = lec_v.get(idx - 1, timeout_ns=20_000_000)
                if gprec is not None:
                    pip_ret["p"] = plans(gprec[2], lyt_in)
            except Exception as e:
                log("trame precedente illisible pour le PiP : %r" % (e,), "warning")
            if pip_ret["p"] is None:
                # ⚠ WE DO NOT COMPOSITE A TORN THUMBNAIL. With no complete frame we
                # skip the PiP for this turn: a missing thumbnail is seen and
                # understood, a half-new half-old one passes for a fault in the
                # SOURCE.
                repli = "PiP saute : trame precedente indisponible"

        def composer(d, f):
            """Write output lines [d, f). Everything in here is LINE-LOCAL."""
            # Vertical gradient: the value depends only on the line index.
            ys = np.arange(d, f, dtype=np.float32) / max(1, h - 1)
            oy[d:f, :] = (fy_h + (fy_b - fy_h) * ys)[:, None].astype(oy.dtype)
            # ⚠ `ch`: in 4:2:0 chroma has HALF the lines, in 4:2:2 it has as many.
            # Writing `d // 2` "because it is chroma" shifts the colour by a factor
            # of two over half the picture, in 4:2:2.
            cd, cf = d // lyt_out["ch"], f // lyt_out["ch"]
            ou[cd:cf, :] = fu
            ov_u[cd:cf, :] = fv
            # ★ THE CREDITS TAKE THE WHOLE SCREEN. While they roll, the rest of the
            # overlay is SKIPPED — not drawn then covered. Two reasons: readable
            # credits have nothing else on screen, and above all we do not run a
            # render whose result we throw away. The stage sits at 18.8 ms on a
            # 20 ms budget: composing an invisible panel would cost exactly what we
            # do not have.
            if generique is not None:
                derouler(oy[d:f, :], d, h, generique, gen_offset)
                return
            # The PiP follows its own source: the current frame when the geometry
            # allows, the previous one otherwise. The rest of the overlay is always
            # computed on the band in hand.
            sp = pip_ret["p"] if pip_ret["p"] is not None else (
                None if (pip_on and not tranchable) else courant["p"])
            sy, su, sv = (sp if sp is not None else (None, None, None))
            if pip_on and sy is not None:
                # ⚠ CLAMPED TO THE PiP'S HEIGHT, not the frame's. While the PiP
                # necessarily touched the bottom, `min(f, h)` was right; with a free
                # rectangle it can end higher, and the index table became shorter
                # than the band to write — "could not broadcast (35,480) into
                # (36,480)", the stage dead on the first raised PiP.
                dd, ff = max(d, pip_y0), min(f, pip_y0 + pip_h)
                if ff > dd:
                    # ★ INDEX TABLES COMPUTED ONCE. The reduction factor is now
                    # ARBITRARY (the editor sets the size), so the step is no longer
                    # an integer and a strided slice no longer does. Recomputing the
                    # indices per band and per frame cost 3 ms — they depend only on
                    # the format and the rectangle, so we keep them.
                    # ⚠ TWO `take` CALLS, ONE PER AXIS, NOT `np.ix_`. Measured on
                    # 1920×1080 → PiP 480×280: `np.ix_` 0.745 ms, two `take` 0.244 ms.
                    # 2D "fancy" indexing jumps around the whole source frame; the row
                    # gather is a memcpy, and the column gather that follows works on
                    # a band that fits in cache.
                    _t = np.take(sy, _map_y[dd - pip_y0:ff - pip_y0], axis=0)
                    np.take(_t, _map_x, axis=1,
                            out=oy[dd:ff, pip_x0:pip_x0 + pip_w])
                    # ★ AND ITS CHROMA. Copying only the Y plane gives a BLACK AND
                    # WHITE PiP on a coloured background — no error, no counter, just
                    # a wrong picture that takes a while to attribute. The chroma
                    # planes subsample with their OWN steps (`ch` for lines, `cw` for
                    # columns): treating them like luma would shift the colour.
                    if su is not None:
                        chh, cww = lyt_out["ch"], lyt_out["cw"]
                        # Same clamping as luma, but in the chroma grid.
                        cpy0 = pip_y0 // chh
                        cdd = max(d // chh, cpy0)
                        cff = min(f // chh, cpy0 + len(_map_cy))
                        cx0, cpw = pip_x0 // cww, len(_map_cx)
                        if cff > cdd and cpw > 0:
                            iy = _map_cy[cdd - cpy0:cff - cpy0]
                            np.take(np.take(su, iy, axis=0), _map_cx, axis=1,
                                    out=ou[cdd:cff, cx0:cx0 + cpw])
                            np.take(np.take(sv, iy, axis=0), _map_cx, axis=1,
                                    out=ov_u[cdd:cff, cx0:cx0 + cpw])
                    # A hairline around the PiP: without it the inset floats on the
                    # background instead of reading as a window.
                    # ★ THE FRAME CARRIES THE TALLY. That is where the eye goes — an
                    # operator looks at the picture, not at the line of text. With no
                    # tally it stays neutral and light: the border's first job is to
                    # say "this is a window".
                    ep = max(2, w // 480)
                    cy_, cu_, cv_ = TALLY_COULEURS.get(tal_video, (210, 128, 128))
                    chh, cww = lyt_out["ch"], lyt_out["cw"]
                    def _bord(y0, y1, x0, x1):
                        if y1 <= y0 or x1 <= x0:
                            return
                        oy[y0:y1, x0:x1] = cy_
                        ou[y0 // chh:y1 // chh, x0 // cww:x1 // cww] = cu_
                        ov_u[y0 // chh:y1 // chh, x0 // cww:x1 // cww] = cv_
                    _bord(dd, ff, pip_x0, pip_x0 + ep)
                    _bord(dd, ff, pip_x0 + pip_w - ep, pip_x0 + pip_w)
                    if dd <= pip_y0 + ep:
                        _bord(dd, min(ff, pip_y0 + ep), pip_x0, pip_x0 + pip_w)
                    if ff >= pip_y0 + pip_h - ep:
                        _bord(max(dd, pip_y0 + pip_h - ep), ff, pip_x0, pip_x0 + pip_w)
            vumetre(oy[d:f, :], d, w, h, niveaux, dispo["vu"])
            incruster(oy[d:f, :], d, h, ov, ova, ov_h, ov_w,
                      ou[d // lyt_out["ch"]:f // lyt_out["ch"], :],
                      ov_u[d // lyt_out["ch"]:f // lyt_out["ch"], :], lyt_out,
                      dispo["texte"])

        if slice_h:
            n = h // slice_h
            for k in range(1, n + 1):
                d, f = (k - 1) * slice_h, k * slice_h
                if lec_v is not None and vue_in is not None and k > 1:
                    got = lec_v.get_slice(idx, k, timeout_ns=40_000_000)
                    if got is None:
                        with metrics_lock:
                            metrics["slices_incompletes"] += 1
                        break
                    courant["p"] = plans(got[2], lyt_in)
                composer(d, f)
                # PROGRESSIVE COMMIT: downstream starts on the first band instead of
                # waiting for the frame. That is the whole gain of slice mode.
                ecr_v.commit(grain, valid_slices=k)
        else:
            composer(0, h)
            ecr_v.commit(grain)

        dernier_idx = idx
        frame_index += 1
        dt = time.time() - _fps_t0
        with metrics_lock:
            metrics["frame_index"] = frame_index
            metrics["source"] = entrees["video"] if vue_in is not None else "fond genere"
            metrics["entrees"] = entrees
            metrics["inputs_latency_ms"] = lat
            metrics["timecode"] = tc
            metrics["audio_crete_dbfs"] = None if crete is None else round(crete, 1)
            metrics["audio_freq_hz"] = freq
            metrics["audio_canaux_dbfs"] = [round(x, 1) for x in niveaux]
            metrics["slice_repli"] = repli
            metrics["pip_retard_trames"] = 1 if (pip_on and not tranchable) else 0
            metrics["tally_age_s"] = (None if _etat_tally() is None
                                      else round(_etat_tally(), 1))
            metrics["slice_mode"] = bool(slice_h)
            metrics["own_latency_ms"] = round((time.time() - t0) * 1000.0, 2)
            if dt >= 1.0:
                metrics["fps"] = round((frame_index - _fps_i0) / dt, 1)
                # REAL panel renders per second. Compare with the frame rate: if the two
                # numbers are equal, the signature cache is doing nothing, and everything
                # this file says about caching is contradicted by what it does.
                with _ov_lock:
                    metrics["overlay_rendus_par_s"] = round(_ov_stats[1] / dt, 1)
                    _ov_stats[0] = _ov_stats[1] = 0
                _fps_t0, _fps_i0 = time.time(), frame_index

        if vue_in is None:
            # With no video source nobody paces us: we hold the cadence ourselves.
            time.sleep(max(0.0, fmt[5] / float(fmt[4]) - (time.time() - t0)))

    except IOError:
        # SIGBUS: a flow was re-created. We start cleanly on the next turn.
        lec_v = lec_a = lec_d = None
        nom_v = nom_a = nom_d = None
        ecr_v = ecr_a = ecr_d = None
        fmt = None
        dernier_idx = None
        time.sleep(0.5)
    except Exception as e:
        # ★ An exception must NEVER kill the loop: the container would restart
        # endlessly, and the operator would read "restarted" in the alerts without
        # ever reading WHY.
        log("erreur : %r" % (e,), "error")
        lec_v = lec_a = lec_d = None
        nom_v = nom_a = nom_d = None
        ecr_v = ecr_a = ecr_d = None
        fmt = None
        dernier_idx = None
        time.sleep(1.0)

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 BOBI SAS, France
#
# Lifecycle hooks for the EXAMPLE plugin hello_world.
#
# ⚠ THIS FILE RUNS IN THE ORCHESTRATOR, not in the container. It is therefore NOT
# a str.format template: braces are ordinary here. In exchange it must stay frugal
# and free of side effects — it is called on the path of an operator's gesture.


def wire_followers(kind, shm, slot, params, ctx):
    """Wiring the VIDEO makes the audio and ANC of the same source follow.

    ★ WHY THIS HOOK EXISTS. Without it the operator wires the video on the Cabling
    page and "the rest does not follow": they have to work out that the container
    has two more inputs, find the audio and ANC flow names of the same producer, and
    wire them by hand. One gesture becomes three, and two of them get forgotten.

    ★ WE DO NOT DERIVE THE NAMES. The source's real flows arrive in
    `ctx["producer_produces"]`: the player publishes `p1`, `p1_audio`, `p1_anc_0` —
    not `p1_0`. Rebuilding names by convention would work on one producer and
    silently not on the next.

    "Always re-follow" policy: (re)wiring the video (re)points the audio and the ANC;
    unwiring (empty shm, or a source with no flows) clears them too — otherwise the
    plugin would keep the audio of a source that has just been unplugged.

    An audio or ANC cable PLACED DIRECTLY triggers no follower: the human chose
    explicitly, and we do not correct them.

    Returns [{essence, shm, state_field}] or None when not applicable."""
    if kind != "video":
        return None
    produces = ctx.get("producer_produces") or []
    audios = [p["shm"] for p in produces if p.get("essence") == "audio"]
    datas = [p["shm"] for p in produces if p.get("essence") == "data"]
    # Only one input per essence here: we take the first. A multi-input plugin
    # would pair them by programme rank (see plugins/2110_io).
    return [
        {"essence": "audio", "shm": (audios[0] if audios else ""), "state_field": "audio_shm"},
        {"essence": "data", "shm": (datas[0] if datas else ""), "state_field": "anc_shm"},
    ]


def tally_targets(params, context):
    """What the TSL distributor must resolve for this container.

    ★ A HOOK, NOT A BRANCH PER TYPE. The distributor knows no plugin: each returns a
    flat list of targets {cle, shm, niveau, label_col}, and the service resolves the
    source's LIVE LABEL and its tally state.

    ★ THE TEXT IS RESOLVED EVEN WITHOUT A TALLY LEVEL, and that is the common case
    here: an example plugin is never on air. Requiring a level in order to get a
    label would have made the function useless in its normal use.

    All three inputs are declared: we want the label of the audio source and of the
    ANC source as much as the video's — that is precisely what lets you check at a
    glance that all three really come from the SAME programme, the costliest
    confusion in three-essence cabling."""
    p = params or {}
    # ⚠ THESE TWO SETTINGS ARE READ HERE, IN THE ORCHESTRATOR — not in the
    # container. They come from `deploy_config.params`, so they only take effect on
    # REDEPLOYMENT: which is why they live in the palette and not on the page,
    # unlike every other setting of this plugin. Putting them on the page would give
    # a control that moves without anything changing, which is worse than no control
    # at all.
    col = int(p.get("tally_label_col") or 0)
    # ★ A LIST OF LEVELS, NOT ONE. Tally ACCUMULATES: the same source can be followed on
    # several destination chains at once, and a scalar forced a choice of which one counts.
    # The "only one" case is just the one-element list — not a different kind of setting.
    # A scalar is still accepted so a container configured before 0.2.0 keeps working
    # without a resave.
    def _niveaux(v):
        if isinstance(v, list):
            return [int(x) for x in v if str(x).strip() not in ("", "0")]
        return [int(v)] if str(v or "").strip() not in ("", "0") else []
    niveaux_defaut = _niveaux(p.get("tally_level"))
    cibles = []
    for cle, champ in (("video", "input_shm"), ("audio", "audio_shm"), ("anc", "anc_shm")):
        shm = (p.get(champ) or "").strip()
        if not shm:
            continue
        cibles.append({
            "cle": cle,
            "shm": shm,
            # Explicit levels, otherwise the project's (resolved by the distributor).
            # Per-essence override when there is one, otherwise the common list,
            # otherwise [] → the distributor takes the project's.
            "niveau": _niveaux(p.get("tally_level_%s" % cle)) or niveaux_defaut,
            "label_col": col,
        })
    return cibles


def before_deploy(params, context):
    """Resolve the output FORMAT from the Settings → Video list.

    ★ WE DO NOT TYPE PIXELS BY HAND. The product already keeps a list of named
    formats (`video_formats`), with their scan, chroma, depth and colorimetry.
    Letting a plugin ask again for "width" and "height" invites typing a format that
    exists nowhere else in the installation — and a hand-typed 1920×1080 says
    NOTHING about scan or depth, two fields that decide the rest of the chain.

    ★ THIS HOOK RUNS IN THE ORCHESTRATOR, and that is what makes it possible: the
    container has no access to the settings. We resolve here, inject the result into
    the params, and the script has only to read them.

    We also pass the LIST of available names (`formats_dispo`): the script
    republishes it in `/state`, which lets the page offer the choice without opening
    one more orchestrator route.

    These values are used ONLY when no video input is wired: with a source, the
    format comes from the flow, which is the only truth on the data side."""
    p = dict(params or {})
    voulu = (p.get("format") or "").strip()
    lignes, choisi = [], None
    try:
        from app import settings as _st
        from app.scripts import get_default_video_format
        reglages = _st.all() if hasattr(_st, "all") else {}
        lignes = [l for l in (reglages.get("video_formats") or "").split("\n") if l.strip()]
        for l in lignes:
            if l.split(";")[0].strip() == voulu:
                choisi = l.split(";")
                break
        if choisi is None:
            # No name, or a name that has vanished from the list: we take the SITE'S
            # default rather than a constant — and we do not leave the stale name in
            # the params, or the page would show a choice that no longer exists as if
            # it were active.
            d = get_default_video_format(reglages)
            p.update({"width": d["width"], "height": d["height"], "fps": int(d["fps"]),
                      "chroma": d.get("chroma") or "422",
                      "bit_depth": int(d.get("bit_depth") or 8)})
            if voulu:
                p["format"] = ""
        else:
            p["width"] = int(choisi[1]); p["height"] = int(choisi[2])
            p["fps"] = int(float(choisi[3]))
            if len(choisi) >= 6:
                p["chroma"] = (choisi[5] or "422").strip()
            if len(choisi) >= 7:
                p["bit_depth"] = int(choisi[6])
    except Exception:
        pass                       # never block a deployment over an overlay
    p["formats_dispo"] = [l.split(";")[0].strip() for l in lignes]
    # ★ THE NAMES OF THE TALLY LEVELS TRAVEL WITH THE PARAMS — same reason as the time zone
    # just below: the container cannot reach the orchestrator's tables, and a bare number
    # ("level 7") sends the reader off to another page to find out what it stands for. We
    # inject only the names of the levels this container actually follows: shipping the whole
    # site's list would go stale on the first rename and grow with every new production.
    try:
        from app.database import db_get_tally_levels
        vus = p.get("tally_level")
        vus = vus if isinstance(vus, list) else ([vus] if vus else [])
        tous = {str(n["id"]): (n.get("nom") or "") for n in (db_get_tally_levels() or [])}
        p["tally_level_noms"] = {str(n): tous.get(str(n), "") for n in vus}
    except Exception:
        p["tally_level_noms"] = {}
    # The orchestrator's time zone travels with the params: it is the only way for
    # the container, which runs in UTC, to display the time the operator reads.
    p["fuseau"] = _fuseau_orchestrateur()
    # ★ THE SYSTEM'S DEFAULT LANGUAGE, not that of the user deploying. What is
    # burnt in goes out in a video stream several people watch — often without an
    # account. A "per user" language therefore makes no sense here: `ui_lang_default`
    # is authoritative, the same setting served to public pages.
    try:
        from app.database import db_get_setting
        lg = str(db_get_setting("ui_lang_default") or "fr").lower()
        p["langue"] = "en" if lg.startswith("en") else "fr"
    except Exception:
        p["langue"] = "fr"
    return p


def _fuseau_orchestrateur():
    """IANA name of the ORCHESTRATOR's time zone (e.g. "Europe/Paris").

    ★ WHY THE ORCHESTRATOR HAS TO SAY IT. A container runs in UTC — checked here:
    the host showed 20:39 CEST while the container showed 18:39 UTC. A naive
    `time.localtime()` in the script would therefore return a time wrong by two
    hours, and wrong in a perfectly credible way: nobody notices a clock off by a
    round number of hours until they look twice.

    ★ AND IT IS A NAME, NOT AN OFFSET. Injecting "+02:00" would freeze summer time:
    the plugin would drift by an hour at the changeover, with no redeployment to fix
    it. The name leaves the conversion to the container, which has the system
    database's 486 zones (checked: `zoneinfo` works there)."""
    import os
    try:
        from datetime import datetime
        z = datetime.now().astimezone().tzinfo
        nom = getattr(z, "key", None)          # zoneinfo → IANA name
        if nom:
            return nom
    except Exception:
        pass
    for chemin in ("/etc/timezone",):
        try:
            with open(chemin, encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    return v
        except Exception:
            pass
    try:
        lien = os.readlink("/etc/localtime")    # …/zoneinfo/Europe/Paris
        if "zoneinfo/" in lien:
            return lien.split("zoneinfo/", 1)[1]
    except Exception:
        pass
    return "UTC"

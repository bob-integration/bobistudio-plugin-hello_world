// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 BOBI SAS, France
//
// Control console for the EXAMPLE plugin hello_world.
// The orchestrator calls window.MXLPlugins.hello_world.mount(el, vmid, ctx).
//
// This file shows four things that are easy to get wrong:
//   1. controls come from the CATALOGUE (window.MXLControls), never rewritten;
//   2. ONE function builds every URL — the public-page contract;
//   3. what does not exist in public mode is SKIPPED, not attempted;
//   4. polling stops on unmount, or it leaks from one page to the next.
//
// ★ THE CATALOGUE IS A RULE, NOT A CONVENIENCE. `controls.css` and `controls.js`
// are loaded by layout.html on EVERY page: knobs, switches and selectors are
// already drawn, already keyboard-accessible, already consistent across pages.
// Redrawing a home-made `<input type="range">` gives a control that looks right,
// that has neither the wheel gesture, nor the fine step, nor return-to-default —
// and that will drift visually at the first theme change. The living inventory is
// under Settings → Controls. Before creating a new one: ask.
(function () {
  // ⚠ PORTÉE DU MODULE, PAS D'UNE FONCTION. Le drapeau « une écriture est en cours » est posé
  // dans `gabarit()` et lu dans `rendreEtat()` : deux fonctions sœurs. Un `const` déclaré dans
  // l'une n'existe pas dans l'autre — la référence LÈVE, et c'est toute la mise à jour d'état
  // qui tombe. (Même piège que la locale orpheline d'un gabarit : `node --check` n'y voit rien.)
  const _ecritureEnCours = new Set();
  // ★ UN RÉGLAGE APPLIQUÉ À CHAUD SE RELIT CHEZ L'ORCHESTRATEUR, PAS DANS `/state`.
  // Le conteneur répond avec la configuration qui lui a été remise à SON DÉPLOIEMENT : une
  // photo, pas un miroir. Tant qu'un réglage redéployait, la photo restait fraîche et personne
  // ne voyait la différence. Depuis qu'un réglage s'applique à chaud, elle ne l'est plus : on
  // retire un niveau, la base l'enregistre, et `/state` rend encore l'ancienne liste — la page
  // se reconstruit dessus et défait le geste. En mode public il n'y a pas d'orchestrateur à
  // joindre : la page y est en lecture seule, et `/state` suffit.
  const _persiste = {};
  "use strict";

  let EL = null, VMID = null, TOAST = () => {};
  let timer = null;

  // ★ PUBLIC-PAGE CONTRACT. A /p/<token> link mounts this same console with a
  // different API base. EVERY URL goes through `api()`: scattering `if (public)`
  // through the calls would eventually miss one, which would hit the private API
  // from the public page and fail with a 401 explaining nothing to the operator.
  // One function, one place to check.
  let BASE = null;              // e.g. "/s/<token>"; null → private API by vmid
  let PUBLIC = false;
  const api = (chemin) => BASE ? (BASE + "/plugin" + chemin)
                               : ("/api/containers/" + VMID + "/plugin" + chemin);
  // ★ WHAT IS NOT BEHIND THE PLUGIN PROXY DOES NOT EXIST IN PUBLIC MODE. The
  // `/api/containers/<vmid>/…` routes are not relayed by a token: we SKIP them
  // rather than attempt them and collect a 404 with no explanation.
  const apiConteneur = (chemin) => BASE ? null : ("/api/containers/" + VMID + chemin);

  // ★ i18n IS MANDATORY FOR ANY NEW UI. The labels live in the plugin's
  // i18n/{fr,en}.json, under the `plugin.hello_world.` prefix. The fallback keeps
  // readable text when a key is missing: showing the raw key to the operator would
  // be worse than the French sentence.
  const T = (cle, repli) => {
    const k = "plugin.hello_world." + cle;
    const v = (window.I18N && window.I18N[k]);
    return (v && v !== k) ? v : repli;
  };

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function lireEtat() {
    // /state is declared in the manifest's control.read_endpoints: that is what
    // makes it readable from the public page too, with the login alone.
    const r = await fetch(api("/state"), { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  async function envoyer(chemin, corps) {
    // ★ IN PUBLIC MODE WE DO NOT WRITE. The relay is read-only (GET only):
    // attempting a POST would return 405. We skip, and the interface says so.
    if (PUBLIC) { TOAST(T("lecture_seule", "Lien public : lecture seule")); return; }
    const r = await fetch(api(chemin), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corps || {}),
    });
    if (!r.ok) { TOAST(T("echec", "Échec : HTTP {c}").replace("{c}", r.status)); return; }
    rafraichir();
  }

  // The EXACT markup `MXLControls.attachKnobGestures` knows how to animate. We
  // reinvent neither the drawing (knobSvg) nor the gesture: wheel, drag, arrows,
  // fine step and return-to-default all come with it.
  function knob(id, label, min, max, pas, def, unite) {
    const v01 = (def - min) / (max - min || 1);
    return `<span class="ctl-knob ctl-knob--arc" id="hw-${id}" data-min="${min}" data-max="${max}"
              data-step="${pas}" data-val="${def}" data-def="${def}" data-unit="${unite}">
      <button type="button" class="ctl-knob-hit" role="slider" aria-label="${esc(label)}"
        aria-valuemin="${min}" aria-valuemax="${max}" aria-valuenow="${def}">${
        window.MXLControls ? window.MXLControls.knobSvg("arc", v01, v01) : ""
      }</button><span class="ctl-knob-val">${def}${esc(unite)}</span>
      <span class="ctl-knob-name">${esc(label)}</span></span>`;
  }

  // ★ THE PAGE IS ZONED BY NATURE OF SETTING, not by writing order. Four zones,
  // and the boundary that matters is the THIRD: what applies live on one side,
  // what REDEPLOYS (and so cuts the stream for a second) on the other. Mixing the
  // two lets an operator take the output off air believing they moved a slider.
  // The switches live with what they command — a boolean placed far from its
  // object forces you to guess its scope.
  function gabarit() {
    EL.innerHTML = `
      <div class="hw-wrap">
        <p class="hw-note">${T("titre_note", "Plugin d'<strong>exemple</strong>.")}</p>

        <section class="hw-sec">
          <h2 class="hw-sec-t">${esc(T("sec_etat", "État"))}</h2>
          <div class="hw-temoins" id="hw-temoins"></div>
          <div class="hw-repli" id="hw-repli"></div>
          <div class="hw-grid" id="hw-etat"><span class="hw-vide">${esc(T("chargement", "Chargement…"))}</span></div>
        </section>

        <section class="hw-sec">
          <h2 class="hw-sec-t">${esc(T("sec_dispo", "Disposition"))}</h2>
          <div class="hw-lay" id="hw-lay">
            <div class="hw-lay-outils" id="hw-lay-outils"></div>
            <div class="hw-lay-scene" id="hw-lay-scene" tabindex="0"
                 role="application" aria-label="${esc(T("lay_titre", "Disposition"))}"></div>
            <div class="hw-lay-pied">
              <small class="hw-lay-tranche" id="hw-lay-tranche"></small>
              <small class="hw-aide">${esc(T("lay_aide",
                "Glisser pour déplacer, la poignée pour redimensionner. Maj ou Ctrl pour une sélection multiple : le DERNIER cliqué sert de référence aux alignements."))}</small>
            </div>
          </div>
        </section>

        <section class="hw-sec">
          <h2 class="hw-sec-t">${esc(T("sec_habillage", "Habillage"))}</h2>
          <div class="hw-switches">
            <label class="ctl-switch-inline"><input type="checkbox" class="ctl-switch" id="hw-ov">
              <span>${esc(T("ov_lab", "Incrustation"))}</span></label>
            <label class="ctl-switch-inline"><input type="checkbox" class="ctl-switch" id="hw-pip">
              <span>${esc(T("pip_lab", "PiP de la source"))}</span></label>
          </div>
          <div class="hw-controles">
            <label>${esc(T("texte", "Texte incrusté"))}
              <input type="text" id="hw-texte" maxlength="64" class="ctl-input">
            </label>
            <label>${esc(T("fond", "Couleur de fond"))}
              <select id="hw-fond" class="ctl-input"></select>
            </label>
          </div>
        </section>

        <section class="hw-sec" id="hw-redeploy">
<h2 class="hw-sec-t">${esc(T("sec_deploy", "Réglage qui redéploie"))}</h2>
          <p class="hw-aide">${esc(T("t_aide",
            "Le conteneur lit ce réglage à son DÉMARRAGE : le changer redéploie le plugin (brève coupure)."))}</p>
          <div class="hw-controles">
            <label>${esc(T("fmt", "Format de sortie (sans entrée câblée)"))}
              <select id="hw-fmt" class="ctl-input"></select>
            </label>
          </div>
        </section>

        <section class="hw-sec">
          <!-- ★ DEUX SECTIONS, PARCE QUE CE SONT DEUX COMPORTEMENTS. Ces réglages-ci ne sont
               jamais lus par le conteneur : c'est l'ORCHESTRATEUR qui les consulte (distributeur
               TSL, hook « tally_targets »), à chaque tour, dans « deploy_config ». Les ranger
               avec le format faisait craindre une coupure de flux à chaque case cochée — et
               pendant longtemps c'en était vraiment une, pour rien.
               ⚠ AUCUN ACCENT GRAVE ICI : ce commentaire vit dans un gabarit JS, où un accent
               grave FERME la chaîne. -->
          <h2 class="hw-sec-t">${esc(T("sec_chaud", "Réglages appliqués à chaud"))}</h2>
          <p class="hw-aide">${esc(T("t_aide_chaud",
            "Lus par l'orchestrateur, jamais par le conteneur : ils prennent effet SANS redéployer, donc sans coupure. Seul le texte incrusté dans l'image attend le prochain déploiement."))}</p>
          <div class="hw-controles">
            <label>${esc(T("t_col", "Libellé de source à afficher"))}
              <select id="hw-tcol" class="ctl-input"></select>
            </label>
<!-- ⚠ PAS DE <label> AUTOUR D'UN CONTRÔLE À PLUSIEURS BOUTONS. Un <label> sans « for »
                 renvoie TOUT clic vers le premier contrôle qu'il contient — ici la croix de la
                 PREMIÈRE puce. Cliquer à côté d'une puce supprimait donc le premier niveau, ce
                 qui donnait l'impression que le contrôle retirait n'importe quoi. Un <label>
                 convient à un champ unique (le menu juste au-dessus), pas à une liste d'actions. -->
            <div class="hw-champ">
              <span class="hw-champ-t">${esc(T("t_niv", "Niveaux de tally suivis"))}</span>
              <div id="hw-tniv"></div>
              <small class="hw-hint">${esc(T("t_niv_aide",
                "Plusieurs choix possibles — le tally se cumule. Aucun = ceux de la production."))}</small>
            </div>
          </div>
        </section>

        <section class="hw-sec">
          <h2 class="hw-sec-t">${esc(T("sec_omega", "Coefficient oméga"))}</h2>
          <div class="hw-omega-bloc">
            <div class="hw-knobs">${knob("omega", T("omega", "Coefficient oméga"), 0, 20, 1, 0, "")}</div>
            <div class="hw-jauge">
              <span class="ctl-gauge" id="hw-omega-g" role="img"
                    aria-label="${esc(T("omega_charge", "Charge du coefficient oméga"))}"
                    style="--ctl-gauge-w:100%;--ctl-gauge-seuil:100%">
                <span class="ctl-gauge-fill" style="transform:scaleX(0)"></span></span>
              <small class="hw-aide">${esc(T("omega_aide", "Sans effet mesurable sur la chaîne de traitement."))}</small>
            </div>
          </div>
        </section>

        <div class="hw-pied-actions">
          <button type="button" id="hw-reset">${esc(T("reset", "Valeurs par défaut"))}</button>
        </div>
      </div>`;
    if (PUBLIC) {
      // We DISABLE visibly rather than hide: a control that disappears looks like
      // a bug, a greyed-out control explains itself.
      EL.querySelectorAll(".hw-controles input, .hw-controles select, .hw-switches input, .hw-pied-actions button")
        .forEach((n) => { n.disabled = true; n.title = T("lecture_seule", "Lien public : lecture seule"); });
    }

    const $ = (id) => EL.querySelector("#" + id);
    $("hw-texte").addEventListener("change", (e) => envoyer("/params", { texte: e.target.value }));
    // ★ ONE EVENT for all the knobs. The catalogue emits `ctl-knob-input` with
    // detail.value; it does not know what the value COMMANDS, and does not need
    // to.
    EL.addEventListener("ctl-knob-input", (e) => {
      const id = (e.target.closest(".ctl-knob") || {}).id || "";
      const v = e.detail && e.detail.value;
      if (id === "hw-omega") envoyer("/params", { coefficient_omega: v });
    });
    $("hw-ov").addEventListener("change", (e) => envoyer("/overlay", { on: e.target.checked }));
    $("hw-pip").addEventListener("change", (e) => envoyer("/pip", { on: e.target.checked }));
    $("hw-reset").addEventListener("click", () => envoyer("/reset", {}));
    // ★ THE LIST COMES FROM THE CONTAINER, not from a table frozen here. The same
    // endpoint (`/couleurs`) feeds the macro editor through `options_endpoint`: a
    // colour added to the plugin appears on both sides without touching the front.
    fetch(api("/couleurs"), { cache: "no-store" })
      .then((r) => r.json())
      .then((j) => {
        $("hw-fond").innerHTML = (j.options || [])
          .map((o) => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join("");
      })
      .catch(() => {});
    $("hw-fond").addEventListener("change", (e) => envoyer("/fond", { couleur: e.target.value }));

    monterEditeur();

    // ── Settings read by the ORCHESTRATOR ─────────────────────────────────
    // They live in `config_schema`, so they go through the container's
    // configuration route — which persists to deploy_config THEN redeploys. We SAY
    // so under the fields: a control that briefly cuts the stream must not look
    // like an ordinary slider.
    const opts = (el, liste, val) => {
      el.innerHTML = liste.map(([v, l]) =>
        `<option value="${esc(v)}"${String(v) === String(val) ? " selected" : ""}>${esc(l)}</option>`).join("");
    };
    const COLS = [["0", T("col0", "Nom du conteneur source")], ["1", T("col1", "Nom du flux MXL")]]
      .concat([2, 3, 4, 5, 6, 7, 8, 9].map((i) => [String(i), T("coln", "Libellé {n}").replace("{n}", i)]));
    opts($("hw-tcol"), COLS, 0);
    // ★ NO STATIC LIST OF LEVELS ANY MORE. It used to be [0,1,2,3,4] — band numbers from the
    // TSL frame, frozen in the page. Levels are named entities of the site now, they come from
    // /state (see `majEtat`), and there can be any number of them.
    // ★ ON GROUPE LES GESTES, ET ON RÉESSAIE SUR 409.
    //
    // Chaque écriture ici REDÉPLOIE le conteneur, et l'orchestrateur refuse un second
    // déploiement tant que le premier est en vol (`_plugin_config_pending` → 409). Une
    // sélection multiple s'édite par gestes SUCCESSIFS : trois niveaux choisis coup sur coup
    // faisaient trois POST, dont deux repartaient en 409 — perdus, alors que les trois puces
    // restaient à l'écran. On croyait avoir réglé trois niveaux, un seul était persisté, et le
    // retrait suivant révélait la vérité en faisant « disparaître » les autres.
    // (Signalé le 2026-09-01 : « j'ai ajouté les 3 niveaux, supprimé le 1, et le 2 s'est
    // supprimé aussi ».)
    //
    // Deux corrections, et il faut les deux : on ATTEND que les gestes se calment avant
    // d'envoyer (une rafale devient un seul déploiement), et on RÉESSAIE si un déploiement
    // venu d'ailleurs occupe la place. Un échec définitif RESYNCHRONISE l'affichage sur
    // l'état réel — laisser une valeur optimiste à l'écran est ce qui a rendu ce défaut si
    // difficile à voir.
    const ATTENTE_MS = 500, ESSAIS_409 = 6;
    const _enAttente = {};          // clé → timer

    const _poster = async (cle, valeur, reste) => {
      const url = apiConteneur("/plugin_config");
      if (!url) { TOAST(T("lecture_seule", "Lien public : lecture seule")); return; }
      _ecritureEnCours.add(cle);
      try {
        const r = await fetch(url, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ params: { [cle]: valeur } }),
        });
        if (r.status === 409 && reste > 0) {
          setTimeout(() => _poster(cle, valeur, reste - 1), 700);
          return;                   // on garde la clé « en vol » : rien ne doit la doubler
        }
        if (!r.ok) {
          TOAST(T("echec", "Échec : HTTP {c}").replace("{c}", r.status));
          // On force la resynchronisation : l'écran doit montrer ce qui est VRAIMENT enregistré.
          const n = $("hw-tniv"); if (n) delete n.dataset.sig;
          return;
        }
        // Le serveur DIT s'il a redéployé : l'annoncer à tort ferait craindre une coupure de
        // flux à chaque case cochée, et l'annoncer jamais cacherait celle qui a vraiment lieu.
        let j = {};
        try { j = await r.json(); } catch (e) { /* réponse sans corps */ }
        // On note ce que l'orchestrateur vient d'accepter : c'est désormais la vérité, et
        // `/state` mettra un déploiement à la rattraper — ou ne la rattrapera jamais.
        _persiste[cle] = valeur;
        TOAST(j && j.redeploye === false
              ? T("applique", "Réglage appliqué")
              : T("redeploye", "Réglage appliqué — plugin redéployé"));
      } finally {
        _ecritureEnCours.delete(cle);
      }
    };

    const envoyerConfig = (cle, valeur) => {
      clearTimeout(_enAttente[cle]);
      _ecritureEnCours.add(cle);    // dès le PREMIER geste : l'affichage ne doit plus bouger
      _enAttente[cle] = setTimeout(() => {
        delete _enAttente[cle];
        _poster(cle, valeur, ESSAIS_409);
      }, ATTENTE_MS);
    };
    // ★ THE LIST COMES FROM THE CONTAINER, WHICH HAS IT FROM THE ORCHESTRATOR. The
    // container has no access to the Settings: `before_deploy` passes it the preset
    // names, and it republishes them in /state. The page therefore needs no extra
    // route, and it works identically behind a public token (read-only).
    $("hw-fmt").addEventListener("change", (e) => envoyerConfig("format", e.target.value));
    $("hw-tcol").addEventListener("change", (e) => envoyerConfig("tally_label_col", e.target.value));
    // ★ CONTRÔLE DU CATALOGUE (`MXLControls.chooseList`) : une liste déroulante pour ajouter,
    // et ce qui est choisi s'affiche dessous en puces. Un `<select multiple>` tient à quatre
    // niveaux ; à vingt il devient inutilisable — et un site en a autant qu'il a de chaînes de
    // destination. Le contrôle est monté à la première mise à jour d'état, quand on connaît la
    // liste (cf. `majEtat`).

    // The catalogue provides the "return to default" button and ALL the gestures.
    if (window.MXLControls) window.MXLControls.attachKnobGestures(EL, T("reset", "Valeurs par défaut"));
  }

  // ── LAYOUT EDITOR ─────────────────────────────────────────────────────────
  // ★ THE GEOMETRY IS NOT WRITTEN HERE. Align, equalise, distribute and snap live
  // in `window.MXLLayout` (static/js/layout_engine.js), shared with the product's
  // other editors. Four copies of the same truth table had already diverged —
  // three of them missed the same case. A plugin copying those functions would
  // make the fifth: we CALL, we do not rewrite.
  //
  // So this console keeps only what is really its own: the scene, the mouse
  // gesture, and the send to the container.
  const LAY_CLES = ["pip", "vu", "texte"];
  const LAY = { rects: [], sel: [], primaire: null, drag: null, guides: [], sig: "" };

  function layLabels() {
    return [T("lay_pip", "PiP"), T("lay_vu", "Vu-mètres"), T("lay_texte", "Cartouche")];
  }

  // The state is authoritative AS LONG AS NOBODY IS DRAGGING. Rewriting the
  // rectangles mid-drag would make the element jump under the finger on every poll.
  function poserDispo(d) {
    if (LAY.drag) return;
    const rects = LAY_CLES.map((k) => {
      const r = (d && d[k]) || {};
      return { x: +r.x || 0, y: +r.y || 0, w: +r.w || 0.1, h: +r.h || 0.1 };
    });
    const sig = JSON.stringify(rects);
    if (sig === LAY.sig) return;              // nothing new: no redraw
    LAY.sig = sig;
    LAY.rects = rects;
    dessinerLay();
  }

  function dessinerLay() {
    const sc = EL && EL.querySelector("#hw-lay-scene");
    if (!sc) return;
    const labs = layLabels();
    sc.innerHTML = LAY.rects.map((r, i) => {
      const cl = "hw-lay-box hw-lay-box--" + LAY_CLES[i]
        + (LAY.sel.includes(i) ? " sel" : "") + (i === LAY.primaire ? " prim" : "");
      return `<div class="${cl}" data-i="${i}" title="${esc(labs[i])}"
        style="left:${(r.x * 100).toFixed(2)}%;top:${(r.y * 100).toFixed(2)}%;
               width:${(r.w * 100).toFixed(2)}%;height:${(r.h * 100).toFixed(2)}%">
        <span class="hw-lay-nom">${esc(labs[i])}</span>
        <i class="hw-lay-poignee" aria-hidden="true"></i></div>`;
    }).join("") + LAY.guides.map((g) => g.axe === "v"
      ? `<i class="hw-lay-guide hw-lay-guide--v" style="left:${(g.pos * 100).toFixed(2)}%"></i>`
      : `<i class="hw-lay-guide hw-lay-guide--h" style="top:${(g.pos * 100).toFixed(2)}%"></i>`).join("");

    // ★ THE COST OF THE PLACEMENT, ANNOUNCED BEFORE IT IS PAID. A PiP that does not
    // touch the bottom edge needs input lines not yet received: it is then served
    // from the previous frame, one frame behind on the inset alone. We do not forbid
    // it — we SAY it, here and in /state.
    const z = EL.querySelector("#hw-lay-tranche");
    if (z) {
      const p = LAY.rects[0] || { y: 0, h: 0 };
      const ok = (p.y + p.h) >= 0.999;
      z.className = "hw-lay-tranche " + (ok ? "ok" : "att");
      z.textContent = ok
        ? T("lay_tr_oui", "PiP au bord bas : servi depuis la trame en cours.")
        : T("lay_tr_non", "PiP décollé du bas : servi depuis la trame précédente (une trame "
                          + "de retard sur la vignette seule ; la sortie reste en tranches).");
    }
  }

  async function envoyerDispo() {
    const d = {};
    LAY_CLES.forEach((k, i) => { d[k] = LAY.rects[i]; });
    LAY.sig = JSON.stringify(LAY.rects);
    await envoyer("/dispo", { dispo: d });
  }

  function monterEditeur() {
    const sc = EL.querySelector("#hw-lay-scene");
    const zo = EL.querySelector("#hw-lay-outils");
    if (!sc || !zo) return;
    poserDispo(null);

    if (window.MXLControls && !PUBLIC) {
      const I = window.MXLControls.ICONS || {};
      // ⚠ WE DRAW FROM THE INVENTORY, WE DO NOT INVENT. A missing icon must be
      // SEEN: `toolGroup` would otherwise place a bare button, clickable and blank.
      const ic = (nom) => I[nom] || "?";
      const appliquer = (out, faute) => {
        if (!out) { TOAST(faute); return; }
        LAY.rects = out.map(window.MXLLayout.borner);
        dessinerLay();
        envoyerDispo();
      };
      const sel2 = T("lay_sel2", "Sélectionnez au moins deux éléments : le dernier cliqué sert de référence.");
      const sel3 = T("lay_sel3", "Sélectionnez au moins trois éléments.");
      const al = (mode) => () => {
        if (!LAY.sel.length) { TOAST(T("lay_sel1", "Sélectionnez un élément.")); return; }
        // With only ONE selected, the reference is the FRAME: that is what lets you
        // centre an element without having a second one to hand.
        appliquer(window.MXLLayout.aligner(LAY.rects, LAY.sel, LAY.primaire, mode), sel2);
      };
      const eq = (mode) => () => appliquer(
        window.MXLLayout.egaliser(LAY.rects, LAY.sel, LAY.primaire, mode), sel2);
      const di = (axe) => () => appliquer(
        window.MXLLayout.distribuer(LAY.rects, LAY.sel, axe), sel3);
      zo.appendChild(window.MXLControls.toolGroup(T("lay_aligner", "Aligner"), [
        [ic("align_left"), T("al_l", "Bords gauches"), al("left")],
        [ic("align_hcenter"), T("al_hc", "Centres horizontaux"), al("hcenter")],
        [ic("align_right"), T("al_r", "Bords droits"), al("right")],
        [ic("align_top"), T("al_t", "Bords hauts"), al("top")],
        [ic("align_vcenter"), T("al_vc", "Centres verticaux"), al("vcenter")],
        [ic("align_bottom"), T("al_b", "Bords bas"), al("bottom")],
      ]));
      zo.appendChild(window.MXLControls.toolGroup(T("lay_taille", "Taille"), [
        [ic("size_w"), T("eq_w", "Même largeur que la référence"), eq("w")],
        [ic("size_h"), T("eq_h", "Même hauteur que la référence"), eq("h")],
        [ic("size_both"), T("eq_b", "Même taille que la référence"), eq("both")],
      ]));
      zo.appendChild(window.MXLControls.toolGroup(T("lay_repartir", "Répartir"), [
        [ic("distribute_h"), T("di_h", "Espacer horizontalement"), di("h")],
        [ic("distribute_v"), T("di_v", "Espacer verticalement"), di("v")],
      ]));
      zo.appendChild(window.MXLControls.toolGroup(T("lay_defaut", "Défaut"), [
        [ic("reset_box"), T("lay_reset", "Disposition par défaut"), () => envoyer("/dispo", {})],
      ]));
    }

    // ── The gesture. Everything else is in the engine. ──────────────────────
    sc.addEventListener("pointerdown", (e) => {
      const b = e.target.closest(".hw-lay-box");
      const i = b ? Number(b.dataset.i) : null;
      const s = window.MXLLayout.sélection(LAY.sel, LAY.primaire, i, e);
      LAY.sel = s.sel; LAY.primaire = s.primaire;
      if (i == null || PUBLIC) { dessinerLay(); return; }
      LAY.drag = {
        i, redim: !!e.target.closest(".hw-lay-poignee"),
        x0: e.clientX, y0: e.clientY, cadre: sc.getBoundingClientRect(),
        // We freeze the STARTING state: applying the delta to already-moved
        // rectangles would accumulate rounding error on every `pointermove`.
        dep: LAY.rects.map((r) => ({ ...r })),
      };
      sc.setPointerCapture(e.pointerId);
      dessinerLay();
      e.preventDefault();
    });

    sc.addEventListener("pointermove", (e) => {
      const d = LAY.drag;
      if (!d) return;
      const dx = (e.clientX - d.x0) / (d.cadre.width || 1);
      const dy = (e.clientY - d.y0) / (d.cadre.height || 1);
      const o = d.dep[d.i];
      if (d.redim) {
        LAY.rects[d.i] = window.MXLLayout.borner({ ...o, w: o.w + dx, h: o.h + dy });
        LAY.guides = [];
      } else {
        // ★ THE TOLERANCE IS OURS, NOT THE ENGINE'S. It reasons in normalised units
        // and deliberately ignores the canvas size; we alone know how many pixels
        // count as "close enough to stick".
        const tol = 8 / (d.cadre.width || 1);
        const a = window.MXLLayout.aimanter(d.dep, LAY.sel, o.x + dx, o.y + dy, o.w, o.h, tol);
        LAY.guides = a.guides;
        const ax = a.x - o.x, ay = a.y - o.y;
        // A multiple selection moves as one block: snapping applies to the element
        // GRABBED, the others follow by the same vector.
        LAY.sel.forEach((k) => {
          const s0 = d.dep[k];
          LAY.rects[k] = window.MXLLayout.borner({ ...s0, x: s0.x + ax, y: s0.y + ay });
        });
      }
      dessinerLay();
    });

    const fin = () => {
      if (!LAY.drag) return;
      LAY.drag = null; LAY.guides = [];
      dessinerLay();
      envoyerDispo();
    };
    sc.addEventListener("pointerup", fin);
    sc.addEventListener("pointercancel", fin);
  }

  // ── Display controls, all taken from the catalogue ────────────────────────
  // ★ THREE STATES, NOT TWO. An on/off LED could not tell "not wired" from "wired
  // but silent" — yet those are opposite faults: one is fixed at the patch, the
  // other at the producer. The hue comes from the STATUS vocabulary through
  // `--ctl-led-col`, never from a hard-coded colour.
  function led(etiquette, etat) {
    const col = etat === "ok" ? "var(--status-running-fg)"
              : etat === "muet" ? "var(--status-warning-fg)" : "var(--text-muted)";
    return `<span class="hw-led"><span class="ctl-led${etat === "ok" ? " on" : ""}"
      style="--ctl-led-col:${col}"></span><span>${esc(etiquette)}</span></span>`;
  }

  function majTemoins(s, ent) {
    // ⚠ THESE THREE VALUES ARE A PROTOCOL, not prose: the script emits them in
    // English whatever the interface language, and translates them on DISPLAY only.
    // Comparing against a translated label would break the console the moment the
    // language changes — with no error, just three dark LEDs.
    const etat = (v) => !v || v === "not wired" ? "off"
                      : (v === "no signal" || v === "waiting" ? "muet" : "ok");
    const z = EL.querySelector("#hw-temoins");
    if (!z) return;
    z.innerHTML =
      led(T("e_video", "Vidéo"), etat(ent.video)) +
      led(T("e_audio", "Audio"), etat(ent.audio)) +
      led(T("e_anc", "ANC"), etat(ent.anc));
    // The whole-frame fallback MUST be visible: it is the cost of the chosen place.
    const r = EL.querySelector("#hw-repli");
    if (r) r.textContent = s.slice_repli
      ? T("repli", "Image entière — {r}").replace("{r}", s.slice_repli) : "";
  }

  function majKnob(id, val, min, max, unite) {
    const k = EL && EL.querySelector("#" + id);
    if (!k || val == null) return;
    if (k.contains(document.activeElement)) return;   // being handled: do not overwrite
    const v = Number(val);
    if (String(k.dataset.val) === String(v)) return;  // nothing new: no redraw
    k.dataset.val = v;
    const v01 = (v - min) / (max - min || 1);
    const hit = k.querySelector(".ctl-knob-hit");
    if (hit && window.MXLControls) {
      hit.innerHTML = window.MXLControls.knobSvg("arc", v01, (Number(k.dataset.def) - min) / (max - min || 1));
      hit.setAttribute("aria-valuenow", String(v));
    }
    const out = k.querySelector(".ctl-knob-val");
    if (out) out.textContent = Math.round(v) + unite;
  }

  function rendreEtat(s) {
    const ent = s.entrees || {};
    const lignes = [
      [T("e_video", "Entrée vidéo"), ent.video || "—"],
      [T("e_audio", "Entrée audio"), ent.audio || "—"],
      [T("e_anc", "Entrée ANC"), ent.anc || "—"],
      [T("timecode", "Timecode"), s.timecode || "—"],
      [T("crete", "Crête audio"), s.audio_crete_dbfs != null ? s.audio_crete_dbfs + " dBFS" : "—"],
      [T("cadence", "Cadence"), (s.fps != null ? s.fps + " i/s" : "—")],
      [T("tranches", "Mode tranche"),
       s.slice_mode ? T("oui_tranche", "oui") : T("non_tranche", "non (image entière)")],
      [T("trames", "Trames émises"), s.frame_index != null ? s.frame_index : "—"],
    ];
    EL.querySelector("#hw-etat").innerHTML = lignes
      .map(([k, v]) => `<div class="hw-cell"><span>${esc(k)}</span><b>${esc(v)}</b></div>`)
      .join("");
    majTemoins(s, ent);

    const $ = (id) => EL.querySelector("#" + id);
    // We do NOT rewrite a field the user is editing: the poll would wipe their
    // typing from under their fingers.
    const t = $("hw-texte");
    if (t && document.activeElement !== t) t.value = s.texte || "";
    // A catalogue knob refreshes through its ATTRIBUTES (data-val) and its
    // drawing, not through a `.value` property: it is a span, not an input. We do
    // not touch the one being manipulated.
    majKnob("hw-omega", s.coefficient_omega, 0, 20, "");
    const fm = $("hw-fmt");
    if (fm && document.activeElement !== fm) {
      const dispo = s.formats_dispo || [];
      const sig = JSON.stringify(dispo);
      if (fm.dataset.sig !== sig) {          // only re-render when the list changed
        fm.dataset.sig = sig;
        fm.innerHTML = [["", T("fmt_defaut", "— défaut du site —")]]
          .concat(dispo.map((n) => [n, n]))
          .map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
      }
      fm.value = s.format || "";
    }
    const tc = $("hw-tcol");
    const _colVraie = ("tally_label_col" in _persiste) ? _persiste.tally_label_col
                                                       : s.tally_label_col;
    if (tc && document.activeElement !== tc && _colVraie != null) tc.value = String(_colVraie);
    // On préfère la valeur PERSISTÉE quand on l'a : c'est la source de vérité de ce réglage.
    const _niveauxVrais = ("tally_level" in _persiste) ? _persiste.tally_level : s.tally_level;
    const tn = $("hw-tniv");
    // ⚠ NE PAS REDESSINER TANT QU'UNE ÉCRITURE N'EST PAS PARTIE ET REVENUE. `/state` répond
    // encore l'ANCIENNE valeur pendant le redéploiement : reconstruire le contrôle dessus
    // ferait réapparaître ce qu'on vient de retirer, puis disparaître à nouveau.
    if (tn && !tn.contains(document.activeElement)
        && !_ecritureEnCours.has("tally_level")) {
      const dispo = (s.tally_levels_dispo || []).map((n) => ({value: n.uuid, label: n.label}));
      const sig = JSON.stringify([dispo, _niveauxVrais || []]);
      if (tn.dataset.sig !== sig) {          // on ne redessine que si quelque chose a bougé
        tn.dataset.sig = sig;
        window.MXLControls.chooseList(tn, {
          options: dispo,
          valeurs: _niveauxVrais || [],
          vide: T("t_niv_vide", "— ceux de la production —"),
          ajouter: T("t_niv_ajout", "+ Ajouter un niveau…"),
          tout: T("t_niv_tout", "tous les niveaux sont choisis"),
          retirer: T("t_niv_retirer", "Retirer"),
          onChange: (v) => envoyerConfig("tally_level", v),
        });
      }
    }
    if (s.dispo) poserDispo(s.dispo);
    // ★ THE GAUGE IS THE HINT. It fills from 0 to 10 — the team is ten people —
    // and the threshold mark sits at 100 %. Nowhere do we say what 10 triggers: a
    // gauge that fills makes you want to fill it, and that is all an easter egg
    // has to do. Beyond that it goes "over": the target is missed.
    const og = $("hw-omega-g");
    if (og) {
      const v = Number(s.coefficient_omega || 0);
      const p = Math.max(0, Math.min(1, v / 10));
      og.querySelector(".ctl-gauge-fill").style.transform = "scaleX(" + p.toFixed(3) + ")";
      og.classList.toggle("over", v > 10);
      og.classList.toggle("warn", v > 7 && v < 10);
    }
    const f = $("hw-fond");
    if (f && document.activeElement !== f && s.fond) f.value = s.fond;
    const ovc = $("hw-ov");
    if (ovc && document.activeElement !== ovc) ovc.checked = !!s.overlay_on;
    const pipc = $("hw-pip");
    if (pipc && document.activeElement !== pipc) pipc.checked = !!s.pip_on;
  }

  async function rafraichir() {
    try { rendreEtat(await lireEtat()); }
    catch (err) {
      const z = EL && EL.querySelector("#hw-etat");
      if (z) z.innerHTML = `<span class="hw-vide">${esc(T("injoignable", "Injoignable : {e}").replace("{e}", err.message))}</span>`;
    }
  }

  // Lit les réglages PERSISTÉS une fois au montage. Sans ça, le premier rendu part de la photo
  // du conteneur, et un réglage changé à chaud depuis une autre session s'afficherait périmé.
  async function chargerPersistes() {
    const url = apiConteneur("/plugin_config");
    if (!url) return;                     // mode public : pas d'orchestrateur à joindre
    try {
      const r = await fetch(url);
      if (!r.ok) return;
      Object.assign(_persiste, (await r.json()).params || {});
    } catch (e) { /* l'affichage retombe sur /state, moins frais mais lisible */ }
  }

  function mount(el, vmid, ctx) {
    EL = el; VMID = vmid;
    TOAST = (ctx && ctx.toast) || (() => {});
    BASE = (ctx && ctx.base) || null;
    PUBLIC = !!BASE;
    gabarit();
    // ⚠ LA VÉRITÉ D'ABORD, LE PREMIER RENDU ENSUITE. Sans cet ordre, le premier affichage part
    // de la photo du conteneur : un réglage changé à chaud depuis une autre session s'y montre
    // périmé, et le geste suivant l'écrit à nouveau tel quel.
    chargerPersistes().finally(() => rafraichir());
    timer = setInterval(rafraichir, 2000);
  }

  function unmount() {
    // ★ WITHOUT THIS, THE POLL OUTLIVES THE PAGE. You switch tab, the console is
    // unmounted, and the interval keeps interrogating a container for a display
    // that no longer exists — invisible, and cumulative on every mount.
    if (timer) { clearInterval(timer); timer = null; }
    EL = null; VMID = null; BASE = null; PUBLIC = false;
  }

  window.MXLPlugins = window.MXLPlugins || {};
  window.MXLPlugins.hello_world = { mount, unmount };
})();

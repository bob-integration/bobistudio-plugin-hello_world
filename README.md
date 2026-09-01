# Hello World — the reference example for a Bobi.Studio plugin

*[Version française](README.fr.md)*

This plugin **has no production use**. It composites "Hello World", a logo and system
information onto the picture. Its reason to exist is elsewhere: it is the **executable
reference** for the plugin contract — the one you read before writing your own, and the one
continuous integration checks so that the documentation cannot quietly go stale.

It is part of [Bobi.Studio](https://github.com/bob-integration/bobistudio), a broadcast
orchestrator built on the ST 2110 / MXL bus.

---

## What it is actually for

**Checking a fresh installation.** Deploy it with nothing wired: it generates its own
background and shows the container name, its version, the output flows, the format, the cadence
and the uptime. If the picture reaches the monitoring panel, the whole chain works —
orchestrator, agent, MXL bus, metrics. That matters most on installation day, which is exactly
when no chain is built yet.

**Learning the contract.** `script.py` is commented to be read. Every rule carries the *why*
and, more importantly, **what breaks silently** when it is left out — because in this product
almost nothing fails loudly. A stage that emits nothing still runs, still answers on both its
ports, and still reports a perfect frame rate.

---

## What it demonstrates

| Contract point | Where to look |
|---|---|
| `str.format` template, doubled braces | script header |
| Native slice mode, progressive commit | `slice_height_pour()` and the main loop |
| **Line-local** processing, absolute offset | `incruster()` — the number one slice-mode trap |
| Signature cache, and how to know it works | `overlay_pour()`, metric `overlay_rendus_par_s` |
| Three essences in and out | video, audio and ANC readers/writers, `wire_followers` hook |
| ANC written as RFC 8331 | a house format decodes to "zero packets", silently |
| Exposure to macros | `param_tree`, `actions`, live option lists |
| State readable as an automation condition | `/state`, declared in `control.read_endpoints` |
| Observability metrics | `slice_mode`, `own_latency_ms`, `slices_incompletes`, … |
| Recovery from SIGBUS and a re-created flow | `_sigbus` and the recovery loop |
| Public read-only page | `ui.public_page`, the console honours `ctx.base` |

It reads video, audio and ANC, and re-emits all three — the wiring case where mistakes cost the
most (silent audio, lost ANC, one input mistaken for another).

---

## Installing it

**From Bobi.Studio** — Settings → Plugins → *Import*, with a `.mxlplugin` package, or the
**Catalogue** page, which lists published packages and installs them for you.

**By hand** — clone this repository into `plugins/hello_world/` of a Bobi.Studio instance and
reload the plugin registry (Settings → Plugins → *Reload*).

> Adding or changing `hooks.py` **requires a registry reload**: the orchestrator imports it
> once at scan time. A hook that never fires is a perfectly silent failure — this plugin
> publishes `tally_age_s` precisely so that its own absence becomes visible.

---

## Reading it

Start at the top of `script.py`: the header lists the seven contract points and the traps.
Then follow the main loop — it is the shape every plugin has.

- `script.py` — the whole plugin, a `str.format` template rendered by the orchestrator and run
  inside the container. **Every literal brace must be doubled `{{ }}`**, comments included.
- `hooks.py` — the lifecycle hooks. This file runs **in the orchestrator**, and is the one
  documented exception to "no plugin code in the controller".
- `control.js` / `control.css` / `control.html` — the console. Controls come from the shared
  catalogue (`window.MXLControls`), the layout editor from the shared engine
  (`window.MXLLayout`); neither is reimplemented here.
- `plugin.json` — the manifest: wiring, config schema, macro surface, control endpoints.
- `help.md` / `help.fr.md` — the article the product's Help page builds from this plugin.

---

## Measured behaviour

On 1080p50, one node, with all three inputs wired:

| | |
|---|---|
| Cadence | 50.0 fps |
| Compute per frame | 18.8 ms, on a 20 ms budget |
| Truncated frames | 0 |
| Panel renders | 8 /s (capped — the cache key would otherwise change every frame) |

Those numbers are not decoration. The plugin publishes them so that a placement choice — moving
the PiP off the bottom edge, widening the info panel — shows its cost instead of hiding it.

---

## The guard rail

`tests/verif_plugin_hello_world.py` — which lives in the
[Bobi.Studio repository](https://github.com/bob-integration/bobistudio), not here — runs 30
checks against this plugin in continuous integration: the template renders *and compiles*, slice
mode is on, macros are reachable, metrics are declared *and* updated, the three essences are
wired both ways, SIGBUS is caught, the public-page contract is honoured.

If the contract evolves and this example does not follow, **CI fails**. That is what stops it
becoming documentation nobody executes — `plugins/AUTHORING.md` once spent three months
describing a contract that had changed underneath it.

---

## Licence

GPL-3.0-or-later — see [LICENSE](LICENSE). Copyright © 2026 BOBI SAS, France.

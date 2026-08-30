# Hello World — the reference example

This plugin **has no production use**. It composites "Hello World", a logo and system
information onto the picture. Its reason to exist is elsewhere: it is the **executable
reference** for the plugin contract, the one you read before writing your own.

## What it is actually for

**Checking a fresh installation.** Deploy it with nothing wired: it generates its own
background and shows the container name, its version, the output flows, the format, the cadence
and the uptime. If the picture appears in the monitoring panel, the whole chain works —
orchestrator, agent, MXL bus, metrics.

**Learning the contract.** Its `script.py` is commented to be read: every rule comes with the
*why*, and with what breaks **silently** when it is ignored.

## What it demonstrates

| Contract point | Where to see it |
|---|---|
| `str.format` template, doubled braces | script header |
| Native slice mode and progressive commit | `slice_height_pour()` and the main loop |
| **Line-local** processing and absolute offset | `incruster()` — the number one slice-mode trap |
| Signature cache | `overlay_pour()` — leading cause of cadence deficit when missing |
| Three essences in and out | video, audio and ANC readers/writers, `wire_followers` hook |
| ANC written as RFC 8331 | `anc_pack_rfc8331` — a house format decodes to "zero packets", silently |
| Exposure to macros | manifest `param_tree` and `actions`, `/params` and `/dispo` endpoints |
| State readable as a condition | `/state`, declared in `control.read_endpoints` |
| Observability metrics | `slice_mode`, `own_latency_ms`, `source`, `slices_incompletes` — not just `fps` |
| Recovery from SIGBUS and a re-created flow | `_sigbus` handler and the recovery loop |
| Public page | `ui.public_page`, the console honours `ctx.base` |

## Settings

| Setting | Effect |
|---|---|
| Overlay text | The line shown in large type. Accents are transliterated — the built-in font has no glyphs for them. |
| Layout | PiP, level meters and info panel are placed and sized in the editor on the plugin page. Normalised rectangles, so a layout survives a format change. The `dispo_defaut` action restores the default. |
| Background colour | Live list served by `/couleurs`, which also feeds the macro editor. |
| Overlay / PiP | On-off actions, triggerable by macro. |
| Output format | Chosen from the site's named formats, **only** when no video input is wired. With a source, the format comes from the flow. Changing it REDEPLOYS the plugin. |
| Tally label column / level | Read by the orchestrator, not by the container: they also take effect on redeployment. |

## The PiP and slice mode

A PiP touching the **bottom edge** is served from the current frame. Anywhere else it needs
input lines that have not arrived yet — so it is served from the **previous** frame instead, and
the output stays sliced. The cost then falls on the inset alone (one frame behind, counted by
`pip_retard_trames`) rather than on the whole signal. The editor says which of the two applies,
before you pay for it.

## The guard rail

`tools/verif_plugin_hello_world.py` checks in continuous integration that this example still
honours the points above. If the contract evolves and the example does not follow, **CI fails** —
which is what stops it becoming stale documentation nobody executes any more.

## This page is produced by the plugin itself

The `help.md` file at the plugin root **is** this article. `/api/plugins/help` aggregates the
`help.md` of every installed plugin, renders them to HTML, and the Help page builds a
`plugin-<type>` article from each. There is nothing to declare and nothing to copy elsewhere.

A plugin may place a `help.<code>.md` alongside it (`help.fr.md`, `help.en.md`): the current
language's file is served, falling back to `help.md`. When the fallback applies, the article SAYS
so — otherwise help in another language reads as a translation fault in the product.

Two details that cost you if ignored:

- the leading `# …` title is **stripped** at render time — the article already carries the
  plugin's label, and keeping it would produce two level-1 headings;
- placement comes from the manifest's `help.category` and `help.order`, falling back to the
  `nav` section. Without `help`, an example plugin lands in the middle of the processing tools,
  where operators are looking for production gear.

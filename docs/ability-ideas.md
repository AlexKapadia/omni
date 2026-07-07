# Good first abilities

A menu of new things Naomi and the approval system could learn to do. Every one
of these is a real, well-scoped [agent tool](../CONTRIBUTING.md#-add-a-new-ability-agent-tool)
— pick one, follow the tutorial, and ship it. They're sorted roughly easiest
first.

Each idea is tagged with:

- **Difficulty** — 🟢 first-timer · 🟡 a weekend · 🔴 needs design first
- **Egress** — does data leave the machine? (local abilities are the easiest and
  safest)
- **Watch** — the one invariant to keep front of mind while building it

> Want to claim one? Open a [New ability issue](../.github/ISSUE_TEMPLATE/new_ability.yml)
> so we can tag it `good first issue` and nobody doubles up. Have an idea that
> isn't here? Even better — propose it.

---

## Fully local — no data leaves the machine

These write to the vault or compute an answer on-device. They work offline and
with the kill-switch on, and they're the gentlest introduction to the extension
point. The `create_reminder` tutorial in CONTRIBUTING.md is one of these.

| Ability | Example utterance | Difficulty | Watch |
| --- | --- | --- | --- |
| **Create reminder** | "Remind me to call the dentist tomorrow" | 🟢 | This is the worked example in the tutorial — start here. Local-only; `data_sent_off_machine=""`. |
| **Add to a list** | "Add milk to my shopping list" | 🟢 | Append-only to a vault note; never overwrite user content (use the collision-safe writer). |
| **Unit / measurement convert** | "Convert 12 miles to kilometres" | 🟢 | Pure deterministic math — no egress, exact to the unit. A live answer, not an action. |
| **Currency convert (cached rates)** | "How much is 40 euros in pounds?" | 🟡 | If rates come from the network it becomes an egress tool — cache them and be honest about the source. |
| **Define a word (local dictionary)** | "What does 'usufruct' mean?" | 🟡 | Ship the dictionary as an on-device asset to stay local; if you call an API, it's an egress tool. |
| **Start a timer / stopwatch** | "Naomi, set a timer for ten minutes" | 🔴 | Firing the timer needs a scheduler + notification surface the engine doesn't have yet — propose the design first. The *capture + approval* half is easy; the *fire* half is the real work. |
| **Quick note to a specific folder** | "Jot this in my Ideas folder" | 🟢 | Very close to the existing `write_note` tool — a good way to learn the vault writers. |

## Reads from the internet — an egress tool

These call an external service to answer, but never act on the user's behalf.
Route the call through a small gateway that respects the kill-switch, and set
`data_sent_off_machine` to exactly what the query sent. See the "talks to the
internet" section of the tutorial.

| Ability | Example utterance | Difficulty | Watch |
| --- | --- | --- | --- |
| **Weather** | "What's the weather in Lisbon this weekend?" | 🟡 | Needs an API + key wired through DPAPI. Send only the location, nothing from the vault. |
| **Web search** | "Search the web for the Parakeet-TDT paper" | 🟡 | Treat results as untrusted input (prompt-injection). Send the minimum query; don't leak context. |
| **Package tracking** | "Where's my parcel, tracking 1Z…?" | 🟡 | The tracking number is the only thing that should leave. State it plainly in the audit line. |
| **Stock / crypto price** | "What's TSLA trading at?" | 🟡 | Read-only. Cache sensibly; be honest that a request went out. |
| **Look up a contact's public info** | "Find the office address for Acme Corp" | 🔴 | Careful scoping — never send the user's own contacts or notes to the lookup. |

## Acts on an external service — approval-carded, draft-only where it sends

These change something outside Omni, so they **must** be approval-carded, and
anything that posts or messages as the user must be **draft-only or staged for
the user to confirm** — the Gmail draft tool is the precedent. These are the most
powerful and the ones to design carefully.

| Ability | Example utterance | Difficulty | Watch |
| --- | --- | --- | --- |
| **Spotify — play / queue** | "Play my focus playlist" | 🟡 | Approval-carded. It controls the user's own player, so no draft needed — but no auto-run either. |
| **Philips Hue / smart-home** | "Dim the office lights" | 🟡 | Approval-carded; scoped to devices the user paired. Fail closed if the bridge is unreachable. |
| **Notion — add a page** | "Add this to my Notion reading list" | 🔴 | Writes to an external doc store → approval-carded. Send only the page content, never the vault. |
| **Slack — post a message** | "Post this to #standup" | 🔴 | Outbound-to-people → **draft/stage it** for the user to send, mirroring Gmail. Never auto-post. |
| **Create a task in a tracker** | "Make a Linear ticket for this bug" | 🔴 | Approval-carded; minimal payload; honest `data_sent_off_machine`. |
| **SMS / text (via a provider)** | "Text Priya I'm running late" | 🔴 | This sends as the user → **draft-only / staged**, never dispatched. The strictest bar. |

---

## Before you start

Whichever you pick, three things make a tool land smoothly:

1. **Read the closest existing tool.** For a local one, `vault_write_note_tool.py`.
   For an egress one, `calendar_create_event_tool.py`. For draft-only, `gmail_create_draft_tool.py`.
2. **Keep it inside the promise.** Local-first, zero telemetry, approval-before-execute,
   draft-only for anything outbound. If your idea strains one of those, open an
   issue and let's find the shape together — that conversation is welcome, not a hurdle.
3. **Write tests with teeth.** Boundary-exact `dry_run` previews, a local-only
   `data_sent_off_machine` assertion, and a round-trip through approval. See the
   tutorial's [test step](../CONTRIBUTING.md#step-10--tests-with-teeth-and-the-count-guards).

Happy building.

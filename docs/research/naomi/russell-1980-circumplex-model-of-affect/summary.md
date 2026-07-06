# A Circumplex Model of Affect — James A. Russell (1980)

**Citation:** Russell, James A. "A circumplex model of affect." *Journal of Personality and
Social Psychology*, 39(6), 1161-1178. American Psychological Association, 1980.
DOI: 10.1037/h0077714.
**Links:** https://psycnet.apa.org/doi/10.1037/h0077714 · overview: Posner, Russell &
Peterson, "The circumplex model of affect: An integrative approach to affective
neuroscience, cognitive development, and psychopathology," *Development and
Psychopathology* 17(3), 2005 — https://pmc.ncbi.nlm.nih.gov/articles/PMC2367156/
**Surveyed:** 2026-07-06.

## The model

Russell derived the model empirically by having subjects classify and scale 28 emotion
words; the words arrange in a circle in a two-dimensional space whose axes are:

- **Valence** — a pleasure-displeasure continuum (horizontal).
- **Arousal** — activation/alertness (vertical).

All affective states arise as combinations of these two continuous dimensions (per the
2005 Posner/Russell/Peterson integrative review, they reflect two underlying
neurophysiological systems). Canonical placements: *content/calm* = positive valence, low
arousal; *happy/excited* = positive valence, high arousal; *tense/angry (agitated)* =
negative valence, high arousal; *sad/depressed* = negative valence, low arousal.

## Why this model (and not discrete emotion labels) for Naomi

1. **Continuous → interpolatable.** Physical simulation parameters (speed, frequency,
   amplitude) need a continuous input space; (valence, arousal) ∈ [−1,1]² blends states
   smoothly where 6 discrete labels would snap.
2. **Two numbers fit through every pipe:** trivially carried in an LLM response tag, a WS
   message, a shader uniform vec2, and mapped onto Cartesia's discrete
   `generation_config.emotion` enum (`neutral, calm, angry, content, sad`) by
   nearest-region lookup.
3. **Established, citable, and widely used** in affective computing for exactly this
   audio/visual parameter-mapping role (e.g. controllable speech synthesis literature uses
   arousal/valence conditioning — see arXiv:1910.01709 for a TTS example).

Laughter is not a point in the circumplex — it is an *event/burst* signal (high-arousal,
positive-valence region plus a rhythmic time signature). Model it as a third channel:
`burst ∈ {none, laugh}` with an intensity, layered on the (v, a) state.

# Omni landing site

The public marketing landing page for Omni. Static, self-contained, and
monochrome — it reuses the app's exact design language (palette, type, spacing,
motion) from `apps/ui/src/styles/tokens.css` and `docs/design/design-brief.md`.

## What's here

```
site/
  index.html            # the whole page (one document, semantic + accessible)
  assets/
    fonts.css           # @font-face — self-hosted, no external CDN
    tokens.css          # design tokens copied verbatim from the app
    base.css            # reset, header, hero, buttons, footer
    sections.css        # feature rows, scroll-reveal motion, dark band, CTA
    scroll.js           # scroll-driven fade-in/out reveals (progressive enhancement)
    fonts/*.woff2        # Space Grotesk 600, Inter 400/500/600, JetBrains Mono 400/500 (OFL)
    shots/*.webp|*.png   # web-optimized product screenshots (originals stay in /media)
    omni-demo.mp4        # the real recorded product demo (hero video)
```

## Design notes

- **Strictly monochrome.** White canvas, ink `#0A0A0A`, greys only. The one
  "accent" is motion — the breathing capture dot — never colour.
- **Real product media.** Every screenshot and the demo video are the real app
  running end-to-end (see `../media/README.md`). Nothing is a mock-up.
- **Scroll-driven storytelling.** Product figures fade and lift in as they enter
  the viewport and soften as they leave, so you watch the product being used as
  you scroll. Copy is enter-only so text never fades while you read.
- **Accessible + fast.** `prefers-reduced-motion` shows everything statically
  with no motion; images are lazy-loaded below the fold with reserved dimensions
  (no layout shift); fonts are self-hosted (works offline, leaks nothing).

## Local preview

No build step. Serve the folder and open it:

```bash
cd site
python -m http.server 8080
# open http://localhost:8080
```

## Deployment — GitHub Pages

Publishing is automated by `.github/workflows/pages.yml`: every push to `main`
that touches `site/` uploads this folder and deploys it.

### One-time enablement (repo admin, once)

1. Go to the repository **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **GitHub Actions**.

That's it. The next push to `main` publishes the site at
`https://alexkapadia.github.io/omni/`. (No `docs/` source and no `gh-pages`
branch is used — the Action deploys `site/` directly.)

---
name: Vaakora
company: Vaakora, Hyderabad
description: AI phone agents that call leads in natural Indian English, answer questions, and return a transcript and lead score for every call.
surfaces: [paper, obsidian]
---

# Vaakora Design Tokens (DESIGN.md)

Source of truth for colour, type, space, and component rules. The full rationale, page specs, and flows live in the Vaakora Design & Product Manual.

## 1. Surfaces

| Surface | Used for |
| :--- | :--- |
| `paper` | Marketing site, docs, legal pages, auth screens |
| `obsidian` | App console, live call monitor, call detail |

## 2. Colour

### Paper
| Token | Hex | Notes |
| :--- | :--- | :--- |
| `paper` | `#F5F3EE` | Page background |
| `paper-raised` | `#FFFFFF` | Cards, inputs |
| `ink` | `#15171C` | Headings and body (16:1) |
| `ink-2` | `#4A4F5A` | Secondary text (7.4:1) |
| `ink-3` | `#646979` | Captions (4.9:1) |
| `rule` | `#E2DED5` | Borders and dividers |
| `accent` | `#3355FF` | Primary actions and links (4.9:1 on paper; 5.4:1 with white text) |
| `accent-hover` | `#2443E0` | |

### Obsidian
| Token | Hex | Notes |
| :--- | :--- | :--- |
| `canvas` | `#07090D` | App background |
| `surface` | `#0E131C` | Panels |
| `raised` | `#151B27` | Menus, modals |
| `subtle` | `#1C2433` | Inputs, hovered rows |
| `rule` | `rgba(255,255,255,0.08)` | Borders |
| `rule-strong` | `rgba(255,255,255,0.16)` | Focused / hovered borders |
| `text` | `#F2F4F7` | Primary (17:1) |
| `text-2` | `#A3ACBD` | Secondary (8.1:1) |
| `text-3` | `#7A8497` | Metadata (4.9:1) |
| `accent` | `#3355FF` | Button fills |
| `accent-text` | `#7D93FF` | Links and accent text on dark (6.6:1) |

### Call-state semantics (console only, always paired with a text label)
| Token | Hex | Meaning |
| :--- | :--- | :--- |
| `live` | `#3CCB7F` | Call in progress, engine healthy |
| `warn` | `#F2B53A` | Warm lead, provider failover, wallet low |
| `fail` | `#F26B5E` | Dropped, unqualified, DND blocked |
| `info` | `accent` | Neutral notice |

Never more than one semantic colour per card.

## 3. Typography

- Sans: `Anek Latin` (add `Anek Devanagari`, `Anek Telugu` when those languages ship). Chosen because one family covers Latin and the major Indic scripts with matched proportions.
- Mono: `JetBrains Mono` with `tabular-nums`, for latency, phone numbers, IDs, and money in tables.

| Role | Size / LH | Weight | Width |
| :--- | :--- | :--- | :--- |
| Display | 56 / 60 (mobile 38 / 42) | 600 | SemiExpanded |
| H1 | 40 / 46 (mobile 30 / 36) | 600 | SemiExpanded |
| H2 | 30 / 36 | 600 | Normal |
| H3 | 22 / 28 | 600 | Normal |
| Body L | 18 / 28 | 400 | Normal |
| Body | 16 / 26 | 400 | Normal |
| Console body | 14 / 20 | 400–500 | Normal |
| Table cell | 13 / 18 | 400 | Normal |
| Caption | 12 / 16 | 500 | Normal |
| Mono metric | 13 / 16 | 600 | — |

## 4. Space, radius, depth, motion

- Spacing scale (px): 4, 8, 12, 16, 24, 32, 48, 64, 96. 8 inside a group, 24 between groups, 64–96 between marketing sections.
- Radius: 6 (inputs, buttons), 10 (cards), 14 (modals), full (avatars, status dots only).
- Depth: 1px rule plus tonal step. One shadow, menus and modals only: paper `0 8px 24px rgba(0,0,0,0.12)`, obsidian `0 8px 24px rgba(0,0,0,0.5)`.
- Motion: 150ms ease-out (hover/press), 220ms (panels/modals). Only the live-call waveform animates continuously. Honour `prefers-reduced-motion`.
- Icons: Lucide, 1.5px stroke, 20px. No emoji in UI.

## 5. Signature component: Call Strip

Two speaker lanes (agent, lead) on a time axis, turn bubbles with transcript text, mono latency chips (STT / LLM / TTS), and an outcome tag (tier + score). Variants: hero (marketing playback), static (product pages), interactive (call detail, click a line to seek audio).

## 6. Rules

1. No gradient text, no purple/indigo gradients, no glassmorphism, no glow shadows.
2. Every number shown publicly comes from a log, invoice, or a customer who agreed to be quoted. Latency figures are measured medians from production, labelled as such.
3. One accent colour per surface. Status colours appear only for call states.
4. Status is never colour alone; always a text label.
5. Buttons are verb + object ("Talk to Archie", "Add credits").
6. Rupees, Indian digit grouping (1,00,000), IST timestamps.

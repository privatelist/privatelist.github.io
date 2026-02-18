# PLC Design System

**All Private List Consulting products must follow this design standard.**

## Core Principle

**Light, clean, professional.** Match the main website (privatelistconsulting.com).

---

## Colors

### Primary Palette

| Name | Hex | Usage |
|------|-----|-------|
| **Navy** | `#1E3A5F` | Headers, primary text, branding |
| **Copper** | `#C47D3A` | CTAs, accents, highlights |
| **Sage** | `#5A7E7E` | Secondary text, status indicators |

### Backgrounds & Neutrals

| Name | Hex | Usage |
|------|-----|-------|
| **White** | `#FFFFFF` | Primary background, cards |
| **Light Gray** | `#F7F8F8` | Page background, sections |
| **Border Gray** | `#E8EAEA` | Card borders, dividers |
| **Dark Gray** | `#2C2C2C` | Body text |

### Status Colors

| Status | Color | Hex |
|--------|-------|-----|
| Success/OK | Sage | `#5A7E7E` |
| Warning | Copper | `#C47D3A` |
| Error | Dark Copper | `#B36E2E` |

---

## Typography

**Font:** Inter (Google Fonts)

```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
```

| Element | Weight | Size |
|---------|--------|------|
| H1 | 700 | 2-2.5em |
| H2 | 700 | 1.5-1.8em |
| H3 | 600 | 1.2-1.4em |
| Body | 400 | 1em (16px) |
| Labels | 400 | 0.9em |

---

## Components

### Cards

```css
.card {
    background: #FFFFFF;
    border-radius: 12px;
    padding: 24px;
    border: 1px solid #E8EAEA;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.card:hover {
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}
```

### Buttons

**Primary (CTA):**
```css
.btn-primary {
    background: #C47D3A;
    color: #FFFFFF;
    padding: 12px 32px;
    border-radius: 4px;
    font-weight: 600;
}

.btn-primary:hover {
    background: #B36E2E;
}
```

**Secondary:**
```css
.btn-secondary {
    background: transparent;
    color: #5A7E7E;
    border: 2px solid #5A7E7E;
    padding: 12px 32px;
    border-radius: 4px;
}

.btn-secondary:hover {
    background: #5A7E7E;
    color: #FFFFFF;
}
```

### Page Layout

```css
body {
    font-family: 'Inter', sans-serif;
    background: #F7F8F8;
    color: #2C2C2C;
}

.header {
    background: #FFFFFF;
    border-bottom: 1px solid #E8EAEA;
}

h1, h2, h3 {
    color: #1E3A5F;
}
```

---

## Do's and Don'ts

### ✅ Do

- Use white/light gray backgrounds
- Use Navy for headers
- Use Copper for CTAs and highlights
- Keep designs clean and minimal
- Use consistent spacing (multiples of 8px)
- Add subtle shadows for depth

### ❌ Don't

- Use dark backgrounds for main content
- Use bright/neon colors
- Overcrowd with too many elements
- Use multiple fonts
- Add unnecessary decorations

---

## Reference

Main website: https://privatelistconsulting.com

All dashboards, tools, and client-facing products must match this aesthetic.

---

*Last updated: 2026-02-18*
*Enforced by: jFISH 🐟*

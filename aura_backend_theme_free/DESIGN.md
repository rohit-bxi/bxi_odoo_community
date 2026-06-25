# Design System Specification: Editorial Precision

 

This document outlines a high-end, editorial approach to digital interface design. It moves away from the generic "app" aesthetic toward a sophisticated, layered experience that prioritizes intentional whitespace, tonal depth, and high-contrast typography.

 

## 1. Overview & Creative North Star

**The Creative North Star: "The Digital Architect"**

This design system is built on the principles of architectural clarity and editorial structure. It celebrates the tension between immersive, high-chroma immersive zones (like the deep blue hero areas) and stark, clinical white workspaces. 

 

Instead of a flat, grid-based approach, we utilize **intentional asymmetry**. Layouts should feel like a premium printed journal—bold headlines that command attention, generous margins that allow content to breathe, and a total absence of clutter. We replace traditional structural lines with tonal shifts to create a sense of infinite, seamless space.

 

---

 

## 2. Colors & Surface Tonalities

 

The palette is anchored by deep, authoritative blues and a spectrum of surgical grays. 

 

### Core Palette

*   **Primary (Action/Header):** `#555b70` (Muted Indigo-Grey)

*   **Secondary (High-Emphasis Action):** `#242424` (Electric Cobalt)

*   **Tertiary (Accent/Alert):** `#0846ed`

*   **Surface (Base Background):** `#f6f6f6`

*   **Surface Container Lowest (Pure White):** `#ffffff`

 

### The "No-Line" Rule

To achieve a premium editorial feel, **prohibit the use of 1px solid borders** for sectioning content. Boundaries must be defined through:

1.  **Background Color Shifts:** A `surface-container-low` card sitting on a `surface` background.

2.  **Negative Space:** Using the spacing scale to separate logical groups.

3.  **Soft Transitions:** Utilizing the deep gradient palette (Primary to Tertiary) for immersive sections.

 

### The Glass & Gradient Rule

For hero sections or immersive login panels, use a radial gradient from `secondary` (`#242424`) to `on_tertiary_container` (`#002388`). For floating elements over these gradients, use **Glassmorphism**:

*   **Fill:** `surface_container_lowest` at 10%–15% opacity.

*   **Backdrop Blur:** 20px–40px.

*   **Border:** Use a "Ghost Border" (see Section 4).

 

---

 

## 3. Typography: The Editorial Voice

 

We use **Inter** exclusively to bridge the gap between technical precision and human readability.

 

| Token | Size | Weight | Tracking | Usage |

| :--- | :--- | :--- | :--- | :--- |

| **Display-LG** | 3.5rem | 700 (Bold) | -0.02em | High-impact hero statements. |

| **Headline-LG**| 2.0rem | 600 (Semi) | -0.01em | Primary section headers. |

| **Title-MD**   | 1.125rem | 500 (Medium)| 0 | Sub-headers and form labels. |

| **Body-LG**    | 1.0rem | 400 (Reg) | 0 | Long-form reading and inputs. |

| **Label-SM**   | 0.6875rem| 600 (Semi) | 0.05em | Overline text and metadata. |

 

**Hierarchy Note:** Always pair a `Display-LG` header with a `Body-LG` sub-text. The contrast in scale is what creates the "Editorial" look. Ensure line height is generous (1.5x for body, 1.2x for headlines).

 

---

 

## 4. Elevation & Depth: Tonal Layering

 

Traditional drop shadows are largely discarded in favor of **Tonal Layering**.

 

*   **The Layering Principle:** Stacking `surface-container` tiers creates depth. A login form (Pure White: `#ffffff`) placed against a workspace background (`#f6f6f6`) creates a natural, soft lift.

*   **Ambient Shadows:** When a floating effect is required (e.g., a modal), use a shadow color tinted with the primary brand color:

    *   `rgba(24, 55, 254, 0.06)` with a 60px Blur and 0px Offset.

*   **The "Ghost Border":** If a container requires a boundary (e.g., a "Passkey" button), use the `outline_variant` token at **15% opacity**. This provides just enough visual friction without cluttering the UI.

 

---

 

## 5. Component Specifications

 

### Buttons

*   **Primary:** Solid `secondary` (`#242424`) or `inverse_surface` (`#0c0f0f`) for maximum contrast.

    *   *Radius:* `sm` (0.125rem) or `md` (0.375rem).

    *   *Padding:* 12px 24px.

*   **Tertiary (Text-only):** Uses `secondary` for text color. No background, no border.

 

### Input Fields

*   **Styling:** Forgo the 4-sided box. Use a "Minimalist Baseline" approach.

    *   **Border:** Bottom-only, `outline_variant` (`#acadad`).

    *   **Active State:** Transition border-bottom to `secondary` (`#242424`) with a 2px stroke.

    *   **Label:** Positioned above the field in `label-md`, using `on_surface_variant` (`#5a5c5c`).

 

### Cards & Lists

*   **Rule:** No dividers. Use `surface_container_low` background shifts to separate list items or cards.

*   **Spacing:** Use a 4px-base scale. Standard card padding should be `24px` (6 units) to maintain the editorial breathability.

 

---

 

## 6. Do's and Don'ts

 

### Do

*   **Do** use asymmetrical layouts. A heavy content block on the left balanced by an airy white space on the right (as seen in the login split) is a signature of this system.

*   **Do** use high-contrast color pairings (e.g., Pure White text on Deep Blue gradients).

*   **Do** prioritize vertical whitespace over horizontal lines.

 

### Don't

*   **Don't** use 100% black. Use `inverse_surface` (`#0c0f0f`) for high-contrast text to keep the palette sophisticated.

*   **Don't** use standard "drop shadows" with grey colors. They muddy the interface. Always tint your shadows or use tonal layering.

*   **Don't** use fully rounded (pill) buttons for primary actions; stay within the `sm` to `md` (0.125rem - 0.375rem) range to maintain a professional, architectural tone.
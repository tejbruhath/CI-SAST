---
name: Sentriq Bauhaus-Security
colors:
  surface: '#0e1320'
  surface-dim: '#0e1320'
  surface-bright: '#343947'
  surface-container-lowest: '#090e1b'
  surface-container-low: '#161b28'
  surface-container: '#1a1f2d'
  surface-container-high: '#252a37'
  surface-container-highest: '#2f3443'
  on-surface: '#dee2f5'
  on-surface-variant: '#c2c6d6'
  inverse-surface: '#dee2f5'
  inverse-on-surface: '#2b303e'
  outline: '#8c909f'
  outline-variant: '#424753'
  surface-tint: '#afc6ff'
  primary: '#afc6ff'
  on-primary: '#002d6c'
  primary-container: '#528dff'
  on-primary-container: '#00275f'
  inverse-primary: '#0059c6'
  secondary: '#c3c6d3'
  on-secondary: '#2c303a'
  secondary-container: '#454953'
  on-secondary-container: '#b5b8c4'
  tertiary: '#ffb77b'
  on-tertiary: '#4d2700'
  tertiary-container: '#d87802'
  on-tertiary-container: '#432100'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#d9e2ff'
  primary-fixed-dim: '#afc6ff'
  on-primary-fixed: '#001a43'
  on-primary-fixed-variant: '#004398'
  secondary-fixed: '#dfe2ef'
  secondary-fixed-dim: '#c3c6d3'
  on-secondary-fixed: '#181c25'
  on-secondary-fixed-variant: '#434751'
  tertiary-fixed: '#ffdcc2'
  tertiary-fixed-dim: '#ffb77b'
  on-tertiary-fixed: '#2e1500'
  on-tertiary-fixed-variant: '#6d3a00'
  background: '#0e1320'
  on-background: '#dee2f5'
  surface-variant: '#2f3443'
typography:
  display-lg:
    fontFamily: Space Grotesk
    fontSize: 48px
    fontWeight: '700'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Space Grotesk
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.2'
  headline-sm:
    fontFamily: Space Grotesk
    fontSize: 18px
    fontWeight: '600'
    lineHeight: '1.2'
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: '1.4'
  code-label:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0.05em
  headline-lg-mobile:
    fontFamily: Space Grotesk
    fontSize: 32px
    fontWeight: '700'
    lineHeight: '1.2'
spacing:
  unit: 4px
  gutter: 16px
  margin-desktop: 24px
  margin-mobile: 16px
  border-width-thin: 1px
  border-width-thick: 2px
---

## Brand & Style
The design system focuses on a **Professional Neo-Brutalist** aesthetic tailored for high-stakes Security Operations. It prioritizes information density, structural integrity, and an "always-on" monitoring atmosphere.

The style is characterized by:
- **Structural Rawness:** Exposed 2px borders and visible grid lines emphasize the mechanical nature of security systems.
- **Technical Precision:** A fusion of Bauhaus geometry with a modern "Command Center" dark mode.
- **Atmospheric Texture:** Use of low-opacity dot grids (8px intervals) or horizontal scanline overlays (2px height, 3% opacity) on large background surfaces to reduce eye strain and provide visual depth without using shadows.

## Colors
The palette is engineered for a "Deep Space" environment to minimize fatigue during long shifts. 
- **Core Tones:** Backgrounds use Deep Space (#0b0d12) for maximum contrast with critical alerts. Surface panels use Midnight Navy (#151922) to define functional areas.
- **Accents:** Sentriq Blue (#4f8cff) is used sparingly for primary actions and active states to maintain its high-signal value.
- **Alert Tiering:** Status colors follow a strict semantic hierarchy. Critical and High alerts utilize the most vibrant saturations to demand immediate attention.

## Typography
Typography is split into three functional roles:
- **Headlines (Space Grotesk):** Geometric and futuristic. Used for page titles and high-level dashboard metrics.
- **Interface (Inter/System Sans):** Optimized for legibility in dense data tables and sidebars.
- **Technical (JetBrains Mono):** Used for IP addresses, file paths, logs, and status badges. All uppercase with slight tracking is preferred for labels to enhance the "monitored" feel.

## Layout & Spacing
The layout follows a **Fixed-Fluid Hybrid Grid** based on 4px increments.
- **Sidebar & Panels:** Fixed-width navigation and utility panels (typically 64px or 240px) to ensure consistent control locations.
- **Data Grid:** Content areas use a 12-column fluid grid. 
- **Borders as Spacers:** Unlike traditional designs that use whitespace for separation, this system uses 2px Steel Grey (#2a2f3d) borders to define boundaries, allowing for higher information density while maintaining clarity.

## Elevation & Depth
In line with the Neo-Brutalist Bauhaus aesthetic, depth is achieved through **Tonal Layering and Borders** rather than shadows.
- **Level 0 (Background):** Deep Space (#0b0d12) with a faint dot grid.
- **Level 1 (Panels):** Midnight Navy (#151922) with a 2px Steel Grey border.
- **Level 2 (Active/Hover):** Surfaces slightly lighten, or the border color shifts to Sentriq Blue. 
- **Popovers/Modals:** Use a solid 4px Steel Grey border with a high-contrast backdrop overlay (80% opacity) to create "physical" separation.

## Shapes
This design system utilizes **Sharp (0px)** roundedness for all primary UI elements (buttons, inputs, panels, cards). This reinforces the "Industrial/Security" feel. 
- **Exceptions:** Status dots and certain toggle switches may use 100% rounding to distinguish them as interactive "lights" or indicators, but the containers they sit in must remain sharp-edged.

## Components
- **Buttons:** Sharp 2px borders. Primary buttons use a solid Sentriq Blue fill with black text for maximum punch. Ghost buttons use Steel Grey borders that turn blue on hover.
- **Badges:** Use JetBrains Mono. Status badges (e.g., "CRITICAL") should have a solid fill of the status color with high-contrast text. Use a "blinking" animation (1s interval) for active critical alerts.
- **Inputs:** Dark backgrounds (#0b0d12) with 2px borders. On focus, the border shifts to Sentriq Blue.
- **Progress Bars:** Flat, no rounding. Use a segmented "block" style (e.g., 10 separate blocks for 100%) to mimic vintage hardware displays.
- **Skeletons:** Use Midnight Navy blocks with a subtle "scanning" light-sweep effect instead of a soft pulse.
- **Data Tables:** Rigid borders on all sides of cells. Header cells use JetBrains Mono in all caps.
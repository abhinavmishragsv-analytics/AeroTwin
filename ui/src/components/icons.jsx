/**
 * Icons
 * =====
 * Small, hand-drawn line-art SVGs (24x24 viewBox, stroke=currentColor)
 * replacing the emoji glyphs the UI used to reach for. Emoji render
 * differently - sometimes wildly differently - across OS/browser font
 * stacks (flat mono-color on one platform, a full-color cartoon on
 * another), which fought the rest of the UI's deliberately flat, monochrome
 * instrument-panel look. These inherit `color` like any other text and stay
 * visually consistent everywhere.
 *
 * Each icon takes the same two props: `size` (px, default 16) and
 * `className`, so they drop into a button next to a text label the same way
 * an emoji character used to.
 */
const base = (size) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
});

export function IconCone({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3l5 15H7l5-15z" />
      <path d="M8.5 12.5h7" />
      <path d="M4 21h16" />
    </svg>
  );
}

export function IconOctagonStop({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M8 3h8l5 5v8l-5 5H8l-5-5V8l5-5z" />
      <path d="M9 12h6" />
    </svg>
  );
}

export function IconFog({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M6 10a4 4 0 0 1 7.6-1.8A3.5 3.5 0 0 1 18 11.5" />
      <path d="M4 14h16" />
      <path d="M6 17.5h12" />
      <path d="M8 21h8" />
    </svg>
  );
}

export function IconHaze({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="9" r="3.2" />
      <path d="M3 15h18" />
      <path d="M5 18h14" />
      <path d="M8 21h8" />
    </svg>
  );
}

export function IconWind({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M3 8h10.5a2.5 2.5 0 1 0-2.4-3.2" />
      <path d="M3 12.5h14a2.5 2.5 0 1 1-2.4 3.2" />
      <path d="M3 17h8.5a2 2 0 1 1-1.9 2.6" />
    </svg>
  );
}

export function IconStorm({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M6 10a4 4 0 0 1 7.6-1.8A3.5 3.5 0 0 1 18 11.5" />
      <path d="M5 14h14" />
      <path d="M13 14l-2.5 4h3L11 22" />
    </svg>
  );
}

export function IconNoEntry({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M6 12h12" />
    </svg>
  );
}

export function IconSiren({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M5 20v-5a7 7 0 0 1 14 0v5z" />
      <path d="M4 20h16" />
      <path d="M12 4v2.2" />
      <path d="M6.5 6.5l1.4 1.4" />
      <path d="M17.5 6.5l-1.4 1.4" />
    </svg>
  );
}

export function IconWarningTriangle({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 3.5l9.5 16.5H2.5L12 3.5z" />
      <path d="M12 10v4.2" />
      <circle cx="12" cy="17.2" r="0.15" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconCheckCircle({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.5 2.5L16 9.5" />
    </svg>
  );
}

export function IconGlobe({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3c2.6 2.5 4 5.7 4 9s-1.4 6.5-4 9c-2.6-2.5-4-5.7-4-9s1.4-6.5 4-9z" />
    </svg>
  );
}

export function IconPlane({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 2.5l1.6 1.6v6.4l6.9 4v2l-6.9-2.1v4.4l2.4 1.8v1.6L12 21l-4-1.4v-1.6l2.4-1.8v-4.4L3.5 12.5v-2l6.9-4V4.1L12 2.5z" />
    </svg>
  );
}

export function IconTower({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M9 8h6l1.4 4.5H7.6L9 8z" />
      <path d="M8 12.5h8L17.3 21H6.7L8 12.5z" />
      <path d="M12 8V3" />
      <path d="M10 3h4" />
    </svg>
  );
}

export function IconRunway({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M9 3l-3 18" />
      <path d="M15 3l3 18" />
      <path d="M11.3 8h1.4" />
      <path d="M10.9 12h2.2" />
      <path d="M10.5 16h3" />
    </svg>
  );
}

export function IconPause({ size = 16, className }) {
  return (
    <svg {...base(size)} className={className}>
      <rect x="6" y="4.5" width="4" height="15" rx="0.8" />
      <rect x="14" y="4.5" width="4" height="15" rx="0.8" />
    </svg>
  );
}

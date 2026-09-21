/**
 * CollapseToggle - the little chevron every panel gets in its header. Purely
 * presentational: the panel that renders it owns the `collapsed` boolean and
 * decides what to hide when it's true. Shared so every panel folds with the
 * same look and the same click target size, instead of each one growing its
 * own slightly-different arrow button.
 */
export default function CollapseToggle({ collapsed, onToggle, label }) {
  return (
    <button
      type="button"
      className={`panel-collapse-btn ${collapsed ? "collapsed" : ""}`}
      onClick={onToggle}
      aria-label={label || (collapsed ? "Expand panel" : "Collapse panel")}
      aria-expanded={!collapsed}
    >
      <span className="chevron">▾</span>
    </button>
  );
}

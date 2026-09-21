/**
 * AirportSwitcher - lets the person jump between airports without typing a
 * URL. Navigates to /<slug>, which App.jsx resolves via lib/api.js the same
 * way a direct link would - so this is a convenience, not a separate code path.
 */
export default function AirportSwitcher({ airports, current }) {
  if (!airports?.length) return null;
  return (
    <select
      className="airport-switcher"
      value={current || ""}
      onChange={(e) => {
        const slug = e.target.value;
        window.location.pathname = slug ? `/${slug}` : "/";
      }}
    >
      {airports.map((a) => (
        <option key={a.icao} value={a.slug}>
          {a.city} ({a.iata})
        </option>
      ))}
    </select>
  );
}

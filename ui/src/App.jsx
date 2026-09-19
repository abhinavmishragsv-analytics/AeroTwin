/**
 * AeroTwin App
 * ============
 * The frontend's job is now narrow and honest: resolve which airport the URL
 * points at, open its WebSocket, and render exactly what the server sends -
 * the generated airfield geometry once, then a traffic frame at STREAM_HZ.
 * No coordinate, no taxiway shape, no marking dimension is decided here; that
 * all lives in core/airports/geometry.py so the picture can never drift from
 * what the simulation believes the airport looks like.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import DeckGL from "@deck.gl/react";
import { Map as MapLibreMap } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";

import { airportViewState, buildAirfieldLayers, towerViewState } from "./lib/airfieldLayers";
import { buildAircraftLayers } from "./lib/aircraftLayers";
import { fetchAirports, postDisruption, slugFromPath, twinSocketUrl } from "./lib/api";

import HUD from "./components/HUD";
import FlightStrips from "./components/FlightStrips";
import AtcConsole from "./components/AtcConsole";
import CameraBar from "./components/CameraBar";
import WeatherOverlay from "./components/WeatherOverlay";
import AirportSwitcher from "./components/AirportSwitcher";

const SATELLITE_STYLE = {
  version: 8,
  sources: {
    satellite: {
      type: "raster",
      tiles: [
        // The canonical host, not the older "server." one - that redirects
        // here, and a redirect can drop CORS headers in some fetch paths.
        "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Esri World Imagery",
    },
  },
  layers: [{ id: "satellite", type: "raster", source: "satellite" }],
};

// deck.gl's MapController asserts that viewState.longitude/latitude are
// finite numbers the moment it mounts - before React even gets to run our
// effects, let alone before the WebSocket delivers the real airport layout.
// Passing `undefined` (or null) as the initial viewState throws inside
// MapState's constructor and takes the whole render tree down with it, which
// is the black screen: there is no fallback UI for a deck.gl crash. Seeding a
// real, finite default here means the very first frame is a valid (if
// unremarkable) view of India, and it gets replaced by the airport's own
// view state the instant the layout frame arrives - see the WebSocket
// `onmessage` handler below.
const FALLBACK_VIEW_STATE = {
  longitude: 78.9629,
  latitude: 22.5937,
  zoom: 3.6,
  pitch: 0,
  bearing: 0,
};

export default function App() {
  const [airports, setAirports] = useState([]);
  const [identifier] = useState(slugFromPath() || "vabo");
  const [layout, setLayout] = useState(null);
  const [frame, setFrame] = useState(null);
  const [connected, setConnected] = useState(false);
  const [camera, setCamera] = useState("orbit");
  const [viewState, setViewState] = useState(FALLBACK_VIEW_STATE);
  const wsRef = useRef(null);

  useEffect(() => {
    fetchAirports()
      .then((d) => setAirports(d.airports || []))
      .catch(() => setAirports([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setConnected(false);
    setLayout(null);
    setFrame(null);

    const ws = new WebSocket(twinSocketUrl(identifier));
    wsRef.current = ws;

    ws.onopen = () => !cancelled && setConnected(true);
    ws.onclose = () => !cancelled && setConnected(false);
    ws.onerror = () => !cancelled && setConnected(false);
    ws.onmessage = (evt) => {
      if (cancelled) return;
      const msg = JSON.parse(evt.data);
      if (msg.kind === "layout") {
        setLayout(msg.layout);
        // Fly from the fallback (or the previous airport, if switching) to
        // this one. Unconditional, not "only if we don't have a view yet" -
        // the old `prev || …` guard relied on the initial state being null,
        // which stopped being true once a real fallback replaced it.
        setViewState({ ...airportViewState(msg.layout), transitionDuration: 1200 });
      } else {
        setFrame(msg);
      }
    };

    return () => {
      cancelled = true;
      ws.close();
    };
  }, [identifier]);

  const handleDisrupt = useCallback(
    (type, minutes, target) => {
      postDisruption(identifier, { type, duration_minutes: minutes, target }).catch(() => {});
    },
    [identifier]
  );

  useEffect(() => {
    if (!layout || camera === "chase") return;
    if (camera === "orbit") {
      setViewState({ ...airportViewState(layout), pitch: 55, zoom: 15.4, transitionDuration: 800 });
    } else if (camera === "tower") {
      // A real vantage point (the ATC tower's own coordinates) looking out
      // toward the runway - not the airport centre pitched down further.
      setViewState({ ...towerViewState(layout), transitionDuration: 800 });
    } else if (camera === "runway") {
      setViewState({ ...airportViewState(layout), pitch: 78, zoom: 17.8, transitionDuration: 800 });
    }
  }, [camera, layout]);

  const flights = frame?.flights || [];

  useEffect(() => {
    if (camera !== "chase" || !flights.length) return;
    const target = flights.find((f) => f.status !== "parked") || flights[0];
    if (!target) return;
    setViewState({
      longitude: target.lng,
      latitude: target.lat,
      zoom: 17.6,
      pitch: 62,
      bearing: target.heading,
      transitionDuration: 0,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera, frame]);

  const layers = useMemo(() => {
    if (!layout) return [];
    return [...buildAirfieldLayers(layout), ...buildAircraftLayers(flights)];
  }, [layout, flights]);

  const twin = frame?.twin;

  return (
    <div className="app-root">
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: vs }) => setViewState(vs)}
        controller={true}
        layers={layers}
      >
        <MapLibreMap mapStyle={SATELLITE_STYLE} />
      </DeckGL>

      <div className="overlay top-left">
        <HUD
          airportName={layout?.name}
          icao={layout?.icao || identifier.toUpperCase()}
          connected={connected}
          frame={frame}
        />
        <FlightStrips flights={flights} />
      </div>

      <div className="overlay top-right">
        <AirportSwitcher airports={airports} current={layout?.slug} />
        <WeatherOverlay
          weather={twin?.weather}
          windAssessment={twin?.wind}
          activeEnd={twin?.runway?.active_end}
        />
        <AtcConsole onDisrupt={handleDisrupt} disruptions={twin?.disruptions} />
      </div>

      <CameraBar active={camera} onSelect={setCamera} />
    </div>
  );
}

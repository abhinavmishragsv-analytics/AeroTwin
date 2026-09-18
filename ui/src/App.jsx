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

import { airportViewState, buildAirfieldLayers } from "./lib/airfieldLayers";
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
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Esri World Imagery",
    },
  },
  layers: [{ id: "satellite", type: "raster", source: "satellite" }],
};

export default function App() {
  const [airports, setAirports] = useState([]);
  const [identifier] = useState(slugFromPath() || "vabo");
  const [layout, setLayout] = useState(null);
  const [frame, setFrame] = useState(null);
  const [connected, setConnected] = useState(false);
  const [camera, setCamera] = useState("orbit");
  const [viewState, setViewState] = useState(null);
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
        setViewState((prev) => prev || { ...airportViewState(msg.layout), transitionDuration: 0 });
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
    const base = airportViewState(layout);
    if (camera === "orbit") {
      setViewState({ ...base, pitch: 55, zoom: 15.4, transitionDuration: 800 });
    } else if (camera === "tower") {
      setViewState({ ...base, pitch: 70, zoom: 17.2, transitionDuration: 800 });
    } else if (camera === "runway") {
      setViewState({ ...base, pitch: 78, zoom: 17.8, transitionDuration: 800 });
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
        viewState={viewState || undefined}
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

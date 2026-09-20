import { useEffect, useRef } from "react";
import { WeatherFXRenderer } from "../lib/weatherFX";

/**
 * WeatherFX - mounts the canvas atmosphere renderer (see lib/weatherFX.js)
 * and keeps it in sync with the live twin state. Pure pass-through: this
 * component owns no visual logic itself, only the React lifecycle around an
 * imperative rAF-driven renderer that doesn't want to be torn down and
 * rebuilt on every store update.
 */
export default function WeatherFX({ targets, bearing }) {
  const canvasRef = useRef(null);
  const rendererRef = useRef(null);

  useEffect(() => {
    if (!canvasRef.current) return undefined;
    rendererRef.current = new WeatherFXRenderer(canvasRef.current);
    return () => {
      rendererRef.current?.destroy();
      rendererRef.current = null;
    };
  }, []);

  useEffect(() => {
    rendererRef.current?.setTargets(targets);
  }, [targets]);

  useEffect(() => {
    rendererRef.current?.setBearing(bearing);
  }, [bearing]);

  return <canvas ref={canvasRef} className="weather-fx-canvas" />;
}

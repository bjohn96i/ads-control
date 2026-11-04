import type Hls from "hls.js";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getJson, type TrafficCamera } from "../api/client";

// 511GA refreshes each picture about once a minute, so asking more often gains nothing.
const REFRESH_MS = 60_000;
// Stream tokens last two minutes; 511GA's own player asks for a new one every minute too.
const TOKEN_REFRESH_MS = 60_000;
// Stop like the house cameras do, so a forgotten tab doesn't stream all day.
const LIVE_LIMIT_MS = 5 * 60 * 1000;

/** Every playlist and video piece is fetched with the newest token, not the one it was listed with. */
export function withToken(url: string, token: string): string {
  const parsed = new URL(url);
  parsed.searchParams.set("token", token);
  return parsed.toString();
}

const tokenOf = (url: string) => new URL(url).searchParams.get("token") ?? "";

function useMinute(): number {
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setTick(Date.now()), REFRESH_MS);
    return () => clearInterval(timer);
  }, []);
  return tick;
}

function TrafficVideo({ camera, onStop }: { camera: TrafficCamera; onStop: (ended: boolean) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let player: Hls | null = null;
    let token = "";
    let stopped = false;
    const address = () => getJson<{ url: string }>(`/api/traffic/${camera.view}/video`);
    const refresh = setInterval(() => {
      address()
        .then(({ url }) => {
          token = tokenOf(url);
        })
        .catch(() => {}); // the old token still has a minute left; the next try may work
    }, TOKEN_REFRESH_MS);
    const limit = setTimeout(() => onStop(true), LIVE_LIMIT_MS);

    (async () => {
      try {
        const { url } = await address();
        token = tokenOf(url);
        const { default: Player } = await import("hls.js");
        if (stopped || !video.current) return;
        if (Player.isSupported()) {
          player = new Player({ xhrSetup: (xhr, next) => xhr.open("GET", withToken(next, token), true) });
          player.loadSource(url);
          player.attachMedia(video.current);
        } else {
          // shortcut: Safari's own player keeps the first token, so it may stop after two minutes.
          video.current.src = url;
        }
      } catch {
        if (!stopped) setError(true);
      }
    })();

    return () => {
      stopped = true;
      clearInterval(refresh);
      clearTimeout(limit);
      player?.destroy();
    };
  }, [camera.view, onStop]);

  if (error) {
    return (
      <p className="warn" role="alert">
        Live video isn't available for this camera right now.
      </p>
    );
  }
  return <video ref={video} data-testid="traffic-video" autoPlay playsInline muted controls />;
}

function LiveTile({ camera, tick }: { camera: TrafficCamera; tick: number }) {
  const [state, setState] = useState<"idle" | "live" | "ended">("idle");
  const stop = useCallback((ended: boolean) => setState(ended ? "ended" : "idle"), []);
  return (
    <figure className="traffic-cam">
      {state === "live" ? (
        <TrafficVideo camera={camera} onStop={stop} />
      ) : (
        <img src={`${camera.image_url}?t=${tick}`} alt={`Traffic at ${camera.nickname}`} loading="lazy" />
      )}
      <figcaption>
        {camera.nickname}
        <span>{camera.name}</span>
      </figcaption>
      {state === "live" ? (
        <button type="button" onClick={() => stop(false)}>
          Stop
        </button>
      ) : (
        <button type="button" onClick={() => setState("live")}>
          {state === "ended" ? "Watch again" : "Watch live"}
        </button>
      )}
    </figure>
  );
}

export function TrafficCams({
  cameras,
  linkTo,
  live = false,
  className = "",
}: {
  cameras: TrafficCamera[];
  linkTo?: string;
  live?: boolean;
  className?: string;
}) {
  const tick = useMinute();
  return (
    <div className={`traffic ${className}`}>
      {cameras.map((camera) => {
        if (live) return <LiveTile key={camera.view} camera={camera} tick={tick} />;
        const body = (
          <>
            <img src={`${camera.image_url}?t=${tick}`} alt={`Traffic at ${camera.nickname}`} loading="lazy" />
            <figcaption>
              {camera.nickname}
              <span>{camera.name}</span>
            </figcaption>
          </>
        );
        return linkTo ? (
          <Link key={camera.view} className="traffic-cam" to={linkTo}>
            <figure>{body}</figure>
          </Link>
        ) : (
          <figure key={camera.view} className="traffic-cam">
            {body}
          </figure>
        );
      })}
    </div>
  );
}

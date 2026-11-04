import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { type CameraEvent, type CameraInfo, getJson, send, type TrafficCamera } from "../api/client";
import { CameraEventTable, eventText } from "../components/CameraEvents";
import { PinGate } from "../components/PinGate";
import { TrafficCams } from "../components/TrafficCams";

// Google ends these streams at five minutes and won't extend them on battery cameras.
export const LIVE_LIMIT_MS = 5 * 60 * 1000;

type Stream = { peer: RTCPeerConnection; sessionId: string | null; timer: ReturnType<typeof setTimeout> };

function LiveVideo({ camera }: { camera: CameraInfo }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<Stream | null>(null);
  const [state, setState] = useState<"idle" | "live" | "ended">("idle");
  const [error, setError] = useState<string | null>(null);

  const stop = useCallback(() => {
    const current = stream.current;
    if (!current) return;
    stream.current = null;
    clearTimeout(current.timer);
    current.peer.close();
    if (current.sessionId) {
      send("DELETE", `/api/cameras/${camera.id}/live/${current.sessionId}`).catch(() => {
        // Google ends it by itself within five minutes.
      });
    }
  }, [camera.id]);

  useEffect(() => stop, [stop]);

  const start = async () => {
    setError(null);
    setState("live");
    const peer = new RTCPeerConnection();
    const timer = setTimeout(() => {
      stop();
      setState("ended");
    }, LIVE_LIMIT_MS);
    const current: Stream = { peer, sessionId: null, timer };
    stream.current = current;
    peer.ontrack = (event) => {
      if (event.track.kind === "video" && video.current) video.current.srcObject = event.streams[0];
    };
    // Google requires these three, in this order.
    peer.addTransceiver("audio", { direction: "recvonly" });
    peer.addTransceiver("video", { direction: "recvonly" });
    peer.createDataChannel("dataSendChannel");
    try {
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      const answer = await send<{ answer_sdp: string; media_session_id: string }>(
        "POST",
        `/api/cameras/${camera.id}/live`,
        { offer_sdp: offer.sdp },
      );
      current.sessionId = answer.media_session_id;
      if (stream.current !== current) {
        // Stopped while waiting for Google, so end what Google just opened.
        send("DELETE", `/api/cameras/${camera.id}/live/${answer.media_session_id}`).catch(() => {});
        return;
      }
      await peer.setRemoteDescription({ type: "answer", sdp: answer.answer_sdp });
    } catch {
      stop();
      setState("idle");
      setError("This camera isn't available for live video right now.");
    }
  };

  return (
    <>
      {state === "live" ? (
        <video ref={video} data-testid="live-video" autoPlay playsInline muted controls />
      ) : null}
      {state === "live" ? (
        <button
          type="button"
          onClick={() => {
            stop();
            setState("idle");
          }}
        >
          Stop
        </button>
      ) : (
        <button type="button" onClick={start}>
          {state === "ended" ? "Watch again" : "Watch live"}
        </button>
      )}
      {error ? (
        <p className="warn" role="alert">
          {error}
        </p>
      ) : null}
    </>
  );
}

export function CamerasView() {
  const auth = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => getJson<{ unlocked: boolean }>("/api/auth/status"),
  });
  const { data, isError } = useQuery({
    queryKey: ["cameras"],
    queryFn: () => getJson<{ cameras: CameraInfo[] }>("/api/cameras"),
    refetchInterval: 30_000,
  });
  const traffic = useQuery({
    queryKey: ["traffic"],
    queryFn: () => getJson<{ cameras: TrafficCamera[] }>("/api/traffic"),
  });
  const events = useQuery({
    queryKey: ["camera-events", 25],
    queryFn: () => getJson<{ events: CameraEvent[] }>("/api/cameras/events?limit=25"),
    refetchInterval: 30_000,
  });

  return (
    <main className="page">
      <header className="top">
        <h1>Cameras</h1>
        {auth.data ? <span className="meta">{auth.data.unlocked ? "Unlocked" : "Locked"}</span> : null}
      </header>
      {isError ? (
        <p className="warn" role="alert">
          Can't reach the house server
        </p>
      ) : null}
      {traffic.data?.cameras.length ? (
        <>
          <div className="section-head">
            <h2>Traffic nearby · Georgia 511</h2>
            <span>Watch any of them live</span>
          </div>
          <TrafficCams cameras={traffic.data.cameras} live />
        </>
      ) : null}
      <div className="section-head">
        <h2>At the house</h2>
        <span>Live only when you press Watch live</span>
      </div>
      <section className="house">
        {data?.cameras.length === 0 ? <p className="sub">No cameras found yet.</p> : null}
        {/* One PIN box for the page; once unlocked it renders nothing and the video controls appear. */}
        <PinGate>{null}</PinGate>
        <div className="house-cams">
          {data?.cameras.map((camera) => (
            <article key={camera.id} className="panel camera-card">
              <div className="kind">{camera.kind}</div>
              <h3>{camera.name}</h3>
              <p className="sub">{eventText(camera)}</p>
              {auth.data?.unlocked ? <LiveVideo camera={camera} /> : null}
            </article>
          ))}
        </div>
      </section>
      {events.data ? (
        <>
          <div className="section-head">
            <h2>Last 25 camera events</h2>
          </div>
          <div className="card">
            <CameraEventTable events={events.data.events} />
          </div>
        </>
      ) : null}
    </main>
  );
}

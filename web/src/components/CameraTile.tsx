import { Link } from "react-router-dom";
import type { CameraInfo } from "../api/client";

const EVENT_TEXT: Record<string, string> = {
  motion: "Motion",
  person: "Person",
  sound: "Sound",
  chime: "Doorbell rang",
};

export function eventText(camera: CameraInfo): string {
  if (!camera.last_event || !camera.last_event_at) return "No events yet";
  const when = new Date(camera.last_event_at).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  return `${EVENT_TEXT[camera.last_event] ?? camera.last_event}, ${when}`;
}

export function ageText(seconds: number): string {
  if (seconds < 3600) return `${Math.max(1, Math.round(seconds / 60))} min ago`;
  if (seconds < 172_800) return `${Math.round(seconds / 3600)} hrs ago`;
  return `${Math.round(seconds / 86_400)} days ago`;
}

export function CameraTile({ camera, unlocked }: { camera: CameraInfo; unlocked: boolean }) {
  const showImage = unlocked && camera.has_image;
  return (
    <Link className="camera" to="/cameras">
      {showImage ? (
        <img
          src={`/api/cameras/${camera.id}/image?age=${camera.last_event_at}`}
          alt={`Last event at ${camera.name}`}
        />
      ) : null}
      <span className="label">{camera.name}</span>
      <span className="sub">{eventText(camera)}</span>
      {showImage && camera.image_age_s !== null ? (
        <span className="sub">Picture from {ageText(camera.image_age_s)}</span>
      ) : null}
    </Link>
  );
}

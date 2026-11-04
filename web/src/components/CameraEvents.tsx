import type { CameraEvent, CameraInfo } from "../api/client";

const EVENT_TEXT: Record<string, string> = {
  motion: "Motion",
  person: "Person",
  sound: "Sound",
  chime: "Doorbell rang",
};

const label = (type: string) => EVENT_TEXT[type] ?? type;

function when(at: string): string {
  return new Date(at).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function eventText(camera: CameraInfo): string {
  if (!camera.last_event || !camera.last_event_at) return "No events yet";
  return `${label(camera.last_event)}, ${when(camera.last_event_at)}`;
}

export function CameraEventTable({ events }: { events: CameraEvent[] }) {
  if (events.length === 0) return <p className="sub">No camera events yet.</p>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Camera</th>
            <th>Event</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={`${e.camera_id}-${e.occurred_at}-${e.type}`}>
              <td>{when(e.occurred_at)}</td>
              <td>{e.camera}</td>
              <td>{label(e.type)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The short form for the home page: camera and what happened on the left, the time on the right. */
export function CameraEventList({ events }: { events: CameraEvent[] }) {
  if (events.length === 0) return <p className="sub">No camera events yet.</p>;
  return (
    <>
      {events.map((e) => (
        <div key={`${e.camera_id}-${e.occurred_at}-${e.type}`} className="row">
          <span>
            <span>{e.camera}</span> · <span className="d">{label(e.type)}</span>
          </span>
          <span className="d">{new Date(e.occurred_at).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}</span>
        </div>
      ))}
    </>
  );
}

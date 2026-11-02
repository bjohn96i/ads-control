export function CameraTile({ name }: { name: string }) {
  return (
    <div className="camera">
      <span className="label">{name}</span>
      <span className="sub">Not connected yet</span>
    </div>
  );
}

const ITEMS = ["Thermostats", "Maintenance", "Last bill"];

export function StatusStrip() {
  return (
    <div className="strip">
      {ITEMS.map((item) => (
        <span key={item}>
          {item}: not connected yet
        </span>
      ))}
    </div>
  );
}

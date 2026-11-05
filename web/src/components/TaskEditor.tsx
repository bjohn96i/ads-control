import { type FormEvent, useState } from "react";
import type { MaintenanceItem, MaintenanceTask, RepeatUnit } from "../api/client";

export type Act = (method: string, path: string, body?: unknown) => Promise<boolean>;

/** Whole months above zero, or null for "no repeat". undefined means not valid. */
export function parseRepeat(text: string): number | null | undefined {
  if (text.trim() === "") return null;
  const count = Number(text);
  return Number.isInteger(count) && count >= 1 ? count : undefined;
}

const REPEAT_ERROR = "Repeat must be a whole number, or blank.";

function UnitSelect({ label, value, onChange }: { label: string; value: RepeatUnit; onChange: (unit: RepeatUnit) => void }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value as RepeatUnit)}>
      <option value="day">days</option>
      <option value="week">weeks</option>
      <option value="month">months</option>
    </select>
  );
}

function RoomRow({
  item,
  act,
}: {
  item: MaintenanceItem;
  act: Act;
}) {
  const [name, setName] = useState(item.name);
  const [confirming, setConfirming] = useState(false);

  const rename = () => {
    const trimmed = name.trim();
    if (!trimmed) setName(item.name);
    else if (trimmed !== item.name) act("PATCH", `/api/maintenance/items/${item.id}`, { name: trimmed });
  };

  if (confirming) {
    return (
      <div className="confirm">
        <span>Remove {item.name} and its history?</span>
        <button
          type="button"
          className="danger"
          onClick={() => act("DELETE", `/api/maintenance/items/${item.id}`)}
        >
          Yes, remove
        </button>
        <button type="button" onClick={() => setConfirming(false)}>
          Keep it
        </button>
      </div>
    );
  }
  return (
    <div className="room-row">
      <input
        type="text"
        aria-label={`Room name: ${item.name}`}
        value={name}
        onChange={(event) => setName(event.target.value)}
        onBlur={rename}
      />
      <button
        type="button"
        className="link"
        aria-label={`Remove ${item.name}`}
        onClick={() => setConfirming(true)}
      >
        Remove
      </button>
    </div>
  );
}

export function TaskEditor({
  task,
  act,
  onError,
  onClose,
}: {
  task: MaintenanceTask;
  act: Act;
  onError: (message: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState(task.name);
  const [category, setCategory] = useState(task.category);
  const [notes, setNotes] = useState(task.notes);
  const [repeat, setRepeat] = useState(task.repeat_every?.toString() ?? "");
  const [unit, setUnit] = useState<RepeatUnit>(task.repeat_unit);
  const [newRoom, setNewRoom] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const every = parseRepeat(repeat);
    if (every === undefined) return onError(REPEAT_ERROR);
    if (!name.trim() || !category.trim()) return onError("A task needs a name and a category.");
    const changes: Record<string, unknown> = {};
    if (name.trim() !== task.name) changes.name = name.trim();
    if (category.trim() !== task.category) changes.category = category.trim();
    if (notes !== task.notes) changes.notes = notes;
    if (every !== task.repeat_every) changes.repeat_every = every;
    if (unit !== task.repeat_unit) changes.repeat_unit = unit;
    if (Object.keys(changes).length === 0 || (await act("PATCH", `/api/maintenance/${task.id}`, changes))) {
      onClose();
    }
  };

  const addRoom = async () => {
    const trimmed = newRoom.trim();
    if (trimmed && (await act("POST", `/api/maintenance/${task.id}/items`, { name: trimmed }))) {
      setNewRoom("");
    }
  };

  return (
    <form className="editor" noValidate onSubmit={save}>
      <label>
        Name
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        Category
        <input type="text" value={category} onChange={(e) => setCategory(e.target.value)} />
      </label>
      <label>
        Notes
        <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="repeat">
        <label>
          Repeat every
          <input type="number" min={1} value={repeat} onChange={(e) => setRepeat(e.target.value)} />
        </label>
        <UnitSelect label="Repeat unit" value={unit} onChange={setUnit} />
      </div>
      <p className="sub">Blank for no repeat.</p>
      <div className="task-actions">
        <button type="submit">Save changes</button>
        <button type="button" className="link" onClick={onClose}>
          Cancel
        </button>
      </div>

      <div className="field">
        Rooms
        {task.items.map((item) => (
          <RoomRow key={item.id} item={item} act={act} />
        ))}
        <div className="room-row">
          <input
            type="text"
            aria-label="New room"
            placeholder="New room"
            value={newRoom}
            onChange={(e) => setNewRoom(e.target.value)}
          />
          <button type="button" onClick={addRoom}>
            Add room
          </button>
        </div>
      </div>

      {confirmingDelete ? (
        <div className="confirm">
          <span>Delete {task.name} and all its history? This can't be undone.</span>
          <button
            type="button"
            className="danger"
            onClick={() => act("DELETE", `/api/maintenance/${task.id}`)}
          >
            Yes, delete
          </button>
          <button type="button" onClick={() => setConfirmingDelete(false)}>
            Keep it
          </button>
        </div>
      ) : (
        <div>
          <button type="button" className="link danger" onClick={() => setConfirmingDelete(true)}>
            Delete task
          </button>
        </div>
      )}
    </form>
  );
}

export function AddTask({
  categories,
  act,
  onError,
}: {
  categories: string[];
  act: Act;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [category, setCategory] = useState(categories[0] ?? "House");
  const [notes, setNotes] = useState("");
  const [repeat, setRepeat] = useState("");
  const [unit, setUnit] = useState<RepeatUnit>("month");
  const [rooms, setRooms] = useState("");

  if (!open) {
    return (
      <div className="add-task">
        <button type="button" onClick={() => setOpen(true)}>
          Add a task
        </button>
      </div>
    );
  }

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const every = parseRepeat(repeat);
    if (every === undefined) return onError(REPEAT_ERROR);
    if (!name.trim() || !category.trim()) return onError("A task needs a name and a category.");
    const items = [...new Set(rooms.split("\n").map((r) => r.trim()).filter(Boolean))];
    const body = { name: name.trim(), category: category.trim(), notes, repeat_every: every, repeat_unit: unit, items };
    if (await act("POST", "/api/maintenance", body)) {
      setOpen(false);
      setName("");
      setNotes("");
      setRepeat("");
      setUnit("month");
      setRooms("");
    }
  };

  return (
    <form className="panel task add-task editor" noValidate onSubmit={save}>
      <label>
        Task name
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <label>
        New task category
        <input
          type="text"
          list="task-categories"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        />
        <datalist id="task-categories">
          {categories.map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </label>
      <label>
        Notes
        <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} />
      </label>
      <div className="repeat">
        <label>
          New task repeat
          <input type="number" min={1} value={repeat} onChange={(e) => setRepeat(e.target.value)} />
        </label>
        <UnitSelect label="New task repeat unit" value={unit} onChange={setUnit} />
      </div>
      <p className="sub">Blank for no repeat.</p>
      <label>
        Rooms, one per line (optional)
        <textarea rows={3} value={rooms} onChange={(e) => setRooms(e.target.value)} />
      </label>
      <div className="task-actions">
        <button type="submit">Save task</button>
        <button type="button" className="link" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

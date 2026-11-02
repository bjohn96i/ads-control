import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getJson, type MaintenanceTask, send } from "../api/client";
import { dueText } from "../components/format";

const PEOPLE = ["John", "Sam"];
const UNDO_MS = 10_000;

function loadWho(): string | null {
  try {
    return localStorage.getItem("who");
  } catch {
    return null;
  }
}

function saveWho(who: string): void {
  try {
    localStorage.setItem("who", who);
  } catch {
    // Private windows can refuse storage; the choice still holds until the page closes.
  }
}

function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

type Mark = { taskId: number; name: string; itemIds?: number[]; doneOn: string };

function TaskCard({
  task,
  onMark,
  onInterval,
}: {
  task: MaintenanceTask;
  onMark: (mark: Mark) => void;
  onInterval: (taskId: number, months: number | null) => void;
}) {
  const today = localToday();
  const [ticked, setTicked] = useState<number[]>([]);
  const [doneOn, setDoneOn] = useState(today);
  const [repeat, setRepeat] = useState(task.interval_months?.toString() ?? "");
  const hasRooms = task.items.length > 0;
  const due = dueText(task.next_due, task.overdue);

  const toggle = (id: number) =>
    setTicked((now) => (now.includes(id) ? now.filter((i) => i !== id) : [...now, id]));

  const mark = () => {
    onMark({
      taskId: task.id,
      name: task.name,
      itemIds: hasRooms ? ticked : undefined,
      doneOn,
    });
    setTicked([]);
    setDoneOn(today);
  };

  const saveRepeat = () => {
    const months = repeat === "" ? null : Number(repeat);
    if (months === task.interval_months) return;
    if (months !== null && (!Number.isInteger(months) || months < 1)) return;
    onInterval(task.id, months);
  };

  let label: string;
  if (hasRooms) {
    label =
      ticked.length === 0
        ? "Tick the rooms you did"
        : `Mark ${ticked.length} ${ticked.length === 1 ? "room" : "rooms"} done`;
  } else {
    label = doneOn === today ? "Done today" : "Mark done";
  }

  return (
    <article className={task.overdue ? "panel task overdue" : "panel task"}>
      <h2>{task.name}</h2>
      {due ? <p className="due">{due}</p> : null}
      {!hasRooms ? (
        <p className="sub">{task.last_done ? `Last done ${task.last_done}` : "Never done"}</p>
      ) : null}
      {task.notes ? <p className="sub">{task.notes}</p> : null}
      {hasRooms ? (
        <div className="rooms">
          {task.items.map((item) => (
            <label key={item.id}>
              <input
                type="checkbox"
                checked={ticked.includes(item.id)}
                onChange={() => toggle(item.id)}
              />
              {item.name}
              <small>{item.last_done ?? "Never done"}</small>
            </label>
          ))}
        </div>
      ) : null}
      <div className="task-actions">
        <button type="button" disabled={hasRooms && ticked.length === 0} onClick={mark}>
          {label}
        </button>
        <label>
          Date
          <input
            type="date"
            max={today}
            value={doneOn}
            onChange={(event) => setDoneOn(event.target.value)}
          />
        </label>
        <label>
          Repeat every
          <input
            type="number"
            min={1}
            value={repeat}
            onChange={(event) => setRepeat(event.target.value)}
            onBlur={saveRepeat}
          />
          months
        </label>
      </div>
    </article>
  );
}

export function MaintenanceView() {
  const client = useQueryClient();
  const [who, setWho] = useState(loadWho);
  const [undo, setUndo] = useState<{ name: string; ids: number[] } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const { data, isError } = useQuery({
    queryKey: ["maintenance"],
    queryFn: () => getJson<{ tasks: MaintenanceTask[] }>("/api/maintenance"),
  });

  const refresh = () => {
    client.invalidateQueries({ queryKey: ["maintenance"] });
    client.invalidateQueries({ queryKey: ["maintenance-next"] });
  };

  useEffect(() => {
    if (!undo) return;
    const timer = setTimeout(() => setUndo(null), UNDO_MS);
    return () => clearTimeout(timer);
  }, [undo]);

  const complete = useMutation({
    mutationFn: ({ taskId, itemIds, doneOn }: Mark) =>
      send<{ completion_ids: number[] }>("POST", `/api/maintenance/${taskId}/complete`, {
        item_ids: itemIds,
        done_on: doneOn,
        who,
      }),
    onSuccess: (result, mark) => {
      setFailed(false);
      if (result.completion_ids.length > 0) {
        setMessage(null);
        setUndo({ name: mark.name, ids: result.completion_ids });
      } else {
        setUndo(null);
        setMessage(`${mark.name} was already recorded for that date.`);
      }
      refresh();
    },
    onError: () => setFailed(true),
  });

  const interval = useMutation({
    mutationFn: ({ taskId, months }: { taskId: number; months: number | null }) =>
      send("PATCH", `/api/maintenance/${taskId}`, { interval_months: months }),
    onSuccess: () => {
      setFailed(false);
      refresh();
    },
    onError: () => setFailed(true),
  });

  const runUndo = async () => {
    if (!undo) return;
    const { ids } = undo;
    setUndo(null);
    try {
      await Promise.all(ids.map((id) => send("DELETE", `/api/maintenance/completions/${id}`)));
      refresh();
    } catch {
      setFailed(true);
    }
  };

  const choose = (person: string) => {
    saveWho(person);
    setWho(person);
  };

  return (
    <main className="home">
      <header>
        <div className="eyebrow">HOUSE / MAINTENANCE</div>
        <h1>What needs doing?</h1>
        <p className="sub">
          <Link to="/">Back to the house</Link> · <a href="/api/maintenance/export">Back up the list</a>
        </p>
      </header>
      {who ? null : (
        <div className="who">
          <span>Who's using this phone?</span>
          {PEOPLE.map((person) => (
            <button key={person} type="button" onClick={() => choose(person)}>
              {person}
            </button>
          ))}
        </div>
      )}
      {failed ? (
        <p className="warn" role="alert">
          Not saved. Check you're on the home Wi-Fi and try again.
        </p>
      ) : null}
      {undo ? (
        <div className="toast" role="status">
          <span>{undo.name} marked done.</span>
          <button type="button" onClick={runUndo}>
            Undo
          </button>
        </div>
      ) : null}
      {message ? (
        <div className="toast" role="status">
          <span>{message}</span>
        </div>
      ) : null}
      {isError ? (
        <p className="warn" role="alert">
          Can't reach the house server
        </p>
      ) : null}
      <div className="tasks">
        {data?.tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            onMark={(mark) => complete.mutate(mark)}
            onInterval={(taskId, months) => interval.mutate({ taskId, months })}
          />
        ))}
      </div>
    </main>
  );
}

"use client";
import { useEffect, useState } from "react";
import { api, money } from "@/lib/api";
import { Protected } from "@/components/protected";

type Goal = {
  id: string;
  name: string;
  target_amount: string | number;
  current_amount?: string | number;
};

export default function Goals() {
  const [rows, setRows] = useState<Goal[]>([]),
    [name, setName] = useState(""),
    [targetAmount, setTargetAmount] = useState(""),
    [selected, setSelected] = useState<Goal | null>(null),
    [editTargetAmount, setEditTargetAmount] = useState(""),
    [deleting, setDeleting] = useState(false),
    [error, setError] = useState("");

  const load = () => api("/goals").then(setRows);

  useEffect(() => {
    void load();
  }, []);

  function open(g: Goal) {
    setSelected(g);
    setEditTargetAmount(String(g.target_amount));
    setDeleting(false);
    setError("");
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    await api("/goals", {
      method: "POST",
      body: JSON.stringify({ name, target_amount: Number(targetAmount) }),
    });
    setName("");
    setTargetAmount("");
    load();
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    try {
      await api(`/goals/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: selected.name,
          target_amount: Number(editTargetAmount),
        }),
      });
      setSelected(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update goal");
    }
  }

  async function remove() {
    if (!selected) return;
    try {
      await api(`/goals/${selected.id}`, { method: "DELETE" });
      setSelected(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete goal");
    }
  }

  return (
    <Protected>
      <h1 className="text-3xl font-bold">Goals</h1>
      <p className="mt-1 text-slate-500">
        Track your savings goals and progress over time.
      </p>

      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {rows.map((g) => (
          <button
            onClick={() => open(g)}
            className="card text-left transition hover:-translate-y-0.5 hover:ring-slate-400 focus:outline-none focus:ring-2 focus:ring-mint"
            key={g.id}
            aria-label={`Edit ${g.name}`}
          >
            <div className="flex justify-between gap-2">
              <p className="label">Goal Target</p>
            </div>
            <p className="mt-2 font-semibold">{g.name}</p>
            <p className="metric mt-3">{money(g.target_amount)}</p>
            <p className="mt-3 text-xs text-slate-400">Click to edit</p>
          </button>
        ))}
      </div>

      <form onSubmit={add} className="card mt-6 flex flex-wrap gap-3">
        <input
          className="rounded border p-2"
          placeholder="Goal name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <input
          className="rounded border p-2"
          type="number"
          step="0.01"
          placeholder="Target amount"
          value={targetAmount}
          onChange={(e) => setTargetAmount(e.target.value)}
          required
        />
        <button className="rounded bg-navy px-4 text-white">Add goal</button>
      </form>

      {selected && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="goal-editor"
        >
          <form
            onSubmit={save}
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="label">Goal</p>
                <h2 id="goal-editor" className="mt-1 text-xl font-bold">
                  Edit goal
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setSelected(null)}
                aria-label="Close editor"
                className="text-xl text-slate-400"
              >
                ×
              </button>
            </div>

            {error && (
              <p className="mt-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
                {error}
              </p>
            )}

            <label className="label mt-5 block">Goal name</label>
            <input
              className="mt-1 w-full rounded border p-2"
              value={selected.name}
              onChange={(e) =>
                setSelected({ ...selected, name: e.target.value })
              }
              required
            />

            <label className="label mt-4 block">Target amount</label>
            <input
              className="mt-1 w-full rounded border p-2"
              type="number"
              step="0.01"
              value={editTargetAmount}
              onChange={(e) => setEditTargetAmount(e.target.value)}
              required
            />

            <div className="mt-6 flex justify-between gap-3">
              <button
                type="button"
                onClick={() => setDeleting(true)}
                className="text-sm font-medium text-red-700"
              >
                Delete goal
              </button>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="rounded border px-4 py-2"
                >
                  Cancel
                </button>
                <button className="rounded bg-navy px-4 py-2 text-white">
                  Save changes
                </button>
              </div>
            </div>

            {deleting && (
              <div className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4">
                <p className="text-sm text-red-800">
                  Delete <b>{selected.name}</b>? This action cannot be undone.
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setDeleting(false)}
                    className="rounded border bg-white px-3 py-2 text-sm"
                  >
                    Keep goal
                  </button>
                  <button
                    type="button"
                    onClick={remove}
                    className="rounded bg-red-700 px-3 py-2 text-sm text-white"
                  >
                    Delete permanently
                  </button>
                </div>
              </div>
            )}
          </form>
        </div>
      )}
    </Protected>
  );
}
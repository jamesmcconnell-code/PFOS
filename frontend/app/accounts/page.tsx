"use client";
import { useEffect, useState } from "react";
import { api, money } from "@/lib/api";
import { Protected } from "@/components/protected";
type Account = {
  id: string;
  name: string;
  type: string;
  balance: string | number;
  source_name: string;
};
export default function Accounts() {
  const [rows, setRows] = useState<Account[]>([]),
    [name, setName] = useState(""),
    [type, setType] = useState("checking"),
    [selected, setSelected] = useState<Account | null>(null),
    [balance, setBalance] = useState(""),
    [deleting, setDeleting] = useState(false),
    [error, setError] = useState("");
  const load = () => api("/accounts").then(setRows);
  useEffect(() => {
    void load();
  }, []);
  function open(a: Account) {
    setSelected(a);
    setBalance(String(a.balance));
    setDeleting(false);
    setError("");
  }
  async function add(e: React.FormEvent) {
    e.preventDefault();
    await api("/accounts", {
      method: "POST",
      body: JSON.stringify({ name, type, balance: 0 }),
    });
    setName("");
    load();
  }
  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    try {
      await api(`/accounts/${selected.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: selected.name,
          type: selected.type,
          balance: Number(balance),
        }),
      });
      setSelected(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update account");
    }
  }
  async function remove() {
    if (!selected) return;
    try {
      await api(`/accounts/${selected.id}`, { method: "DELETE" });
      setSelected(null);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete account");
    }
  }
  return (
    <Protected>
      <h1 className="text-3xl font-bold">Accounts</h1>
      <p className="mt-1 text-slate-500">
        Cash, savings, and credit cards—grouped by source.
      </p>
      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {rows.map((a) => (
          <button
            onClick={() => open(a)}
            className="card text-left transition hover:-translate-y-0.5 hover:ring-slate-400 focus:outline-none focus:ring-2 focus:ring-mint"
            key={a.id}
            aria-label={`Edit ${a.name}`}
          >
            <div className="flex justify-between gap-2">
              <p className="label">{a.type.replace("_", " ")}</p>
              <p className="text-xs text-slate-400">{a.source_name}</p>
            </div>
            <p className="mt-2 font-semibold">{a.name}</p>
            <p className="metric mt-3">{money(a.balance)}</p>
            <p className="mt-3 text-xs text-slate-400">Click to edit</p>
          </button>
        ))}
      </div>
      <form onSubmit={add} className="card mt-6 flex flex-wrap gap-3">
        <input
          className="rounded border p-2"
          placeholder="Account name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <select
          className="rounded border p-2"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option>checking</option>
          <option>savings</option>
          <option>credit_card</option>
        </select>
        <button className="rounded bg-navy px-4 text-white">Add account</button>
      </form>
      {selected && (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="account-editor"
        >
          <form
            onSubmit={save}
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="label">{selected.source_name}</p>
                <h2 id="account-editor" className="mt-1 text-xl font-bold">
                  Edit account
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
            <label className="label mt-5 block">Account name</label>
            <input
              className="mt-1 w-full rounded border p-2"
              value={selected.name}
              onChange={(e) =>
                setSelected({ ...selected, name: e.target.value })
              }
              required
            />
            <label className="label mt-4 block">Account type</label>
            <select
              className="mt-1 w-full rounded border p-2"
              value={selected.type}
              onChange={(e) =>
                setSelected({ ...selected, type: e.target.value })
              }
            >
              <option>checking</option>
              <option>savings</option>
              <option>credit_card</option>
            </select>
            <label className="label mt-4 block">Current balance</label>
            <input
              className="mt-1 w-full rounded border p-2"
              type="number"
              step="0.01"
              value={balance}
              onChange={(e) => setBalance(e.target.value)}
              required
            />
            <div className="mt-6 flex justify-between gap-3">
              <button
                type="button"
                onClick={() => setDeleting(true)}
                className="text-sm font-medium text-red-700"
              >
                Delete account
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
                  Delete <b>{selected.name}</b> and all its local transactions?
                  This cannot be undone. Linked accounts will be excluded from
                  future syncs.
                </p>
                <div className="mt-3 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setDeleting(false)}
                    className="rounded border bg-white px-3 py-2 text-sm"
                  >
                    Keep account
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

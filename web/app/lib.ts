export type Flag = { level: "warning" | "info"; title: string; detail: string };
export type Dash = { income: string; expenses: string; refunds: string; neutral: string; transactions: number; exceptions: number; accounts: number; flags: Flag[] };
export type Tx = {
  id: number; date: string; narration: string; debit: string; credit: string; balance: string | null;
  category: string; category_label: string; group: string; itr_hint: string; category_source: string; note: string | null;
  status: string; match_group: string | null; financial_year: string; account_id: number; account: string; account_kind: string;
  document_id: number; source_row: number;
};
export type Category = { key: string; label: string; group: string; itr_hint: string };
export type Account = { id: number; name: string; kind: string; transactions: number };
export type Doc = { id: number; filename: string; imported_at: string; transactions: number; account: string | null; kind: string | null; from: string | null; to: string | null; warnings: string[] };
export type FileResult = { filename: string; transactions?: number; duplicate?: boolean; needs_password?: boolean; error?: string; message?: string; account?: string; kind?: string; period?: string; warnings?: string[]; document_id?: number; account_id?: number };
export type Year = { financial_year: string; transactions: number };

export const money = (v: string | number | null | undefined) =>
  v === null || v === undefined || v === "" ? "—" : new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(Number(v));

export const amountOf = (t: Tx) => (Number(t.debit) > 0 ? -Number(t.debit) : Number(t.credit));

export const STATUS_LABEL: Record<string, string> = {
  ok: "OK", needs_review: "Needs review", unmatched: "Unmatched", ambiguous: "Ambiguous",
  confirmed_settlement: "Matched", confirmed_transfer: "Matched",
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function makeApi(token: string, onUnauthorized: () => void) {
  const call = async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const res = await fetch(`/api${path}`, { ...init, headers: { Authorization: `Bearer ${token}`, ...(init.body && !(init.body instanceof FormData) ? { "content-type": "application/json" } : {}), ...init.headers } });
    if (res.status === 401) { onUnauthorized(); throw new ApiError(401, "Session expired"); }
    if (!res.ok) {
      let msg = `Request failed (${res.status})`;
      try { const b = await res.json(); msg = typeof b.detail === "string" ? b.detail : msg; } catch {}
      throw new ApiError(res.status, msg);
    }
    return res.headers.get("content-type")?.includes("json") ? res.json() : (res.blob() as unknown as T);
  };
  return {
    get: <T,>(path: string) => call<T>(path),
    post: <T,>(path: string, body?: unknown) => call<T>(path, { method: "POST", body: body instanceof FormData ? body : JSON.stringify(body ?? {}) }),
    patch: <T,>(path: string, body: unknown) => call<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
    del: <T,>(path: string) => call<T>(path, { method: "DELETE" }),
    download: async (path: string, filename: string) => {
      const blob = await call<Blob>(path);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  };
}
export type Api = ReturnType<typeof makeApi>;

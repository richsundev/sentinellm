/**
 * A tiny fetch router for component tests: map "METHOD /path" (the path
 * without the /api/v1 prefix) to a response body, or to a function of the
 * request. Every call is recorded so tests can assert on what the UI sent.
 * Unmocked routes 404 loudly rather than hanging or returning `undefined`.
 */
export interface RecordedCall {
  method: string;
  path: string;
  query: Record<string, string>;
  body: unknown;
  headers: Record<string, string>;
}

/** Return this from a handler to make the mocked endpoint fail. */
export class HttpFailure {
  constructor(
    public status: number,
    public detail: string
  ) {}
}

type Handler =
  | unknown
  | ((call: RecordedCall) => unknown | Promise<unknown>);

export function mockApi(routes: Record<string, Handler>) {
  const calls: RecordedCall[] = [];

  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const call: RecordedCall = {
      method: (init?.method ?? "GET").toUpperCase(),
      path: url.pathname.replace(/^\/api\/v1/, ""),
      query: Object.fromEntries(url.searchParams.entries()),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
      headers: (init?.headers ?? {}) as Record<string, string>,
    };
    calls.push(call);

    const key = `${call.method} ${call.path}`;
    const handler = routes[key];
    const result =
      handler === undefined
        ? new HttpFailure(404, `unmocked route: ${key}`)
        : typeof handler === "function"
          ? await handler(call)
          : handler;

    if (result instanceof HttpFailure) {
      return {
        ok: false,
        status: result.status,
        statusText: "error",
        json: async () => ({ detail: result.detail }),
      } as unknown as Response;
    }
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => result,
      blob: async () => new Blob([String(result)]),
    } as unknown as Response;
  }) as unknown as typeof fetch;

  return {
    calls,
    called: (method: string, path: string) =>
      calls.filter((c) => c.method === method && c.path === path),
  };
}

export function page<T>(items: T[]) {
  return { items, total: items.length, limit: 100, offset: 0 };
}

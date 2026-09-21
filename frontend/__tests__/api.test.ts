import { api, ApiError } from "@/lib/api";
import { HttpFailure, mockApi, page } from "../test-utils/mockApi";

describe("api client", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it("authenticates every request with the API key header", async () => {
    const mock = mockApi({ "GET /traces": page([]) });

    await api.listTraces();

    expect(mock.calls[0].headers["X-API-Key"]).toBeTruthy();
  });

  it("sends filters as query params and drops empty ones", async () => {
    const mock = mockApi({ "GET /traces": page([]) });

    await api.listTraces({ q: "refund", tag: "pii", model: "", provider: undefined, limit: 25 });

    expect(mock.calls[0].query).toEqual({ q: "refund", tag: "pii", limit: "25" });
  });

  it("turns an error response into an ApiError carrying the server's detail", async () => {
    mockApi({ "POST /rollouts": new HttpFailure(409, "already has an active rollout") });

    const failure = await api
      .createRollout({ application_id: "a", incumbent_model: "x", challenger_model: "y" })
      .catch((e) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(409);
    expect(failure.message).toBe("already has an active rollout");
  });

  it("reports an unreachable API as status 0 rather than throwing a raw TypeError", async () => {
    global.fetch = jest.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    const failure = await api.listModels().catch((e) => e);

    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(0);
  });

  it("URL-encodes ids that contain path characters", async () => {
    const mock = mockApi({ "PATCH /models/openai%3Agpt-4o": {} });

    await api.updateModel("openai:gpt-4o", { status_auto: true });

    expect(mock.calls[0].path).toBe("/models/openai%3Agpt-4o");
    expect(mock.calls[0].body).toEqual({ status_auto: true });
  });

  it("posts rollout operator actions without a body", async () => {
    const mock = mockApi({ "POST /rollouts/r1/rollback": {} });

    await api.rollbackRollout("r1");

    expect(mock.calls[0]).toMatchObject({ method: "POST", path: "/rollouts/r1/rollback" });
    expect(mock.calls[0].body).toBeUndefined();
  });

  describe("CSV export", () => {
    function stubDownload() {
      const createObjectURL = jest.fn(() => "blob:traces");
      const revokeObjectURL = jest.fn();
      Object.assign(URL, { createObjectURL, revokeObjectURL });
      const click = jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
      return { createObjectURL, revokeObjectURL, click };
    }

    it("downloads the filtered result set as traces.csv and cleans up the blob URL", async () => {
      const mock = mockApi({ "GET /traces/export": "trace_id,prompt\ntrc_1,hi\n" });
      const dl = stubDownload();
      let downloadName = "";
      dl.click.mockImplementation(function (this: HTMLAnchorElement) {
        downloadName = this.download;
      });

      await api.exportTracesCsv({ tag: "escalation", status: "error" });

      expect(mock.calls[0].query).toEqual({ tag: "escalation", status: "error" });
      expect(downloadName).toBe("traces.csv");
      expect(dl.revokeObjectURL).toHaveBeenCalledWith("blob:traces");
      // The temporary link must not be left in the document.
      expect(document.querySelector("a[download]")).toBeNull();
    });

    it("throws instead of downloading an error page when the export fails", async () => {
      mockApi({ "GET /traces/export": new HttpFailure(403, "forbidden") });
      const dl = stubDownload();

      await expect(api.exportTracesCsv()).rejects.toBeInstanceOf(ApiError);
      expect(dl.click).not.toHaveBeenCalled();
    });
  });
});

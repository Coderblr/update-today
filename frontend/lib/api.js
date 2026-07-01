const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, init) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore non-JSON error body
    }
    throw new Error(detail);
  }
  return response.json();
}

export const api = {
  startCrawl: (payload) =>
    request("/crawl/run", { method: "POST", body: JSON.stringify(payload) }),
  getCrawlRun: (runId) => request(`/crawl/${runId}`),
  listCrawlRuns: () => request("/crawl"),
  getCrawlRunLocators: (runId) => request(`/crawl/${runId}/locators`),
  listAllLocators: (transactionNumber) =>
    request(
      `/crawl/locators/all${transactionNumber ? `?transaction_number=${encodeURIComponent(transactionNumber)}` : ""}`
    ),
  exportUrl: (format, transactionNumber) =>
    `${API_BASE_URL}/crawl/locators/export?format=${format}${
      transactionNumber ? `&transaction_number=${encodeURIComponent(transactionNumber)}` : ""
    }`,

  startExecution: (payload) =>
    request("/execution/run", { method: "POST", body: JSON.stringify(payload) }),
  getExecution: (executionId) => request(`/execution/${executionId}`),
  getExecutionFeatureFiles: (executionId) =>
    request(`/execution/${executionId}/feature-files`),
  getExecutionSteps: (executionId) => request(`/execution/${executionId}/steps`),
  executionReportUrl: (executionId, format) =>
    `${API_BASE_URL}/execution/${executionId}/report?format=${format}`,
  screenshotUrl: (path) => `${API_BASE_URL}/execution/screenshot?path=${encodeURIComponent(path)}`,

  uploadJavaPO: async (file, transactionNumber, screenName) => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("transaction_number", transactionNumber);
    formData.append("screen_name", screenName);
    const response = await fetch(`${API_BASE_URL}/locator-repository/upload-java-po`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `${response.status} ${response.statusText}`);
    }
    return response.json();
  },

  uploadLocatorFiles: async (files) => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    const response = await fetch(`${API_BASE_URL}/locator-repository/upload`, { method: "POST", body: formData });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `${response.status} ${response.statusText}`);
    }
    return response.json();
  },
  getLocatorVersions: (transactionNumber) =>
    request(`/locator-repository/versions?transaction_number=${encodeURIComponent(transactionNumber)}`),
  activateLocatorVersion: (versionId, transactionNumber) =>
    request(
      `/locator-repository/versions/${versionId}/activate?transaction_number=${encodeURIComponent(transactionNumber)}`,
      { method: "POST" }
    ),
  updateLocatorEntry: (entryId, payload) =>
    request(`/locator-repository/entries/${entryId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteLocatorEntry: (entryId) =>
    request(`/locator-repository/entries/${entryId}`, { method: "DELETE" }),
  validateLocatorRepository: (transactionNumber, featureFiles) =>
    request("/locator-repository/validate", {
      method: "POST",
      body: JSON.stringify({ transaction_number: transactionNumber, feature_files: featureFiles }),
    }),
  getLocatorUsageStats: (transactionNumber) =>
    request(`/locator-repository/stats?transaction_number=${encodeURIComponent(transactionNumber)}`),
  mergeLocatorVersions: (transactionNumber, versionIds) =>
    request("/locator-repository/merge", {
      method: "POST",
      body: JSON.stringify({ transaction_number: transactionNumber, version_ids: versionIds }),
    }),

  executionVideoUrl: (executionId) => `${API_BASE_URL}/execution/${executionId}/video`,

  getAnalyticsSummary: () => request("/analytics/summary"),
};

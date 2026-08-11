// Thin fetch wrappers. Every function returns parsed JSON or throws an
// Error carrying the server's detail message.

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body, keep the status message
    }
    throw new Error(detail);
  }
  return response.json();
}

export function uploadJob(formData) {
  return request("/api/jobs", { method: "POST", body: formData });
}

export function getProgress(jobId) {
  return request(`/api/jobs/${jobId}/progress`);
}

export function getJob(jobId) {
  return request(`/api/jobs/${jobId}`);
}

export function getNewSegments(jobId, afterId) {
  return request(`/api/jobs/${jobId}/segments?after_id=${afterId}`);
}

export function getEvents(jobId, afterId) {
  return request(`/api/jobs/${jobId}/events?after_id=${afterId}`);
}

export function flipLabels(jobId, flips) {
  return request(`/api/jobs/${jobId}/segments`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(flips),
  });
}

export function getDemoId() {
  return request("/api/jobs/demo/id");
}

export function downloadUrl(jobId, kind) {
  return `/api/jobs/${jobId}/${kind}`;
}

export function photoUrl(jobId) {
  return `/api/jobs/${jobId}/photo`;
}

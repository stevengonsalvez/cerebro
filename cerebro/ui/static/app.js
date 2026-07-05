const state = {
  lastResult: null,
  selected: null,
};

const el = {
  health: document.querySelector("#healthStatus"),
  form: document.querySelector("#searchForm"),
  query: document.querySelector("#queryInput"),
  limit: document.querySelector("#limitInput"),
  deep: document.querySelector("#deepToggle"),
  mode: document.querySelector("#modeLabel"),
  results: document.querySelector("#resultsList"),
  count: document.querySelector("#resultCount"),
  detail: document.querySelector("#detailBody"),
  openVault: document.querySelector("#openVaultButton"),
  repoSkill: document.querySelector("#repoSkillButton"),
  userSkill: document.querySelector("#userSkillButton"),
  artifact: document.querySelector("#artifactOutput"),
  stageLog: document.querySelector("#stageLog"),
};

const stageNames = [
  "query plan",
  "exact match",
  "source search",
  "repo inspection",
  "builder inspection",
  "ranking",
  "artifact write",
];

el.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await runSearch();
});

el.deep.addEventListener("change", () => {
  el.mode.textContent = el.deep.checked ? "Deep" : "Quick";
});

el.openVault.addEventListener("click", () => {
  const path = vaultPathFor(state.selected);
  if (path) {
    window.open(`file://${path}`, "_blank", "noopener");
  }
});

el.repoSkill.addEventListener("click", async () => {
  const fullName = repoNameFor(state.selected);
  if (!fullName) return;
  await generateSkill("/api/cracked-devs/repo", { full_name: fullName, write: true, dry_run: true });
});

el.userSkill.addEventListener("click", async () => {
  const login = loginFor(state.selected);
  if (!login) return;
  await generateSkill("/api/cracked-devs/user", { login, write: true, dry_run: true });
});

boot();

async function boot() {
  renderStages();
  try {
    const health = await fetchJson("/api/health");
    el.health.textContent = health.ok ? "Ready" : "Degraded";
    el.health.dataset.state = health.ok ? "ready" : "error";
  } catch (error) {
    el.health.textContent = "Offline";
    el.health.dataset.state = "error";
  }
}

async function runSearch() {
  const payload = {
    query: el.query.value.trim(),
    target: document.querySelector('input[name="target"]:checked').value,
    limit: Number(el.limit.value || 10),
    deep: el.deep.checked,
  };
  if (!payload.query) return;

  setBusy(true);
  renderStages("running");
  el.artifact.textContent = "";

  try {
    const result = await fetchJson("/api/git-search", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.lastResult = result;
    const candidates = candidatesFrom(result);
    state.selected = candidates[0] || null;
    renderResults(candidates);
    renderDetail(state.selected);
    renderStages("done", result);
  } catch (error) {
    state.lastResult = null;
    state.selected = null;
    renderResults([]);
    renderDetail(null, error.message);
    renderStages("error");
  } finally {
    setBusy(false);
  }
}

async function generateSkill(url, payload) {
  el.artifact.textContent = "Generating";
  try {
    const result = await fetchJson(url, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    el.artifact.innerHTML = renderArtifact(result);
  } catch (error) {
    el.artifact.textContent = error.message;
  }
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "Request failed");
  }
  return data;
}

function candidatesFrom(result) {
  if (!result) return [];
  if (Array.isArray(result.candidates)) return result.candidates;
  if (Array.isArray(result.repositories)) return result.repositories;
  if (Array.isArray(result.results)) return result.results;
  if (Array.isArray(result.items)) return result.items;
  return [];
}

function renderResults(candidates) {
  el.count.textContent = String(candidates.length);
  el.results.innerHTML = "";

  if (!candidates.length) {
    el.results.innerHTML = '<p class="muted">No results.</p>';
    return;
  }

  candidates.forEach((candidate, index) => {
    const button = document.createElement("button");
    button.className = "result-card";
    button.type = "button";
    button.dataset.active = candidate === state.selected ? "true" : "false";
    button.innerHTML = `
      <span class="result-title">${escapeHtml(displayName(candidate))}</span>
      <span class="result-meta">${escapeHtml(metaLine(candidate))}</span>
      <span class="result-reason">${escapeHtml(candidate.reason || candidate.description || "")}</span>
    `;
    button.addEventListener("click", () => {
      state.selected = candidate;
      renderResults(candidates);
      renderDetail(candidate);
    });
    if (index === 0 && !state.selected) state.selected = candidate;
    el.results.appendChild(button);
  });
}

function renderDetail(candidate, message = "") {
  el.openVault.disabled = !vaultPathFor(candidate);
  el.repoSkill.disabled = !repoNameFor(candidate);
  el.userSkill.disabled = !loginFor(candidate);

  if (!candidate) {
    el.detail.innerHTML = `<p class="muted">${escapeHtml(message || "Select result.")}</p>`;
    return;
  }

  const topics = Array.isArray(candidate.topics) ? candidate.topics : [];
  el.detail.innerHTML = `
    <h3>${escapeHtml(displayName(candidate))}</h3>
    <p>${escapeHtml(candidate.description || candidate.bio || "No description.")}</p>
    <dl>
      <div><dt>Score</dt><dd>${escapeHtml(scoreFor(candidate))}</dd></div>
      <div><dt>Stars</dt><dd>${escapeHtml(String(candidate.stars ?? candidate.stargazers_count ?? "-"))}</dd></div>
      <div><dt>Language</dt><dd>${escapeHtml(candidate.language || "-")}</dd></div>
      <div><dt>Updated</dt><dd>${escapeHtml(candidate.updated_at || candidate.pushed_at || "-")}</dd></div>
    </dl>
    <div class="badge-row">${topics.map((topic) => `<span>${escapeHtml(topic)}</span>`).join("")}</div>
  `;
}

function renderStages(status = "idle", result = null) {
  const resultStages = Array.isArray(result?.stages) ? result.stages : [];
  const stages = resultStages.length ? resultStages : stageNames;
  el.stageLog.innerHTML = stages
    .map((stage, index) => {
      const name = typeof stage === "string" ? stage : stage.name || stage.stage || `stage_${index + 1}`;
      const stateName = status === "done" ? "done" : status === "error" ? "error" : index === 0 && status === "running" ? "running" : "idle";
      return `<li data-state="${stateName}"><span>${escapeHtml(stageLabel(name))}</span></li>`;
    })
    .join("");
}

function stageLabel(name) {
  const labels = {
    query_plan: "query plan",
    exact_lookup: "exact match",
    github_search: "source search",
    repo_inspection: "repo inspection",
    profile_inspection: "builder inspection",
    artifact_write: "artifact write",
  };
  return labels[name] || String(name).replaceAll("_", " ");
}

function renderArtifact(result) {
  const path = result?.path || result?.artifact_path || result?.skill_path || result?.skill || result?.bundle_path || result?.bundle || "";
  const name = result?.name || result?.full_name || result?.login || "Cerebro artifact";
  const link = path ? `<a href="file://${escapeHtml(path)}" target="_blank" rel="noopener">${escapeHtml(path)}</a>` : "";
  const scan = result?.scan?.ok ? '<span class="artifact-ok">scan ok</span>' : "";
  return `<strong>${escapeHtml(name)}</strong>${link}${scan}`;
}

function setBusy(isBusy) {
  el.form.dataset.busy = String(isBusy);
  el.form.querySelector("button[type='submit']").disabled = isBusy;
}

function displayName(candidate) {
  return candidate?.full_name || candidate?.login || candidate?.name || candidate?.title || "Unknown";
}

function metaLine(candidate) {
  const parts = [];
  if (candidate?.type) parts.push(candidate.type);
  if (candidate?.language) parts.push(candidate.language);
  const stars = candidate?.stars ?? candidate?.stargazers_count;
  if (stars !== undefined) parts.push(`${stars} stars`);
  return parts.join(" / ") || "candidate";
}

function scoreFor(candidate) {
  const score = candidate?.score ?? candidate?.semantic_score ?? candidate?.activity_score;
  return score === undefined ? "-" : String(score);
}

function repoNameFor(candidate) {
  return candidate?.full_name || candidate?.repo?.full_name || "";
}

function loginFor(candidate) {
  if (candidate?.login) return candidate.login;
  if (candidate?.owner?.login) return candidate.owner.login;
  if (candidate?.full_name && candidate.full_name.includes("/")) return candidate.full_name.split("/")[0];
  return "";
}

function vaultPathFor(candidate) {
  return candidate?.vault_path || candidate?.artifact_path || candidate?.path || candidate?.bundle || "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

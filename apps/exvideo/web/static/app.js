const API = "/api/exvideo";
const $ = (id) => document.getElementById(id);
let pollTimer = null;
let currentJob = null;

async function startJob() {
  const source = $("source").value.trim();
  if (!source) { alert("영상 주소를 입력하세요."); return; }
  const body = {
    source,
    transcribe: $("transcribe").checked,
    ocr: $("ocr").checked,
    figures: $("figures").checked,
    model: $("model").value,
  };
  $("startBtn").disabled = true;
  const res = await fetch(`${API}/jobs`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) { alert("작업 시작 실패"); $("startBtn").disabled = false; return; }
  const { job_id } = await res.json();
  currentJob = job_id;
  $("progressCard").classList.remove("hidden");
  $("doneBtns").classList.add("hidden");
  $("previewCard").classList.add("hidden");
  poll();
}

async function poll() {
  if (!currentJob) return;
  const res = await fetch(`${API}/jobs/${currentJob}`);
  const j = await res.json();
  $("barFill").style.width = (j.progress || 0) + "%";
  $("statusText").textContent = `상태: ${statusKo(j.status)} (${j.progress || 0}%)`;
  $("log").textContent = (j.messages || []).join("\n");
  $("log").scrollTop = $("log").scrollHeight;

  if (j.status === "done") {
    $("statusText").textContent = `완료! 슬라이드 ${j.result?.n_slides ?? "?"}개`;
    $("doneBtns").classList.remove("hidden");
    loadPreview();
    return;
  }
  if (j.status === "error") {
    $("statusText").textContent = "오류: " + (j.error || "알 수 없음");
    $("startBtn").disabled = false;
    return;
  }
  pollTimer = setTimeout(poll, 1500);
}

function statusKo(s) {
  return { queued: "대기 중", running: "처리 중", done: "완료", error: "오류" }[s] || s;
}

async function loadPreview() {
  try {
    const res = await fetch(`${API}/jobs/${currentJob}/bundle`);
    const txt = await res.text();
    $("preview").textContent = txt;
    $("previewCard").classList.remove("hidden");
  } catch (e) { /* ignore */ }
}

// ─────────────────────────── 요약정리본 ───────────────────────────

let sourceId = null;

async function notesJob(jobId, label) {
  $("notesProgress").classList.remove("hidden");
  for (;;) {
    const j = await (await fetch(`${API}/notes/jobs/${jobId}`)).json();
    $("nBar").style.width = (j.progress || 0) + "%";
    $("nStatus").textContent = `${label}: ${statusKo(j.status)} (${j.progress || 0}%)`;
    $("nLog").textContent = (j.messages || []).join("\n");
    $("nLog").scrollTop = $("nLog").scrollHeight;
    if (j.status === "done") return j.result;
    if (j.status === "error") { alert(`${label} 실패: ${j.error}`); return null; }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

async function createSource() {
  const fd = new FormData();
  fd.append("title", $("nTitle").value.trim());
  fd.append("job_id", $("nJobId").value.trim());
  fd.append("transcript", $("nTranscript").value.trim());
  const file = $("nPdf").files[0];
  if (file) fd.append("pdf", file);
  if (!file && !$("nJobId").value.trim() && !$("nTranscript").value.trim()) {
    alert("강의자료 PDF 나 전사 중 하나는 있어야 합니다.");
    return;
  }

  $("nCreateBtn").disabled = true;
  try {
    const res = await fetch(`${API}/notes/sources`, { method: "POST", body: fd });
    if (!res.ok) { alert("업로드 실패: " + (await res.text())); return; }
    sourceId = (await res.json()).source_id;

    const { job_id } = await (await fetch(`${API}/notes/sources/${sourceId}/index`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    })).json();
    // 색인은 원본 전체를 읽으므로 한 번뿐이고 제일 오래 걸린다
    if (await notesJob(job_id, "색인")) await showIndex();
  } finally {
    $("nCreateBtn").disabled = false;
  }
}

async function showIndex() {
  const body = await (await fetch(`${API}/notes/sources/${sourceId}`)).json();
  const idx = body.index;
  const used = body.usage.find((u) => u.stage === "index") || {};
  $("nIndexInfo").innerHTML =
    `색인 v${idx.version} · 섹션 ${idx.sections.length}개 · ` +
    `${idx.provider.name}/${idx.provider.model} · ` +
    `입력 ${used.input_tokens ?? "?"}토큰 (이 비용은 한 번만 듭니다)`;

  const parts = await (await fetch(`${API}/notes/parts`)).json();
  $("nParts").innerHTML = parts.map((p, i) =>
    `<label title="${p.desc}"><input type="checkbox" value="${p.id}"` +
    `${i < 3 ? " checked" : ""} /> ${p.name}</label>`).join("");

  $("nSections").innerHTML = idx.sections.map((s) => {
    const where = [s.pages.length ? `p.${s.pages[0]}` : "", s.time_start].filter(Boolean);
    return `<option value="${s.id}">${s.title} ${where.length ? `(${where.join(", ")})` : ""}</option>`;
  }).join("");

  await loadProviders();
  $("notesBuild").classList.remove("hidden");
  renderOutputs(body.outputs);
}

// 정리본을 만들 모델 고르기. 못 쓰는 것도 이유와 함께 남겨 둔다 —
// 목록에서 그냥 사라지면 "왜 클로드가 없지" 하고 헤매게 된다.
async function loadProviders() {
  const sel = $("nProvider");
  if (sel.options.length) return;
  const list = await (await fetch(`${API}/notes/providers`)).json();
  sel.innerHTML = list.map((p) =>
    `<option value="${p.id}"${p.ready ? "" : " disabled"}>` +
    `${p.label}${p.model ? ` · ${p.model}` : ""}${p.ready ? "" : ` — ${p.reason}`}</option>`
  ).join("");
  const preferred = list.find((p) => p.ready && p.id === "claude-cli")
    || list.find((p) => p.ready);
  if (preferred) sel.value = preferred.id;
}

async function renderNotes() {
  const parts = [...$("nParts").querySelectorAll("input:checked")].map((c) => c.value);
  const outline = $("nOutline").value.trim();
  // 구성을 직접 적었으면 체크박스는 안 골라도 된다.
  if (!parts.length && !outline) { alert("구성을 고르거나 직접 적으세요."); return; }
  const sections = [...$("nSections").selectedOptions].map((o) => o.value);

  $("nRenderBtn").disabled = true;
  try {
    const { job_id } = await (await fetch(`${API}/notes/sources/${sourceId}/render`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parts,
        sections: sections.length ? sections : null,
        raw_sections: $("nRaw").checked && sections.length ? sections : null,
        note: $("nNote").value.trim(),
        provider: $("nProvider").value || null,
        outline,
        design: {
          scale: Number($("dScale").value),
          line: Number($("dLine").value),
          margin: Number($("dMargin").value),
          accent: $("dAccent").value,
        },
      }),
    })).json();
    if (await notesJob(job_id, "정리본")) {
      const body = await (await fetch(`${API}/notes/sources/${sourceId}`)).json();
      renderOutputs(body.outputs);
    }
  } finally {
    $("nRenderBtn").disabled = false;
  }
}

function renderOutputs(outputs) {
  if (!outputs || !outputs.length) return;
  $("nOutputs").classList.remove("hidden");
  $("nOutputs").innerHTML = outputs.map((o) => {
    const warn = (o.foreign_ratio > 0.05
      ? ` ⚠ 한국어 이탈 ${Math.round(o.foreign_ratio * 100)}%` : "")
      + (o.chunks > 1 ? ` ⚠ ${o.chunks}조각으로 이어 씀 (이은 자리 확인 필요)` : "");
    return `<div><a href="${API}/notes/sources/${sourceId}/outputs/${o.render_id}.pdf"` +
      ` target="_blank">${o.render_id}.pdf</a> — ${o.parts.join(", ")}` +
      ` · ${o.provider || "?"} · 입력 ${o.input_tokens}토큰${warn}</div>`;
  }).join("");
}

$("nCreateBtn").addEventListener("click", createSource);
$("nRenderBtn").addEventListener("click", renderNotes);

$("startBtn").addEventListener("click", startJob);
$("dlZip").addEventListener("click", () => { window.location = `${API}/jobs/${currentJob}/download`; });
$("dlBundle").addEventListener("click", () => { window.open(`${API}/jobs/${currentJob}/bundle`, "_blank"); });
$("againBtn").addEventListener("click", () => {
  if (pollTimer) clearTimeout(pollTimer);
  currentJob = null;
  $("startBtn").disabled = false;
  $("progressCard").classList.add("hidden");
  $("previewCard").classList.add("hidden");
});

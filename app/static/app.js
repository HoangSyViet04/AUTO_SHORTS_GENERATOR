const state = {
  config: null,
  videos: [],
  selected: null,
  job: null,
  keepLogs: true,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const ui = {
  geminiStatus: $("#geminiStatus"),
  ttsStatus: $("#ttsStatus"),
  refreshBtn: $("#refreshBtn"),
  uploadInput: $("#uploadInput"),
  videoList: $("#videoList"),
  selectedVideoName: $("#selectedVideoName"),
  runBtn: $("#runBtn"),
  jobStatus: $("#jobStatus"),
  videoCount: $("#videoCount"),
  doneCount: $("#doneCount"),
  outputDir: $("#outputDir"),
  outputStatus: $("#outputStatus"),
  outputList: $("#outputList"),
  optionsForm: $("#optionsForm"),
  saveOptionsBtn: $("#saveOptionsBtn"),
  clearLogsBtn: $("#clearLogsBtn"),
  logBox: $("#logBox"),
};

function bytes(value) {
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(value || 0);
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return index === 0 ? `${size} ${units[index]}` : `${size.toFixed(1)} ${units[index]}`;
}

function dateTime(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(typeof payload === "string" ? payload : payload.detail || `HTTP ${response.status}`);
  }
  return payload;
}

function chip(element, ok, okText, badText) {
  element.textContent = ok ? okText : badText;
  element.classList.toggle("ok", ok);
  element.classList.toggle("bad", !ok);
}

function markStep(stepName) {
  const order = ["video", "stt", "translate", "tts", "done"];
  const currentIndex = order.indexOf(stepName);
  $$(".flow-node").forEach((node) => {
    const index = order.indexOf(node.dataset.step);
    node.classList.toggle("active", index === currentIndex);
    node.classList.toggle("done", currentIndex >= 0 && index < currentIndex);
  });
}

function inferStep(logs) {
  const joined = logs.join("\n");
  if (joined.includes("Da luu audio long tieng") || joined.includes("Hoan tat")) return "done";
  if (joined.includes("Dang tao audio caption")) return "tts";
  if (joined.includes("Dang dich subtitle") || joined.includes("Dang dich SRT")) return "translate";
  if (joined.includes("Whisper") || joined.includes("subtitle tieng Trung")) return "stt";
  return "video";
}

function setFormValue(name, value) {
  const field = ui.optionsForm.elements[name];
  if (!field) return;
  field.value = Array.isArray(value) ? value.join(",") : value ?? "";
}

function renderConfig() {
  const config = state.config;
  if (!config) return;

  chip(ui.geminiStatus, config.api.gemini, "Gemini OK", "Thiếu Gemini");
  chip(ui.ttsStatus, config.api.tts, "TTS OK", "Thiếu TTS");
  ui.outputDir.textContent = config.paths.output;

  const settings = config.settings;
  setFormValue("whisperModel", settings.whisperModel);
  setFormValue("whisperDevice", settings.whisperDevice);
  setFormValue("whisperComputeType", settings.whisperComputeType);
  setFormValue("whisperFallbackModels", settings.whisperFallbackModels);
  setFormValue("geminiModel", settings.geminiModel);
  setFormValue("ttsApiUrl", settings.ttsApiUrl);
  setFormValue("ttsVoiceId", settings.ttsVoiceId);
  setFormValue("ttsModelId", settings.ttsModelId);
  setFormValue("ttsTimeoutSeconds", settings.ttsTimeoutSeconds);
  setFormValue("ttsMaxRetries", settings.ttsMaxRetries);
  setFormValue("maxAudioSpeedupRatio", settings.maxAudioSpeedupRatio);
}

function renderVideos() {
  ui.videoCount.textContent = state.videos.length;
  ui.doneCount.textContent = state.videos.filter((video) => video.status === "done").length;

  if (!state.videos.length) {
    state.selected = null;
    ui.selectedVideoName.textContent = "Chưa chọn video";
    ui.videoList.innerHTML = `<div class="empty">Upload video .mp4 hoặc .mkv để bắt đầu.</div>`;
    ui.runBtn.disabled = true;
    renderOutputs();
    return;
  }

  if (!state.selected || !state.videos.some((video) => video.name === state.selected.name)) {
    state.selected = state.videos[0];
  }

  ui.videoList.innerHTML = state.videos
    .map((video) => {
      const selected = state.selected?.name === video.name;
      const done = video.status === "done";
      return `
        <button class="video-card ${selected ? "selected" : ""}" data-name="${video.name}">
          <span class="file-mark">MP4</span>
          <span>
            <strong>${video.name}</strong>
            <small>${bytes(video.size)} · ${dateTime(video.modified)}</small>
          </span>
          <span class="state-badge ${done ? "done" : ""}">${done ? "Đủ file" : "Chờ chạy"}</span>
        </button>
      `;
    })
    .join("");

  $$(".video-card").forEach((button) => {
    button.addEventListener("click", () => {
      state.selected = state.videos.find((video) => video.name === button.dataset.name);
      renderVideos();
    });
  });

  ui.selectedVideoName.textContent = state.selected.name;
  ui.runBtn.disabled = Boolean(state.job?.running);
  renderOutputs();
}

function renderOutputs() {
  const selected = state.selected;
  if (!selected) {
    ui.outputStatus.textContent = "Đang chờ";
    ui.outputStatus.className = "run-status";
    ui.outputList.innerHTML = `<div class="empty">Chọn video để xem output.</div>`;
    return;
  }

  const complete = selected.complete.video && selected.complete.subtitle && selected.complete.audio;
  ui.outputStatus.textContent = complete ? "Hoàn thành" : "Chưa đủ";
  ui.outputStatus.className = `run-status ${complete ? "ok" : "bad"}`;

  if (!selected.outputs.length) {
    ui.outputList.innerHTML = `<div class="empty">Chưa có output cho video này.</div>`;
    return;
  }

  ui.outputList.innerHTML = selected.outputs
    .map((file) => {
      const isAudio = file.name.endsWith(".mp3");
      const isSubtitle = file.name.endsWith(".srt");
      const mark = isAudio ? "MP3" : isSubtitle ? "SRT" : "MP4";
      const color = isAudio ? "yellow" : isSubtitle ? "green" : "";
      return `
        <div class="output-card">
          <span class="file-mark ${color}">${mark}</span>
          <span>
            <strong>${file.name}</strong>
            <small>${bytes(file.size)}</small>
          </span>
          <a class="state-badge done" href="${file.url}" target="_blank" rel="noreferrer">Mở</a>
        </div>
      `;
    })
    .join("");
}

function renderJob(job) {
  state.job = job;
  if (job.running) {
    ui.jobStatus.textContent = `Đang chạy ${job.currentVideo || ""}`;
    ui.jobStatus.className = "run-status";
  } else if (job.error) {
    ui.jobStatus.textContent = "Có lỗi";
    ui.jobStatus.className = "run-status bad";
  } else {
    ui.jobStatus.textContent = "Sẵn sàng";
    ui.jobStatus.className = "run-status ok";
  }

  markStep(inferStep(job.logs || []));
  if (state.keepLogs) {
    ui.logBox.textContent = job.logs?.length ? job.logs.join("\n") : "Chưa có log.";
    ui.logBox.scrollTop = ui.logBox.scrollHeight;
  }
  ui.runBtn.disabled = job.running || !state.selected;
}

function formPayload() {
  const form = new FormData(ui.optionsForm);
  return {
    whisperModel: form.get("whisperModel"),
    whisperDevice: form.get("whisperDevice"),
    whisperComputeType: form.get("whisperComputeType"),
    whisperFallbackModels: form.get("whisperFallbackModels"),
    geminiModel: form.get("geminiModel"),
    ttsApiUrl: form.get("ttsApiUrl"),
    ttsVoiceId: form.get("ttsVoiceId"),
    ttsModelId: form.get("ttsModelId"),
    ttsTimeoutSeconds: Number(form.get("ttsTimeoutSeconds")),
    ttsMaxRetries: Number(form.get("ttsMaxRetries")),
    maxAudioSpeedupRatio: Number(form.get("maxAudioSpeedupRatio")),
  };
}

async function loadConfig() {
  state.config = await api("/api/config");
  renderConfig();
}

async function loadVideos() {
  const payload = await api("/api/videos");
  state.videos = payload.videos;
  renderVideos();
}

async function loadJob() {
  const job = await api("/api/job");
  renderJob(job);
  if (!job.running) {
    await loadVideos();
  }
}

async function saveOptions() {
  ui.saveOptionsBtn.disabled = true;
  try {
    state.config = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(formPayload()),
    });
    renderConfig();
    ui.saveOptionsBtn.textContent = "Đã lưu";
    window.setTimeout(() => {
      ui.saveOptionsBtn.textContent = "Lưu .env";
    }, 1400);
  } catch (error) {
    alert(error.message);
  } finally {
    ui.saveOptionsBtn.disabled = false;
  }
}

async function uploadVideo(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  ui.uploadInput.disabled = true;
  try {
    await api("/api/upload", { method: "POST", body: form });
    await loadVideos();
  } catch (error) {
    alert(error.message);
  } finally {
    ui.uploadInput.value = "";
    ui.uploadInput.disabled = false;
  }
}

async function runPipeline() {
  if (!state.selected) return;
  state.keepLogs = true;
  ui.logBox.textContent = "Đang khởi động pipeline...";
  try {
    const job = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videos: [state.selected.name] }),
    });
    renderJob(job);
  } catch (error) {
    alert(error.message);
  }
}

function wireEvents() {
  ui.refreshBtn.addEventListener("click", async () => {
    await loadConfig();
    await loadVideos();
    await loadJob();
  });
  ui.uploadInput.addEventListener("change", (event) => uploadVideo(event.target.files?.[0]));
  ui.runBtn.addEventListener("click", runPipeline);
  ui.saveOptionsBtn.addEventListener("click", saveOptions);
  ui.clearLogsBtn.addEventListener("click", () => {
    state.keepLogs = false;
    ui.logBox.textContent = "Đã xóa log hiển thị. Log nền vẫn tiếp tục chạy.";
  });
  $$(".rail-button").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".rail-button").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      $(`#${button.dataset.target}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  });
}

async function boot() {
  wireEvents();
  await loadConfig();
  await loadVideos();
  await loadJob();
  window.setInterval(loadJob, 2500);
}

boot().catch((error) => {
  ui.logBox.textContent = error.stack || error.message;
});

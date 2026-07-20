const state = {
  config: null,
  videos: [],
  selected: null,
  job: null,
  keepLogs: true,
  lastJobRunning: null,
  lastRenderedAudioUrl: "",
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const ui = {
  uploadInput: $("#uploadInput"),
  outputList: $("#outputList"),
  outputStatus: $("#outputStatus"),
  runBtn: $("#runBtn"),
  refreshBtn: $("#refreshBtn"),
  saveOptionsBtn: $("#saveOptionsBtn"),
  clearSelectionBtn: $("#clearSelectionBtn"),
  copyCampaignBtn: $("#copyCampaignBtn"),
  copyShopeeBtn: $("#copyShopeeBtn"),
  clearLogsBtn: $("#clearLogsBtn"),
  optionsForm: $("#optionsForm"),
  logBox: $("#logBox"),
  openOutputBtn: $("#openOutputBtn"),
  dropZone: $("#dropZone"),
  subtitlePreview: $("#subtitlePreview"),
  campaignPreview: $("#campaignPreview"),
  shopeePreview: $("#shopeePreview"),
  audioPreview: $("#audioPreview"),
  videoSelect: $("#videoSelect"),
  capcutBtn: $("#capcutBtn"),
};

const workflowSteps = ["import", "srt", "gemini", "tts", "capcut"];
const workflowLabels = {
  ready: "Chờ xử lý",
  running: "Đang xử lý...",
  done: "Hoàn thành",
  capcutReady: "Sẵn sàng mở",
  error: "Có lỗi",
};

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = Number(bytes || 0);
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return index === 0 ? `${value} ${units[index]}` : `${value.toFixed(1)} ${units[index]}`;
}

function formatDate(value) {
  if (!value) return "-";
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
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    throw new Error(typeof payload === "string" ? payload : payload.detail || `HTTP ${response.status}`);
  }
  return payload;
}

function showView(name) {
  $$(".view").forEach((view) => view.classList.remove("active"));
  $(`#${name}View`)?.classList.add("active");
  $$(".nav-item[data-view]").forEach((item) => item.classList.toggle("active", item.dataset.view === name));
}

function setWorkflowState(currentStep = "import", mode = "ready") {
  const currentIndex = workflowSteps.indexOf(currentStep);
  $$(".workflow-card").forEach((card) => {
    const step = card.dataset.step;
    const index = workflowSteps.indexOf(step);
    const status = card.querySelector(".step-status");
    card.classList.remove("done", "active", "error");

    if (mode === "error" && index === currentIndex) {
      card.classList.add("error");
      if (status) status.textContent = workflowLabels.error;
      return;
    }

    if (mode === "complete") {
      if (step === "capcut") {
        card.classList.add("active");
        if (status) status.textContent = workflowLabels.capcutReady;
      } else {
        card.classList.add("done");
        if (status) status.textContent = workflowLabels.done;
      }
      return;
    }

    if (index < currentIndex) {
      card.classList.add("done");
      if (status) status.textContent = workflowLabels.done;
    } else if (index === currentIndex) {
      card.classList.add("active");
      if (status) status.textContent = mode === "running" ? workflowLabels.running : workflowLabels.ready;
    } else if (status) {
      status.textContent = workflowLabels.ready;
    }
  });
}

function inferWorkflowStep(logs = []) {
  const text = logs.join("\n");
  if (text.includes("Dang tao audio caption") || text.includes("Da luu sub Viet")) return "tts";
  if (text.includes("Dang dich") || text.includes("Da luu sub Trung")) return "gemini";
  if (text.includes("Whisper") || text.includes("trich xuat subtitle")) return "srt";
  if (text.includes("Da copy video goc") || text.includes("Bat dau xu ly")) return "import";
  return "import";
}

function setFormValue(name, value) {
  const field = ui.optionsForm.elements[name];
  if (!field) return;
  field.value = Array.isArray(value) ? value.join(",") : value ?? "";
}

function applyConfigToForm() {
  const settings = state.config?.settings;
  if (!settings) return;
  setFormValue("whisperModel", settings.whisperModel);
  setFormValue("whisperDevice", settings.whisperDevice);
  setFormValue("whisperComputeType", settings.whisperComputeType);
  setFormValue("whisperFallbackModels", settings.whisperFallbackModels);
  setFormValue("geminiModel", settings.geminiModel);
  setFormValue("geminiRewritePrompt", settings.geminiRewritePrompt);
  setFormValue("geminiPostPrompt", settings.geminiPostPrompt);
  setFormValue("shopeeProductPrompt", settings.shopeeProductPrompt);
  setFormValue("ttsApiUrl", settings.ttsApiUrl);
  setFormValue("ttsVoiceId", settings.ttsVoiceId);
  setFormValue("ttsModelId", settings.ttsModelId);
  setFormValue("ttsTimeoutSeconds", settings.ttsTimeoutSeconds);
  setFormValue("ttsMaxRetries", settings.ttsMaxRetries);
  setFormValue("maxAudioSpeedupRatio", settings.maxAudioSpeedupRatio);
  setFormValue("capcutPath", settings.capcutPath);
  setFormValue("capcutProjectDir", settings.capcutProjectDir);
}

function selectedOutput(name) {
  return state.selected?.outputs?.find((file) => file.name === name);
}

function outputByExtension(extension) {
  return state.selected?.outputs?.find((file) => file.name.toLowerCase().endsWith(extension));
}

async function copyBoxText(previewElement, buttonElement) {
  const text = previewElement.textContent.trim();
  if (!text || buttonElement.disabled) return;
  await navigator.clipboard.writeText(text);
  buttonElement.textContent = "Đã copy";
  setTimeout(() => {
    buttonElement.textContent = "Copy";
  }, 1200);
}

async function renderPreviews() {
  if (!state.selected) {
    if (state.lastRenderedAudioUrl) {
      ui.audioPreview.innerHTML = "Chua co audio preview.";
      state.lastRenderedAudioUrl = "";
    }
    ui.subtitlePreview.textContent = "Chọn video để xem SRT.";
    ui.campaignPreview.textContent = "Chọn video đã chạy xong để xem caption đăng bài.";
    ui.shopeePreview.textContent = "Chọn video đã chạy xong để xem gợi ý comment.";
    ui.copyCampaignBtn.disabled = true;
    ui.copyShopeeBtn.disabled = true;
    return;
  }

  const subtitle = selectedOutput("sub_viet.srt");
  const campaign = selectedOutput("chien_dich_dang_bai.txt");
  const shopee = selectedOutput("shopee_links.txt");
  const audio = selectedOutput("giong_doc_viet.mp3");
  const audioUrl = audio?.url || "";

  if (state.lastRenderedAudioUrl !== audioUrl) {
    ui.audioPreview.innerHTML = audio
      ? `<audio controls src="${audio.url}"></audio>`
      : "Chua co audio preview.";
    state.lastRenderedAudioUrl = audioUrl;
  }

  if (subtitle) {
    try {
      const text = await fetch(subtitle.url).then((response) => response.text());
      ui.subtitlePreview.textContent = text.split("\n\n").slice(0, 4).join("\n\n");
    } catch {
      ui.subtitlePreview.textContent = "Khong doc duoc file SRT.";
    }
  } else {
    ui.subtitlePreview.textContent = "Chua co file SRT.";
  }

  if (campaign) {
    try {
      ui.campaignPreview.textContent = await fetch(campaign.url).then((response) => response.text());
      ui.copyCampaignBtn.disabled = false;
    } catch {
      ui.campaignPreview.textContent = "Không đọc được file caption.";
      ui.copyCampaignBtn.disabled = true;
    }
  } else {
    ui.campaignPreview.textContent = "Chưa có caption. Chạy pipeline để tạo caption và hashtag.";
    ui.copyCampaignBtn.disabled = true;
  }

  if (shopee) {
    try {
      ui.shopeePreview.textContent = await fetch(shopee.url).then((response) => response.text());
      ui.copyShopeeBtn.disabled = false;
    } catch {
      ui.shopeePreview.textContent = "Không đọc được file gợi ý comment.";
      ui.copyShopeeBtn.disabled = true;
    }
  } else {
    ui.shopeePreview.textContent = "Chưa có gợi ý comment. Chạy pipeline để tạo nội dung.";
    ui.copyShopeeBtn.disabled = true;
  }
}

function renderOutputs() {
  const video = state.selected;
  if (!video) {
    ui.outputStatus.textContent = "Đang chờ";
    ui.outputList.innerHTML = `<div class="empty">Upload hoặc chọn video để xem output.</div>`;
    ui.runBtn.disabled = true;
    ui.capcutBtn.disabled = true;
    setWorkflowState("import", "ready");
    renderPreviews();
    return;
  }

  const complete = video.complete.video && video.complete.subtitle && video.complete.audio && video.complete.logo;
  const readyCount = ["video", "subtitle", "audio", "logo"].filter((key) => video.complete[key]).length;
  ui.outputStatus.textContent = complete ? "4/4 file đã sẵn sàng" : `${readyCount}/4 file đã sẵn sàng`;
  setWorkflowState(complete ? "capcut" : "import", complete ? "complete" : "ready");
  ui.runBtn.disabled = Boolean(state.job?.running);
  ui.capcutBtn.disabled = !complete || Boolean(state.job?.running);

  if (!video.outputs.length) {
    ui.outputList.innerHTML = `<div class="empty">Video này chưa có output. Bấm Run all để chạy.</div>`;
    renderPreviews();
    return;
  }

  const outputPriority = { "video_goc": 1, "sub_viet.srt": 2, "giong_doc_viet.mp3": 3, "logo.png": 4, "chien_dich_dang_bai.txt": 5, "shopee_links.txt": 6 };
  const sortedOutputs = [...video.outputs].sort((left, right) => {
    const leftKey = Object.keys(outputPriority).find((key) => left.name.toLowerCase().startsWith(key));
    const rightKey = Object.keys(outputPriority).find((key) => right.name.toLowerCase().startsWith(key));
    return (outputPriority[leftKey] || 99) - (outputPriority[rightKey] || 99) || left.name.localeCompare(right.name);
  });

  ui.outputList.innerHTML = sortedOutputs
    .map((file) => {
      const lower = file.name.toLowerCase();
      const label = lower.endsWith(".srt") ? "SRT" : lower.endsWith(".mp3") ? "MP3" : lower.endsWith(".png") ? "PNG" : lower.endsWith(".txt") ? "TXT" : "MP4";
      return `
        <div class="file-row ${lower.endsWith(".png") ? "logo-file" : ""}">
          <span class="file-icon">${label}</span>
          <span>
            <strong>${file.name}</strong>
            <small>${formatBytes(file.size)}</small>
          </span>
          <a class="outline-button" href="${file.url}" target="_blank" rel="noreferrer">Xem</a>
          <a class="icon-button" href="${file.url}" download>⇩</a>
        </div>
      `;
    })
    .join("");
  renderPreviews();
}

function chooseVideo(video) {
  state.selected = video;
  renderOutputs();
}

function renderVideos() {
  if (!state.videos.length) {
    state.selected = null;
    ui.videoSelect.innerHTML = `<option value="">Chua co video</option>`;
    renderOutputs();
    return;
  }
  if (state.selected && state.videos.some((video) => video.name === state.selected.name)) {
    state.selected = state.videos.find((video) => video.name === state.selected.name);
  } else {
    state.selected = null;
  }
  ui.videoSelect.innerHTML = [
    `<option value="">Khong chon video</option>`,
    ...state.videos.map((video) => `<option value="${video.name}">${video.name}</option>`),
  ].join("");
  ui.videoSelect.value = state.selected?.name || "";
  renderOutputs();
}

function renderJob(job) {
  state.job = job;
  if (state.keepLogs) {
    ui.logBox.textContent = job.logs?.length ? job.logs.join("\n") : "Chưa có log.";
    ui.logBox.scrollTop = ui.logBox.scrollHeight;
  }
  ui.runBtn.disabled = job.running || !state.selected;
  ui.capcutBtn.disabled = job.running || !(state.selected?.complete?.video && state.selected?.complete?.subtitle && state.selected?.complete?.audio && state.selected?.complete?.logo);
  if (job.running) {
    setWorkflowState(inferWorkflowStep(job.logs || []), "running");
  } else if (job.error) {
    setWorkflowState(inferWorkflowStep(job.logs || []), "error");
  } else if (state.selected?.status === "done") {
    setWorkflowState("capcut", "complete");
  }
}

function optionsPayload() {
  const form = new FormData(ui.optionsForm);
  return {
    whisperModel: form.get("whisperModel"),
    whisperDevice: form.get("whisperDevice"),
    whisperComputeType: form.get("whisperComputeType"),
    whisperFallbackModels: form.get("whisperFallbackModels"),
    geminiModel: form.get("geminiModel"),
    geminiRewritePrompt: form.get("geminiRewritePrompt"),
    geminiPostPrompt: form.get("geminiPostPrompt"),
    shopeeProductPrompt: form.get("shopeeProductPrompt"),
    ttsApiUrl: form.get("ttsApiUrl"),
    ttsVoiceId: form.get("ttsVoiceId"),
    ttsModelId: form.get("ttsModelId"),
    ttsTimeoutSeconds: Number(form.get("ttsTimeoutSeconds")),
    ttsMaxRetries: Number(form.get("ttsMaxRetries")),
    maxAudioSpeedupRatio: Number(form.get("maxAudioSpeedupRatio")),
    capcutPath: form.get("capcutPath"),
    capcutProjectDir: form.get("capcutProjectDir"),
  };
}

async function loadConfig() {
  state.config = await api("/api/config");
  applyConfigToForm();
}

async function loadVideos() {
  const payload = await api("/api/videos");
  state.videos = payload.videos;
  renderVideos();
}

async function loadJob() {
  const job = await api("/api/job");
  const wasRunning = state.lastJobRunning === true;
  renderJob(job);
  if (wasRunning && !job.running) {
    await loadVideos();
  }
  state.lastJobRunning = job.running;
}

async function uploadVideo(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    await api("/api/upload", { method: "POST", body: form });
    await loadVideos();
  } catch (error) {
    alert(error.message);
  } finally {
    ui.uploadInput.value = "";
  }
}

async function saveOptions() {
  ui.saveOptionsBtn.disabled = true;
  try {
    state.config = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(optionsPayload()),
    });
    applyConfigToForm();
    ui.saveOptionsBtn.textContent = "Đã lưu";
    setTimeout(() => {
      ui.saveOptionsBtn.textContent = "Lưu cài đặt";
    }, 1200);
  } catch (error) {
    alert(error.message);
  } finally {
    ui.saveOptionsBtn.disabled = false;
  }
}

async function runPipeline() {
  if (!state.selected) return;
  state.keepLogs = true;
  ui.logBox.textContent = "Đang khởi động pipeline...";
  setWorkflowState("import", "running");
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

async function openOutput() {
  try {
    await api("/api/open-output", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: state.selected?.stem }),
    });
  } catch (error) {
    alert(error.message);
  }
}

async function openCapCut() {
  try {
    const result = await api("/api/open-capcut", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: state.selected?.stem }),
    });
    if (result.message) {
      alert(result.message);
    }
    setWorkflowState("capcut", "complete");
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
  ui.dropZone.addEventListener("dragover", (event) => {
    event.preventDefault();
    ui.dropZone.classList.add("drag-over");
  });
  ui.dropZone.addEventListener("dragleave", () => {
    ui.dropZone.classList.remove("drag-over");
  });
  ui.dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    ui.dropZone.classList.remove("drag-over");
    uploadVideo(event.dataTransfer.files?.[0]);
  });
  ui.openOutputBtn.addEventListener("click", openOutput);
  ui.clearSelectionBtn.addEventListener("click", () => {
    chooseVideo(null);
    ui.videoSelect.value = "";
  });
  ui.copyCampaignBtn.addEventListener("click", async () => {
    await copyBoxText(ui.campaignPreview, ui.copyCampaignBtn);
  });
  ui.copyShopeeBtn.addEventListener("click", async () => {
    await copyBoxText(ui.shopeePreview, ui.copyShopeeBtn);
  });
  ui.videoSelect.addEventListener("change", () => {
    const video = state.videos.find((item) => item.name === ui.videoSelect.value);
    chooseVideo(video || null);
  });
  ui.runBtn.addEventListener("click", runPipeline);
  ui.saveOptionsBtn.addEventListener("click", saveOptions);
  ui.clearLogsBtn.addEventListener("click", () => {
    state.keepLogs = false;
    ui.logBox.textContent = "Đã xóa log hiển thị. Job nền vẫn tiếp tục nếu đang chạy.";
  });
  $$("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      showView(button.dataset.view);
      if (button.dataset.focus) {
        setTimeout(() => $(`#${button.dataset.focus}`)?.scrollIntoView({ behavior: "smooth" }), 50);
      }
    });
  });
  $$("[data-jump]").forEach((button) => {
    button.addEventListener("click", () => {
      showView("overview");
      setTimeout(() => $(`#${button.dataset.jump}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
    });
  });
  $$(".voice-option").forEach((button) => {
    button.addEventListener("click", () => {
      $$(".voice-option").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
    });
  });
  ui.capcutBtn.addEventListener("click", openCapCut);
}

async function boot() {
  wireEvents();
  await loadConfig();
  await loadVideos();
  await loadJob();
  setInterval(loadJob, 2500);
}

boot().catch((error) => {
  ui.logBox.textContent = error.stack || error.message;
});

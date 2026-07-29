const state = {
  config: null,
  videos: [],
  selected: null,
  job: null,
  keepLogs: true,
  lastJobRunning: null,
  lastRenderedAudioUrl: "",
  celebratedProject: "",
  voices: [],
  currentVoiceAudio: null,
  ttsHistory: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const ui = {
  uploadInput: $("#uploadInput"),
  outputList: $("#outputList"),
  outputStatus: $("#outputStatus"),
  runBtn: $("#runBtn"),
  refreshBtn: $("#refreshBtn"),
  themeToggle: $("#themeToggle"),
  saveOptionsBtn: $("#saveOptionsBtn"),
  clearSelectionBtn: $("#clearSelectionBtn"),
  copyCampaignBtn: $("#copyCampaignBtn"),
  copyShopeeBtn: $("#copyShopeeBtn"),
  clearLogsBtn: $("#clearLogsBtn"),
  optionsForm: $("#optionsForm"),
  geminiApiKeysInput: $("#geminiApiKeysInput"),
  toggleGeminiKeysBtn: $("#toggleGeminiKeysBtn"),
  logBox: $("#logBox"),
  openOutputBtn: $("#openOutputBtn"),
  dropZone: $("#dropZone"),
  subtitlePreview: $("#subtitlePreview"),
  campaignPreview: $("#campaignPreview"),
  shopeePreview: $("#shopeePreview"),
  audioPreview: $("#audioPreview"),
  videoSelect: $("#videoSelect"),
  capcutBtn: $("#capcutBtn"),
  batchList: $("#batchList"),
  batchRunBtn: $("#batchRunBtn"),
  batchSelectAllBtn: $("#batchSelectAllBtn"),
  batchClearBtn: $("#batchClearBtn"),
  batchStatus: $("#batchStatus"),
  sidebar: $("#sidebar"),
  sidebarToggle: $("#sidebarToggle"),
  ttsText: $("#ttsText"),
  ttsCharCount: $("#ttsCharCount"),
  ttsGenerateBtn: $("#ttsGenerateBtn"),
  ttsVoiceSelect: $("#ttsVoiceSelect"),
  ttsResult: $("#ttsResult"),
  ttsVoicePanel: $("#ttsVoicePanel"),
  ttsHistoryPanel: $("#ttsHistoryPanel"),
  ttsHistoryList: $("#ttsHistoryList"),
  voiceLibraryList: $("#voiceLibraryList"),
  voiceSearch: $("#voiceSearch"),
  loadVoicesBtn: $("#loadVoicesBtn"),
  voicePreviewPanel: $("#voicePreviewPanel"),
  historyList: $("#historyList"),
};

const voiceModules = window.VoiceModules;
const defaultVoices = voiceModules.defaultVoices;

const workflowSteps = ["import", "srt", "gemini", "tts", "capcut"];
const typewriterFrames = new WeakMap();
const typewriterCache = new WeakMap();
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
  $$("[data-view]").forEach((item) => {
    if (item.classList.contains("side-nav-item") || item.classList.contains("nav-item")) {
      item.classList.toggle("active", item.dataset.view === name);
    }
  });
  localStorage.setItem("active-view", name);
  if (name === "history") renderHistory();
  if (name === "voiceLibrary" && !state.voices.length) renderVoiceLibrary(defaultVoices);
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
  setFormValue("geminiModelFallbacks", settings.geminiModelFallbacks);
  setFormValue("geminiApiKeys", "");
  setFormValue("geminiRewritePrompt", settings.geminiRewritePrompt);
  setFormValue("geminiPostPrompt", settings.geminiPostPrompt);
  setFormValue("shopeeProductPrompt", settings.shopeeProductPrompt);
  setFormValue("ttsApiUrl", settings.ttsApiUrl);
  setFormValue("ttsVoiceId", settings.ttsVoiceId);
  setFormValue("ttsModelId", settings.ttsModelId);
  setFormValue("ttsTimeoutSeconds", settings.ttsTimeoutSeconds);
  setFormValue("ttsMaxRetries", settings.ttsMaxRetries);
  setFormValue("maxAudioSpeedupRatio", settings.maxAudioSpeedupRatio);
  setFormValue("ttsStrictTimeline", String(settings.ttsStrictTimeline ?? true));
  setFormValue("ttsSegmentGapMs", settings.ttsSegmentGapMs);
  setFormValue("capcutPath", settings.capcutPath);
  setFormValue("capcutProjectDir", settings.capcutProjectDir);
}

function applyGeminiKeysVisibility(hidden) {
  if (!ui.geminiApiKeysInput || !ui.toggleGeminiKeysBtn) return;
  ui.geminiApiKeysInput.classList.toggle("secret-masked", hidden);
  ui.toggleGeminiKeysBtn.classList.toggle("active", !hidden);
  ui.toggleGeminiKeysBtn.setAttribute("aria-pressed", String(!hidden));
  ui.toggleGeminiKeysBtn.title = hidden ? "Hiện Gemini API keys" : "Ẩn Gemini API keys";
  const label = ui.toggleGeminiKeysBtn.querySelector(".secret-toggle-label");
  if (label) label.textContent = hidden ? "Hiện" : "Ẩn";
}

function selectedOutput(name) {
  return state.selected?.outputs?.find((file) => file.name === name);
}

function outputByExtension(extension) {
  return state.selected?.outputs?.find((file) => file.name.toLowerCase().endsWith(extension));
}

async function copyBoxText(previewElement, buttonElement) {
  const text = (previewElement.dataset.fullText || previewElement.textContent).trim();
  if (!text || buttonElement.disabled) return;
  await navigator.clipboard.writeText(text);
  const defaultText = buttonElement.dataset.defaultText || buttonElement.textContent;
  buttonElement.dataset.defaultText = defaultText;
  buttonElement.textContent = "Đã copy! ✓";
  buttonElement.classList.add("copy-success", "spring-pop");
  setTimeout(() => {
    buttonElement.textContent = defaultText;
    buttonElement.classList.remove("copy-success", "spring-pop");
  }, 1500);
}

function applyTheme(theme) {
  const isLight = theme === "light";
  document.body.classList.toggle("light-theme", isLight);
  document.querySelector(".theme-icon-dark")?.classList.toggle("hidden", isLight);
  document.querySelector(".theme-icon-light")?.classList.toggle("hidden", !isLight);
  localStorage.setItem("ui-theme", theme);
}

function stopTypewriter(element) {
  const frameId = typewriterFrames.get(element);
  if (frameId) {
    cancelAnimationFrame(frameId);
    typewriterFrames.delete(element);
  }
  element.classList.remove("typing-text");
}

function setPreviewText(element, text, { animate = false } = {}) {
  const nextText = text || "";
  element.dataset.fullText = nextText;
  if (typewriterCache.get(element) === nextText && element.textContent === nextText) return;

  stopTypewriter(element);
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!animate || reducedMotion || !nextText.trim()) {
    element.textContent = nextText;
    typewriterCache.set(element, nextText);
    return;
  }

  let index = 0;
  const chunkSize = Math.max(2, Math.ceil(nextText.length / 130));
  element.textContent = "";
  element.classList.add("typing-text");

  const tick = () => {
    index = Math.min(nextText.length, index + chunkSize);
    element.textContent = nextText.slice(0, index);
    if (index < nextText.length) {
      typewriterFrames.set(element, requestAnimationFrame(tick));
      return;
    }
    element.classList.remove("typing-text");
    typewriterFrames.delete(element);
    typewriterCache.set(element, nextText);
  };
  typewriterFrames.set(element, requestAnimationFrame(tick));
}

function setupSpotlightCards() {
  $$(".spotlight-card").forEach((card) => {
    card.addEventListener("pointermove", (event) => {
      const rect = card.getBoundingClientRect();
      card.style.setProperty("--spotlight-x", `${event.clientX - rect.left}px`);
      card.style.setProperty("--spotlight-y", `${event.clientY - rect.top}px`);
      card.style.setProperty("--spotlight-opacity", "1");
    });
    card.addEventListener("pointerleave", () => {
      card.style.setProperty("--spotlight-opacity", "0");
    });
  });
}

function applySidebarState(collapsed) {
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  ui.sidebarToggle?.querySelector("span")?.replaceChildren(document.createTextNode(collapsed ? "Mở rộng" : "Thu gọn"));
  localStorage.setItem("sidebar-collapsed", collapsed ? "1" : "0");
}

function updateTtsControls() {
  if (!ui.ttsText || !ui.ttsCharCount || !ui.ttsGenerateBtn) return;
  const length = ui.ttsText.value.length;
  ui.ttsCharCount.textContent = `${length.toLocaleString("vi-VN")} / 8,000`;
  ui.ttsGenerateBtn.disabled = length === 0;
}

function renderVoiceOptions(voices = defaultVoices) {
  if (!ui.ttsVoiceSelect) return;
  ui.ttsVoiceSelect.innerHTML = voiceModules.voiceOptionHtml(voices);
}

function renderVoiceLibrary(voices = defaultVoices) {
  if (!ui.voiceLibraryList) return;
  ui.voiceLibraryList.innerHTML = voiceModules.voiceLibraryHtml(voices, ui.voiceSearch?.value || "");
}

function renderHistory() {
  if (!ui.historyList) return;
  ui.historyList.innerHTML = voiceModules.historyHtml(state.videos, formatBytes, formatDate);
}

function renderTtsHistory() {
  if (!ui.ttsHistoryList) return;
  ui.ttsHistoryList.innerHTML = voiceModules.ttsHistoryHtml(state.ttsHistory, formatBytes, formatDate);
}

async function loadTtsHistory() {
  try {
    const payload = await api("/api/tts/history");
    state.ttsHistory = payload.items || [];
  } catch {
    state.ttsHistory = [];
  }
  renderTtsHistory();
}

function showTtsSidePanel(name) {
  const isHistory = name === "history";
  ui.ttsVoicePanel?.classList.toggle("hidden", isHistory);
  ui.ttsHistoryPanel?.classList.toggle("hidden", !isHistory);
  $$("[data-tts-side-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.ttsSideTab === name);
  });
  if (isHistory) loadTtsHistory();
}

function playVoicePreview(row) {
  if (!ui.voicePreviewPanel) return;
  const voiceName = row.querySelector("strong")?.textContent || "Voice";
  const previewUrl = row.dataset.previewUrl;
  $$(".voice-library-row").forEach((item) => item.classList.remove("previewing"));

  if (!previewUrl) {
    ui.voicePreviewPanel.textContent = `Giọng "${voiceName}" chưa có preview_url từ API. Bấm "Dùng giọng" rồi tạo thử ở tab Text to Speech.`;
    return;
  }

  state.currentVoiceAudio?.pause();
  row.classList.add("previewing");
  ui.voicePreviewPanel.innerHTML = `
    <strong>Đang nghe thử: ${voiceName}</strong>
    <audio controls src="${previewUrl}"></audio>
  `;
  state.currentVoiceAudio = ui.voicePreviewPanel.querySelector("audio");
  state.currentVoiceAudio?.play().catch(() => undefined);
  state.currentVoiceAudio?.addEventListener("ended", () => row.classList.remove("previewing"), { once: true });
}

async function loadVoicesFromApi() {
  if (!ui.loadVoicesBtn) return;
  ui.loadVoicesBtn.disabled = true;
  const originalText = ui.loadVoicesBtn.textContent;
  ui.loadVoicesBtn.textContent = "Đang tải...";
  try {
    const payload = await api("/api/voices");
    state.voices = voiceModules.normalizeVoices(payload.voices?.length ? payload.voices : defaultVoices);
    renderVoiceOptions(state.voices);
    renderVoiceLibrary(state.voices);
  } catch (error) {
    alert(error.message);
    state.voices = voiceModules.normalizeVoices(defaultVoices);
    renderVoiceLibrary(defaultVoices);
  } finally {
    ui.loadVoicesBtn.disabled = false;
    ui.loadVoicesBtn.textContent = originalText;
  }
}

async function generateStandaloneTts() {
  if (!ui.ttsText || !ui.ttsGenerateBtn || !ui.ttsResult) return;
  const text = ui.ttsText.value.trim();
  if (!text) return;
  ui.ttsGenerateBtn.disabled = true;
  ui.ttsGenerateBtn.classList.add("spring-pop");
  ui.ttsResult.textContent = "Đang tạo audio...";
  try {
    const payload = await api("/api/tts/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voiceId: ui.ttsVoiceSelect?.value || "" }),
    });
    ui.ttsResult.innerHTML = `
      <strong>Đã tạo audio</strong>
      <audio controls src="${payload.url}"></audio>
      <a class="secondary-action" href="${payload.url}" download>Download MP3</a>
    `;
    state.ttsHistory = [
      {
        filename: payload.filename,
        url: payload.url,
        size: payload.size,
        createdAt: new Date().toISOString(),
      },
      ...state.ttsHistory,
    ];
    renderTtsHistory();
  } catch (error) {
    ui.ttsResult.textContent = error.message;
  } finally {
    ui.ttsGenerateBtn.classList.remove("spring-pop");
    updateTtsControls();
  }
}

function triggerOutputCelebration() {
  const project = state.selected?.stem || state.selected?.name;
  if (!project || state.celebratedProject === project) return;
  state.celebratedProject = project;

  const burst = document.createElement("div");
  burst.className = "confetti-burst";
  const colors = ["#22d3ee", "#a855f7", "#34d399", "#f59e0b", "#f472b6", "#818cf8"];
  for (let index = 0; index < 26; index += 1) {
    const particle = document.createElement("span");
    particle.className = "confetti-particle";
    const angle = (Math.PI * 2 * index) / 26;
    const distance = 58 + (index % 5) * 18;
    particle.style.setProperty("--x", `${Math.cos(angle) * distance}px`);
    particle.style.setProperty("--y", `${Math.sin(angle) * distance - 18}px`);
    particle.style.setProperty("--rotate", `${180 + index * 28}deg`);
    particle.style.setProperty("--size", `${5 + (index % 3) * 2}px`);
    particle.style.setProperty("--color", colors[index % colors.length]);
    particle.style.animationDelay = `${(index % 6) * 24}ms`;
    burst.appendChild(particle);
  }
  document.body.appendChild(burst);
  setTimeout(() => burst.remove(), 1400);
}

async function renderPreviews() {
  if (!state.selected) {
    if (state.lastRenderedAudioUrl) {
      ui.audioPreview.innerHTML = "Chưa có audio preview.";
      state.lastRenderedAudioUrl = "";
    }
    setPreviewText(ui.subtitlePreview, "Chọn video để xem SRT.");
    setPreviewText(ui.campaignPreview, "Chọn video đã chạy xong để xem caption đăng bài.");
    setPreviewText(ui.shopeePreview, "Chọn video đã chạy xong để xem gợi ý comment.");
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
      : "Chưa có audio preview.";
    state.lastRenderedAudioUrl = audioUrl;
  }

  if (subtitle) {
    try {
      const text = await fetch(subtitle.url).then((response) => response.text());
      setPreviewText(ui.subtitlePreview, text.split("\n\n").slice(0, 4).join("\n\n"), { animate: true });
    } catch {
      setPreviewText(ui.subtitlePreview, "Không đọc được file SRT.");
    }
  } else {
    setPreviewText(ui.subtitlePreview, "Chưa có file SRT.");
  }

  if (campaign) {
    try {
      setPreviewText(ui.campaignPreview, await fetch(campaign.url).then((response) => response.text()), { animate: true });
      ui.copyCampaignBtn.disabled = false;
    } catch {
      setPreviewText(ui.campaignPreview, "Không đọc được file caption.");
      ui.copyCampaignBtn.disabled = true;
    }
  } else {
    setPreviewText(ui.campaignPreview, "Chưa có caption. Chạy pipeline để tạo caption và hashtag.");
    ui.copyCampaignBtn.disabled = true;
  }

  if (shopee) {
    try {
      setPreviewText(ui.shopeePreview, await fetch(shopee.url).then((response) => response.text()));
      ui.copyShopeeBtn.disabled = false;
    } catch {
      setPreviewText(ui.shopeePreview, "Không đọc được file gợi ý comment.");
      ui.copyShopeeBtn.disabled = true;
    }
  } else {
    setPreviewText(ui.shopeePreview, "Chưa có gợi ý comment. Chạy pipeline để tạo nội dung.");
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
  if (complete) triggerOutputCelebration();
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
    ui.videoSelect.innerHTML = `<option value="">Chưa có video</option>`;
    renderOutputs();
    renderBatchVideos();
    return;
  }
  if (state.selected && state.videos.some((video) => video.name === state.selected.name)) {
    state.selected = state.videos.find((video) => video.name === state.selected.name);
  } else {
    state.selected = null;
  }
  ui.videoSelect.innerHTML = [
    `<option value="">Không chọn video</option>`,
    ...state.videos.map((video) => `<option value="${video.name}">${video.name}</option>`),
  ].join("");
  ui.videoSelect.value = state.selected?.name || "";
  renderOutputs();
  renderBatchVideos();
  renderHistory();
}

function selectedBatchNames() {
  return $$("input[name='batchVideo']:checked").map((input) => input.value);
}

function updateBatchStatus() {
  if (!ui.batchStatus || !ui.batchRunBtn) return;
  const selectedCount = selectedBatchNames().length;
  ui.batchStatus.textContent = selectedCount ? `${selectedCount}/5 video đã chọn` : "Chưa chọn video";
  ui.batchRunBtn.disabled = selectedCount === 0 || Boolean(state.job?.running);
}

function renderBatchVideos() {
  if (!ui.batchList) return;
  if (!state.videos.length) {
    ui.batchList.innerHTML = `<div class="empty">Chưa có video trong input_videos.</div>`;
    updateBatchStatus();
    return;
  }
  ui.batchList.innerHTML = state.videos
    .map((video) => {
      const readyText = video.status === "done" ? "Đã có output" : "Sẵn sàng chạy";
      return `
        <label class="batch-row">
          <input type="checkbox" name="batchVideo" value="${video.name}" />
          <span>
            <strong>${video.name}</strong>
            <small>${formatBytes(video.size)} • ${readyText}</small>
          </span>
        </label>
      `;
    })
    .join("");
  updateBatchStatus();
}

function renderJob(job) {
  state.job = job;
  if (state.keepLogs) {
    ui.logBox.textContent = job.logs?.length ? job.logs.join("\n") : "Chưa có log.";
    ui.logBox.scrollTop = ui.logBox.scrollHeight;
  }
  ui.runBtn.disabled = job.running || !state.selected;
  if (ui.batchRunBtn) ui.batchRunBtn.disabled = job.running || selectedBatchNames().length === 0;
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
    geminiModelFallbacks: form.get("geminiModelFallbacks"),
    geminiApiKeys: form.get("geminiApiKeys"),
    geminiRewritePrompt: form.get("geminiRewritePrompt"),
    geminiPostPrompt: form.get("geminiPostPrompt"),
    shopeeProductPrompt: form.get("shopeeProductPrompt"),
    ttsApiUrl: form.get("ttsApiUrl"),
    ttsVoiceId: form.get("ttsVoiceId"),
    ttsModelId: form.get("ttsModelId"),
    ttsTimeoutSeconds: Number(form.get("ttsTimeoutSeconds")),
    ttsMaxRetries: Number(form.get("ttsMaxRetries")),
    maxAudioSpeedupRatio: Number(form.get("maxAudioSpeedupRatio")),
    ttsStrictTimeline: form.get("ttsStrictTimeline"),
    ttsSegmentGapMs: Number(form.get("ttsSegmentGapMs")),
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

async function runBatchPipeline() {
  const videos = selectedBatchNames();
  if (!videos.length) return;
  state.keepLogs = true;
  ui.logBox.textContent = `Đang khởi động batch ${videos.length} video...`;
  setWorkflowState("import", "running");
  try {
    const job = await api("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videos }),
    });
    showView("logs");
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
  setupSpotlightCards();
  applySidebarState(localStorage.getItem("sidebar-collapsed") === "1");
  applyGeminiKeysVisibility(true);
  renderVoiceOptions(defaultVoices);
  renderVoiceLibrary(defaultVoices);
  updateTtsControls();
  ui.sidebarToggle?.addEventListener("click", () => {
    applySidebarState(!document.body.classList.contains("sidebar-collapsed"));
  });
  ui.themeToggle.addEventListener("click", () => {
    applyTheme(document.body.classList.contains("light-theme") ? "dark" : "light");
  });
  document.addEventListener("play", (event) => {
    if (event.target?.tagName === "AUDIO") {
      document.body.classList.add("audio-playing");
    }
  }, true);
  document.addEventListener("pause", (event) => {
    if (event.target?.tagName === "AUDIO") {
      document.body.classList.remove("audio-playing");
    }
  }, true);
  document.addEventListener("ended", (event) => {
    if (event.target?.tagName === "AUDIO") {
      document.body.classList.remove("audio-playing");
    }
  }, true);
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
  ui.toggleGeminiKeysBtn?.addEventListener("click", () => {
    applyGeminiKeysVisibility(!ui.geminiApiKeysInput.classList.contains("secret-masked"));
  });
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
  ui.batchList?.addEventListener("change", (event) => {
    if (event.target?.name !== "batchVideo") return;
    const selected = selectedBatchNames();
    if (selected.length > 5) {
      event.target.checked = false;
      alert("Chỉ chọn tối đa 5 video mỗi lượt để tránh limit API.");
    }
    updateBatchStatus();
  });
  ui.batchSelectAllBtn?.addEventListener("click", () => {
    $$("input[name='batchVideo']").forEach((input, index) => {
      input.checked = index < 5;
    });
    updateBatchStatus();
  });
  ui.batchClearBtn?.addEventListener("click", () => {
    $$("input[name='batchVideo']").forEach((input) => {
      input.checked = false;
    });
    updateBatchStatus();
  });
  ui.batchRunBtn?.addEventListener("click", runBatchPipeline);
  ui.ttsText?.addEventListener("input", updateTtsControls);
  ui.ttsGenerateBtn?.addEventListener("click", generateStandaloneTts);
  $$("[data-tts-side-tab]").forEach((button) => {
    button.addEventListener("click", () => showTtsSidePanel(button.dataset.ttsSideTab));
  });
  ui.loadVoicesBtn?.addEventListener("click", loadVoicesFromApi);
  ui.voiceSearch?.addEventListener("input", () => renderVoiceLibrary(state.voices.length ? state.voices : defaultVoices));
  ui.voiceLibraryList?.addEventListener("click", (event) => {
    const row = event.target.closest(".voice-library-row");
    if (!row) return;
    if (event.target.closest("[data-voice-action='preview']")) {
      playVoicePreview(row);
      return;
    }
    const useButton = event.target.closest("[data-voice-action='use']");
    if (!useButton) return;
    const voiceId = row?.dataset.voiceId || "";
    if (ui.ttsVoiceSelect) {
      ui.ttsVoiceSelect.value = voiceId;
    }
    showView("tts");
  });
  ui.historyList?.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-history-video]");
    if (!button) return;
    try {
      await api("/api/open-output", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project: button.dataset.historyVideo }),
      });
    } catch (error) {
      alert(error.message);
    }
  });
}

async function boot() {
  applyTheme(localStorage.getItem("ui-theme") || "dark");
  wireEvents();
  await loadConfig();
  await loadVideos();
  await loadJob();
  showView(localStorage.getItem("active-view") || "overview");
  setInterval(loadJob, 2500);
}

boot().catch((error) => {
  ui.logBox.textContent = error.stack || error.message;
});

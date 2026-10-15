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
  publishCaptionDirty: false,
  publishCaptionProject: "",
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
  finalVideoInput: $("#finalVideoInput"),
  finalVideoDropZone: $("#finalVideoDropZone"),
  finalVideoStatus: $("#finalVideoStatus"),
  publishProjectBadge: $("#publishProjectBadge"),
  publishCaption: $("#publishCaption"),
  publishCaptionCount: $("#publishCaptionCount"),
  facebookConfigStatus: $("#facebookConfigStatus"),
  publishFacebookBtn: $("#publishFacebookBtn"),
  publishTikTokBtn: $("#publishTikTokBtn"),
  tiktokRevealVideoBtn: $("#tiktokRevealVideoBtn"),
  tiktokCopyCaptionBtn: $("#tiktokCopyCaptionBtn"),
  publishDownloadVideo: $("#publishDownloadVideo"),
  publishOutputPath: $("#publishOutputPath"),
  publishRevealVideoBtn: $("#publishRevealVideoBtn"),
  publishCopyCaptionBtn: $("#publishCopyCaptionBtn"),
  publishResult: $("#publishResult"),
  publishCenterStatus: $("#publishCenterStatus"),
  publishStep1Status: $("#publishStep1Status"),
  publishStep2Status: $("#publishStep2Status"),
  publishStep3Status: $("#publishStep3Status"),
  publishReadyBtn: $("#publishReadyBtn"),
  facebookConnectionBadge: $("#facebookConnectionBadge"),
  facebookPageSelect: $("#facebookPageSelect"),
  settingsSaveState: $("#settingsSaveState"),
  aiSettingsStatus: $("#aiSettingsStatus"),
  voiceSettingsStatus: $("#voiceSettingsStatus"),
  capcutSettingsStatus: $("#capcutSettingsStatus"),
  publishingSettingsStatus: $("#publishingSettingsStatus"),
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
  capcutReady: "Sẵn sàng dựng",
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
  if (name === "editor" || name === "publish") {
    window.ShortsStudio?.activatePane(name === "editor" ? "subtitle" : "publish");
    name = "overview";
  }
  document.body.classList.toggle("studio-active", name === "overview");
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
  if (name === "overview") renderPublishState();
  document.dispatchEvent(new CustomEvent("shorts:view-change", { detail: { name } }));
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

    if (mode === "finished") {
      card.classList.add("done");
      if (status) status.textContent = step === "capcut" ? "Đã render" : workflowLabels.done;
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
  setFormValue("googleTranslateFallback", String(settings.googleTranslateFallback ?? true));
  setFormValue("geminiApiKeys", "");
  setFormValue("geminiRewritePrompt", settings.geminiRewritePrompt);
  setFormValue("geminiPostPrompt", settings.geminiPostPrompt);
  setFormValue("ttsEnhancePrompt", settings.ttsEnhancePrompt);
  setFormValue("shopeeProductPrompt", settings.shopeeProductPrompt);
  setFormValue("ttsApiUrl", settings.ttsApiUrl);
  setFormValue("ttsApiKey", "");
  setFormValue("ttsMode", settings.ttsMode);
  setFormValue("ttsEnhanceEnabled", String(settings.ttsEnhanceEnabled ?? true));
  setFormValue("ttsSemanticChunkEnabled", String(settings.ttsSemanticChunkEnabled ?? true));
  setFormValue("ttsAudioFirst", String(settings.ttsAudioFirst ?? false));
  setFormValue("ttsQualityModelId", settings.ttsQualityModelId);
  setFormValue("ttsFastModelId", settings.ttsFastModelId);
  setFormValue("ttsVoiceId", settings.ttsVoiceId);
  setFormValue("ttsModelId", settings.ttsModelId);
  setFormValue("ttsTimeoutSeconds", settings.ttsTimeoutSeconds);
  setFormValue("ttsMaxRetries", settings.ttsMaxRetries);
  setFormValue("maxAudioSpeedupRatio", settings.maxAudioSpeedupRatio);
  setFormValue("ttsFinalSpeedupRatio", settings.ttsFinalSpeedupRatio);
  setFormValue("ttsQualityMaxSpeedupRatio", settings.ttsQualityMaxSpeedupRatio);
  setFormValue("ttsQualityFinalSpeedupRatio", settings.ttsQualityFinalSpeedupRatio);
  setFormValue("ttsStrictTimeline", String(settings.ttsStrictTimeline ?? true));
  setFormValue("ttsSegmentGapMs", settings.ttsSegmentGapMs);
  setFormValue("ttsMaxSilenceGapMs", settings.ttsMaxSilenceGapMs);
  setFormValue("ttsReuseSegments", String(settings.ttsReuseSegments ?? true));
  setFormValue("ttsChunkMaxChars", settings.ttsChunkMaxChars);
  setFormValue("ttsChunkMaxSegments", settings.ttsChunkMaxSegments);
  setFormValue("ttsTargetCharsPerSecond", settings.ttsTargetCharsPerSecond);
  setFormValue("ttsUseDurationTextBudget", String(settings.ttsUseDurationTextBudget ?? true));
  setFormValue("ttsPreserveScript", String(settings.ttsPreserveScript ?? true));
  setFormValue("ttsLeadInMs", settings.ttsLeadInMs ?? 80);
  setFormValue("ttsFitAudioToVideo", String(settings.ttsFitAudioToVideo ?? true));
  setFormValue("ttsEmergencyFinalSpeedupRatio", settings.ttsEmergencyFinalSpeedupRatio);
  setFormValue("ttsVoiceStability", settings.ttsVoiceStability);
  setFormValue("ttsVoiceSimilarity", settings.ttsVoiceSimilarity);
  setFormValue("ttsVoiceStyle", settings.ttsVoiceStyle);
  setFormValue("capcutPath", settings.capcutPath);
  setFormValue("capcutProjectDir", settings.capcutProjectDir);
  setFormValue("openCutUrl", settings.openCutUrl);
  setFormValue("editorAutoRender", String(settings.editorAutoRender ?? true));
  setFormValue("editorSubtitleTemplate", settings.editorSubtitleTemplate);
  setFormValue("editorSubtitleFontSize", settings.editorSubtitleFontSize);
  setFormValue("editorSubtitleMarginBottom", settings.editorSubtitleMarginBottom);
  setFormValue("editorSubtitleColor", settings.editorSubtitleColor);
  setFormValue("editorSubtitleAccentColor", settings.editorSubtitleAccentColor);
  setFormValue("editorSubtitleOutlineColor", settings.editorSubtitleOutlineColor);
  setFormValue("editorSubtitleBackground", settings.editorSubtitleBackground);
  setFormValue("editorSubtitleBackgroundOpacity", settings.editorSubtitleBackgroundOpacity);
  setFormValue("editorLogoPosition", settings.editorLogoPosition);
  setFormValue("editorLogoWidth", settings.editorLogoWidth);
  setFormValue("editorLogoOpacity", settings.editorLogoOpacity);
  setFormValue("editorVoiceVolume", settings.editorVoiceVolume);
  setFormValue("editorSourceVolume", settings.editorSourceVolume ?? 0);
  setFormValue("editorRenderPreset", settings.editorRenderPreset);
  setFormValue("facebookPageId", settings.facebookPageId);
  setFormValue("facebookPageUrl", settings.facebookPageUrl);
  renderPublishState();
  renderSettingsStatuses();
}

function setSettingsStatus(element, label, ready) {
  if (!element) return;
  element.textContent = label;
  element.classList.toggle("ready", ready);
  element.classList.toggle("warning", !ready);
}

function renderSettingsStatuses() {
  const apiStatus = state.config?.api || {};
  const settings = state.config?.settings || {};
  const pageConfigured = Boolean(facebookPageUrl());
  setSettingsStatus(
    ui.aiSettingsStatus,
    apiStatus.gemini ? `${apiStatus.geminiKeyCount || 1} Gemini key` : "Thiếu Gemini key",
    Boolean(apiStatus.gemini),
  );
  setSettingsStatus(
    ui.voiceSettingsStatus,
    apiStatus.tts ? "API đã kết nối" : "Thiếu ElevenLabs key",
    Boolean(apiStatus.tts),
  );
  setSettingsStatus(
    ui.capcutSettingsStatus,
    settings.editorAutoRender ? "Auto render đang bật" : "Đang chỉnh thủ công",
    Boolean(settings.editorAutoRender),
  );

  setSettingsStatus(
    ui.publishingSettingsStatus,
    pageConfigured ? "Đã lưu Fanpage" : "Chưa lưu Fanpage",
    pageConfigured,
  );
}

function setSettingsSaveState(label, stateName = "") {
  if (!ui.settingsSaveState) return;
  ui.settingsSaveState.textContent = label;
  ui.settingsSaveState.classList.toggle("dirty", stateName === "dirty");
  ui.settingsSaveState.classList.toggle("saved", stateName === "saved");
}

function restoreSettingsPanel() {
  const sections = $$(".settings-section");
  if (!sections.length) return;
  const savedPanel = localStorage.getItem("settings-panel") || "ai";
  const target = sections.find((section) => section.dataset.settingsPanel === savedPanel) || sections[0];
  sections.forEach((section) => {
    section.open = section === target;
  });
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

function setPublishResult(message, tone = "") {
  if (!ui.publishResult) return;
  const content = ui.publishResult.querySelector("span") || ui.publishResult;
  content.textContent = message;
  ui.publishResult.classList.toggle("success", tone === "success");
  ui.publishResult.classList.toggle("error", tone === "error");
}

function setPageBadge(element, configured) {
  if (!element) return;
  element.classList.toggle("connected", configured);
  const dot = element.querySelector("i");
  element.textContent = configured ? "Đã lưu trang" : "Chưa lưu trang";
  if (dot) element.prepend(dot);
}

function facebookPageUrl() {
  const settings = state.config?.settings || {};
  const configuredUrl = String(settings.facebookPageUrl || "").trim();
  if (configuredUrl) {
    try {
      const url = new URL(configuredUrl);
      if (url.protocol === "https:" && ["facebook.com", "www.facebook.com", "web.facebook.com", "m.facebook.com"].includes(url.host) && url.pathname !== "/") {
        url.host = "www.facebook.com";
        return url.href;
      }
    } catch {}
  }
  const pageId = String(settings.facebookPageId || "").trim();
  return /^\d+$/.test(pageId) ? `https://www.facebook.com/${pageId}` : "";
}

function renderPublishState() {
  if (!ui.publishProjectBadge) return;
  const finalVideo = selectedOutput("video_final.mp4");
  const missingComposition = Boolean(state.selected && (!state.selected.complete.subtitle || !state.selected.complete.audio));
  const pageUrl = facebookPageUrl();
  const facebookConfigured = Boolean(pageUrl);
  const hasCaption = Boolean(postingCaption(ui.publishCaption?.value));
  const readyToPublish = Boolean(state.selected && finalVideo && hasCaption && !missingComposition);

  ui.publishProjectBadge.textContent = state.selected ? state.selected.name : "Chưa chọn project";
  ui.finalVideoStatus.textContent = finalVideo
    ? missingComposition
      ? `⚠ ${finalVideo.name} thiếu SRT Việt hoặc giọng lồng tiếng. Hãy kiểm tra trước khi đăng.`
      : `✓ ${finalVideo.name} • ${formatBytes(finalVideo.size)} • sẵn sàng đăng`
    : "Chưa có video final. Render trong Video Editor hoặc chọn file MP4 tại đây.";
  ui.finalVideoStatus.classList.toggle("ready", Boolean(finalVideo && !missingComposition));
  ui.facebookConfigStatus.textContent = facebookConfigured ? "Tự copy tiêu đề & hashtag khi mở · không gửi video qua API" : "Thêm link Fanpage hoặc Page ID trong Cài đặt";
  ui.publishFacebookBtn.disabled = !facebookConfigured;
  ui.publishReadyBtn.disabled = !facebookConfigured;
  ui.publishCopyCaptionBtn.disabled = !hasCaption;
  ui.tiktokCopyCaptionBtn.disabled = !hasCaption;
  ui.publishDownloadVideo.hidden = !finalVideo;
  if (finalVideo) ui.publishDownloadVideo.href = finalVideo.url;
  else ui.publishDownloadVideo.removeAttribute("href");
  const baseDir = state.config?.paths?.base || "";
  const outputDir = state.selected?.outputDir || "";
  const separator = baseDir.includes("\\") ? "\\" : "/";
  ui.publishOutputPath.textContent = finalVideo && outputDir
    ? [baseDir.replace(/[\\/]+$/, ""), outputDir.replace(/[\\/]/g, separator), finalVideo.name].filter(Boolean).join(separator)
    : "Chưa có video_final.mp4";
  ui.publishRevealVideoBtn.disabled = !finalVideo;
  ui.tiktokRevealVideoBtn.disabled = !finalVideo;

  ui.publishStep1Status.textContent = finalVideo ? missingComposition ? "Cần kiểm tra MP4" : "Video sẵn sàng" : "Chưa có video";
  ui.publishStep1Status.classList.toggle("ready", Boolean(finalVideo && !missingComposition));
  ui.publishStep2Status.textContent = hasCaption ? "Đã có nội dung" : "Chưa có nội dung";
  ui.publishStep2Status.classList.toggle("ready", hasCaption);
  ui.publishStep3Status.textContent = facebookConfigured ? "TikTok & Fanpage sẵn sàng" : "TikTok Studio sẵn sàng";
  ui.publishStep3Status.classList.add("ready");

  ui.publishCenterStatus.innerHTML = missingComposition ? "<i></i> Thiếu SRT/voice" : readyToPublish ? "<i></i> Sẵn sàng đăng thủ công" : "<i></i> Đang chuẩn bị";
  setPageBadge(ui.facebookConnectionBadge, facebookConfigured);
  ui.facebookPageSelect.textContent = pageUrl || "Chưa lưu Fanpage";
  $("#facebookPublishCard")?.classList.toggle("connected", facebookConfigured);
  $$(".publish-platform-choice")[0]?.classList.toggle("connected", facebookConfigured);
  if (ui.publishCaptionCount) {
    ui.publishCaptionCount.textContent = `${ui.publishCaption.value.length.toLocaleString("vi-VN")} / 2200`;
  }
}

async function uploadFinalVideo(file) {
  if (!file || !state.selected) {
    alert("Hãy chọn project trước khi tải video final.");
    return;
  }
  const form = new FormData();
  form.append("project", state.selected.stem);
  form.append("file", file);
  ui.finalVideoStatus.textContent = "Đang tải video final...";
  try {
    await api("/api/publish/final-video", { method: "POST", body: form });
    await loadVideos();
    setPublishResult("Video final đã sẵn sàng. Copy caption rồi mở TikTok Studio hoặc Fanpage để đăng.", "success");
  } catch (error) {
    setPublishResult(error.message, "error");
    alert(error.message);
  } finally {
    ui.finalVideoInput.value = "";
    renderPublishState();
  }
}

async function revealFinalVideo(platform = "nền tảng đăng video") {
  if (!state.selected || !selectedOutput("video_final.mp4")) return false;
  try {
    await api("/api/open-output", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: state.selected.stem, file: "video_final.mp4" }),
    });
    setPublishResult(`Đã chọn video_final.mp4 trong Explorer. Bạn có thể kéo file vào ${platform}.`, "success");
    return true;
  } catch (error) {
    setPublishResult(`Không mở được file video: ${error.message}`, "error");
    return false;
  }
}

function openPublishPage(url, platform, copyButton) {
  const hasCaption = Boolean(postingCaption(ui.publishCaption.value));
  const hasVideo = Boolean(selectedOutput("video_final.mp4"));
  const copyTask = hasCaption ? copyPublishCaption(copyButton) : Promise.resolve(false);
  window.open(url, "_blank", "noopener,noreferrer");
  const revealTask = hasVideo ? revealFinalVideo(platform) : Promise.resolve(false);
  void Promise.all([copyTask, revealTask]).then(([copied, revealed]) => {
    if (!copied) {
      setPublishResult(hasCaption ? "Đã mở trang nhưng không copy được caption. Hãy bấm Copy caption thủ công."
        : "Đã mở trang nhưng chưa có tiêu đề & hashtag để copy.", "error");
    } else if (revealed) {
      setPublishResult(`Đã copy tiêu đề & hashtag và hiện MP4 trong Explorer để kéo vào ${platform}.`, "success");
    } else if (!hasVideo) {
      setPublishResult(`Đã copy tiêu đề & hashtag. Hãy render video_final.mp4 trước khi đăng lên ${platform}.`, "success");
    }
  });
}

function openFacebookPage() {
  const pageUrl = facebookPageUrl();
  if (pageUrl) openPublishPage(pageUrl, "Facebook Reels", ui.publishCopyCaptionBtn);
}

function openTikTokStudio() {
  openPublishPage("https://www.tiktok.com/tiktokstudio", "TikTok Studio", ui.tiktokCopyCaptionBtn);
}

function postingCaption(text) {
  const lines = String(text || "").split(/\r?\n/).map((line) => line.trim().replace(/^\*+|\*+$/g, "")).filter(Boolean);
  const titleLine = lines.find((line) => /^(?:tiêu đề|caption|title)\s*:/i.test(line));
  const title = (titleLine || lines.find((line) => !line.startsWith("#") && !/^(?:hashtag|nội dung bài đăng)\s*:/i.test(line)) || "")
    .replace(/^(?:tiêu đề|caption|title)\s*:\s*/i, "").trim();
  if (!title) return "";
  const hashtagLine = lines.find((line) => /^hashtag\s*:/i.test(line)) || lines.find((line) => line.startsWith("#")) || "";
  const hashtags = [];
  const addHashtag = (hashtag) => {
    if (hashtag && hashtags.length < 3 && !hashtags.some((existing) => existing.toLocaleLowerCase("vi") === hashtag.toLocaleLowerCase("vi"))) {
      hashtags.push(hashtag);
    }
  };
  (hashtagLine.match(/#[\p{L}\p{N}_]+/gu) || []).forEach(addHashtag);
  const productWords = title.match(/[\p{L}\p{N}]+/gu)?.slice(0, 4) || [];
  const productTag = productWords.map((word) => word[0].toUpperCase() + word.slice(1).toLowerCase())
    .join("").replace(/Đ/g, "D").replace(/đ/g, "d").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^A-Za-z0-9]/g, "");
  [productTag && `#${productTag}`, "#review", "#sanpham"].forEach(addHashtag);
  return [title, hashtags.join(" ")].filter(Boolean).join("\n");
}

async function copyPublishCaption(button = ui.publishCopyCaptionBtn) {
  const caption = postingCaption(ui.publishCaption.value);
  if (!caption) return false;
  try {
    await navigator.clipboard.writeText(caption);
    button.textContent = "Đã copy! ✓";
    button.classList.add("copy-success", "spring-pop");
    setTimeout(() => {
      button.textContent = "Copy caption";
      button.classList.remove("copy-success", "spring-pop");
    }, 1500);
    setPublishResult("Đã copy caption. Dán vào bài đăng trên TikTok hoặc Fanpage.", "success");
    return true;
  } catch {
    setPublishResult("Không copy được tự động; hãy chọn và copy nội dung trong ô caption phía trên.", "error");
    return false;
  }
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
    if (ui.publishCaption) ui.publishCaption.value = "";
    renderPublishState();
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
      const campaignText = postingCaption(await fetch(campaign.url).then((response) => response.text()));
      setPreviewText(ui.campaignPreview, campaignText, { animate: true });
      if (!state.publishCaptionDirty || state.publishCaptionProject !== state.selected.stem) {
        ui.publishCaption.value = campaignText.trim();
        state.publishCaptionProject = state.selected.stem;
        state.publishCaptionDirty = false;
      }
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
  renderPublishState();
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
  const finalReady = Boolean(video.complete.finalVideo && complete);
  const readyCount = ["video", "subtitle", "audio", "logo", "finalVideo"].filter((key) => video.complete[key]).length;
  ui.outputStatus.textContent = finalReady ? "5/5 file · video final sẵn sàng" : complete ? "4/5 file · sẵn sàng dựng" : `${readyCount}/5 file đã sẵn sàng`;
  if (finalReady) triggerOutputCelebration();
  setWorkflowState(finalReady ? "capcut" : complete ? "capcut" : "import", finalReady ? "finished" : complete ? "complete" : "ready");
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
  if (state.selected?.stem !== video?.stem) {
    state.publishCaptionDirty = false;
    state.publishCaptionProject = "";
  }
  state.selected = video;
  renderOutputs();
  renderPublishState();
  document.dispatchEvent(new CustomEvent("shorts:selection-changed", { detail: { video } }));
}

function renderVideos() {
  if (!state.videos.length) {
    state.selected = null;
    ui.videoSelect.innerHTML = `<option value="">Chưa có video</option>`;
    renderOutputs();
    renderBatchVideos();
    document.dispatchEvent(new CustomEvent("shorts:selection-changed", { detail: { video: null } }));
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
  if (state.selected) {
    document.dispatchEvent(new CustomEvent("shorts:selection-changed", { detail: { video: state.selected } }));
  }
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
  } else if (state.selected?.complete?.finalVideo && state.selected?.complete?.subtitle && state.selected?.complete?.audio && state.selected?.complete?.logo) {
    setWorkflowState("capcut", "finished");
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
    googleTranslateFallback: form.get("googleTranslateFallback"),
    geminiApiKeys: form.get("geminiApiKeys"),
    geminiRewritePrompt: form.get("geminiRewritePrompt"),
    geminiPostPrompt: form.get("geminiPostPrompt"),
    ttsEnhancePrompt: form.get("ttsEnhancePrompt"),
    shopeeProductPrompt: form.get("shopeeProductPrompt"),
    ttsApiUrl: form.get("ttsApiUrl"),
    ttsApiKey: form.get("ttsApiKey"),
    ttsMode: form.get("ttsMode"),
    ttsEnhanceEnabled: form.get("ttsEnhanceEnabled"),
    ttsSemanticChunkEnabled: form.get("ttsSemanticChunkEnabled"),
    ttsAudioFirst: form.get("ttsAudioFirst"),
    ttsQualityModelId: form.get("ttsQualityModelId"),
    ttsFastModelId: form.get("ttsFastModelId"),
    ttsVoiceId: form.get("ttsVoiceId"),
    ttsModelId: form.get("ttsModelId"),
    ttsTimeoutSeconds: Number(form.get("ttsTimeoutSeconds")),
    ttsMaxRetries: Number(form.get("ttsMaxRetries")),
    maxAudioSpeedupRatio: Number(form.get("maxAudioSpeedupRatio")),
    ttsFinalSpeedupRatio: Number(form.get("ttsFinalSpeedupRatio")),
    ttsQualityMaxSpeedupRatio: Number(form.get("ttsQualityMaxSpeedupRatio")),
    ttsQualityFinalSpeedupRatio: Number(form.get("ttsQualityFinalSpeedupRatio")),
    ttsStrictTimeline: form.get("ttsStrictTimeline"),
    ttsSegmentGapMs: Number(form.get("ttsSegmentGapMs")),
    ttsMaxSilenceGapMs: Number(form.get("ttsMaxSilenceGapMs")),
    ttsReuseSegments: form.get("ttsReuseSegments"),
    ttsChunkMaxChars: Number(form.get("ttsChunkMaxChars")),
    ttsChunkMaxSegments: Number(form.get("ttsChunkMaxSegments")),
    ttsTargetCharsPerSecond: Number(form.get("ttsTargetCharsPerSecond")),
    ttsUseDurationTextBudget: form.get("ttsUseDurationTextBudget"),
    ttsPreserveScript: form.get("ttsPreserveScript"),
    ttsLeadInMs: Number(form.get("ttsLeadInMs")),
    ttsFitAudioToVideo: form.get("ttsFitAudioToVideo"),
    ttsEmergencyFinalSpeedupRatio: Number(form.get("ttsEmergencyFinalSpeedupRatio")),
    ttsVoiceStability: Number(form.get("ttsVoiceStability")),
    ttsVoiceSimilarity: Number(form.get("ttsVoiceSimilarity")),
    ttsVoiceStyle: Number(form.get("ttsVoiceStyle")),
    capcutPath: form.get("capcutPath"),
    capcutProjectDir: form.get("capcutProjectDir"),
    openCutUrl: form.get("openCutUrl"),
    editorAutoRender: form.get("editorAutoRender"),
    editorSubtitleTemplate: form.get("editorSubtitleTemplate"),
    editorSubtitleFontSize: Number(form.get("editorSubtitleFontSize")),
    editorSubtitleMarginBottom: Number(form.get("editorSubtitleMarginBottom")),
    editorSubtitleColor: form.get("editorSubtitleColor"),
    editorSubtitleAccentColor: form.get("editorSubtitleAccentColor"),
    editorSubtitleOutlineColor: form.get("editorSubtitleOutlineColor"),
    editorSubtitleBackground: form.get("editorSubtitleBackground"),
    editorSubtitleBackgroundOpacity: Number(form.get("editorSubtitleBackgroundOpacity")) / 100,
    editorLogoPosition: form.get("editorLogoPosition"),
    editorLogoWidth: Number(form.get("editorLogoWidth")),
    editorLogoOpacity: Number(form.get("editorLogoOpacity")) / 100,
    editorVoiceVolume: Number(form.get("editorVoiceVolume")) / 100,
    editorSourceVolume: Number(form.get("editorSourceVolume")) / 100,
    editorRenderPreset: form.get("editorRenderPreset"),
    facebookPageId: form.get("facebookPageId"),
    facebookPageUrl: form.get("facebookPageUrl"),
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
  setSettingsSaveState("Đang lưu...", "dirty");
  try {
    state.config = await api("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(optionsPayload()),
    });
    applyConfigToForm();
    ui.saveOptionsBtn.textContent = "Đã lưu";
    setSettingsSaveState("Đã lưu an toàn vào .env", "saved");
    setTimeout(() => {
      ui.saveOptionsBtn.textContent = "Lưu cài đặt";
      setSettingsSaveState("Chưa có thay đổi");
    }, 1200);
  } catch (error) {
    setSettingsSaveState("Lưu thất bại", "dirty");
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
  ui.finalVideoInput?.addEventListener("change", (event) => uploadFinalVideo(event.target.files?.[0]));
  ui.finalVideoDropZone?.addEventListener("dragover", (event) => {
    event.preventDefault();
    ui.finalVideoDropZone.classList.add("drag-over");
  });
  ui.finalVideoDropZone?.addEventListener("dragleave", () => ui.finalVideoDropZone.classList.remove("drag-over"));
  ui.finalVideoDropZone?.addEventListener("drop", (event) => {
    event.preventDefault();
    ui.finalVideoDropZone.classList.remove("drag-over");
    uploadFinalVideo(event.dataTransfer.files?.[0]);
  });
  ui.publishCaption?.addEventListener("input", () => {
    state.publishCaptionDirty = true;
    renderPublishState();
  });
  ui.publishFacebookBtn?.addEventListener("click", openFacebookPage);
  ui.publishTikTokBtn?.addEventListener("click", openTikTokStudio);
  ui.publishReadyBtn?.addEventListener("click", openFacebookPage);
  ui.publishRevealVideoBtn?.addEventListener("click", () => revealFinalVideo("Facebook Reels"));
  ui.tiktokRevealVideoBtn?.addEventListener("click", () => revealFinalVideo("TikTok Studio"));
  ui.publishCopyCaptionBtn?.addEventListener("click", () => copyPublishCaption(ui.publishCopyCaptionBtn));
  ui.tiktokCopyCaptionBtn?.addEventListener("click", () => copyPublishCaption(ui.tiktokCopyCaptionBtn));
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
  ui.optionsForm?.addEventListener("input", () => setSettingsSaveState("Có thay đổi chưa lưu", "dirty"));
  ui.optionsForm?.addEventListener("change", () => setSettingsSaveState("Có thay đổi chưa lưu", "dirty"));
  $$(".settings-section").forEach((section) => {
    section.addEventListener("toggle", () => {
      if (!section.open) return;
      $$(".settings-section").forEach((other) => {
        if (other !== section) other.open = false;
      });
      localStorage.setItem("settings-panel", section.dataset.settingsPanel || "ai");
    });
  });
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
        setTimeout(() => {
          const target = $(`#${button.dataset.focus}`);
          const section = target?.closest("details");
          if (section) {
            $$(".settings-section").forEach((item) => {
              item.open = item === section;
            });
          }
          target?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 50);
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
  ui.capcutBtn.addEventListener("click", () => showView("editor"));
  document.addEventListener("shorts:editor-rendered", async () => {
    await loadVideos();
    renderPublishState();
  });
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
  applyTheme(localStorage.getItem("ui-theme") || "light");
  wireEvents();
  restoreSettingsPanel();
  await loadConfig();
  await loadVideos();
  await loadJob();
  showView(localStorage.getItem("active-view") || "overview");
  setInterval(loadJob, 2500);
}

boot().catch((error) => {
  ui.logBox.textContent = error.stack || error.message;
});

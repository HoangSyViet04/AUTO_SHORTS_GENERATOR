(() => {
  const editorState = {
    project: "",
    manifest: null,
    cues: [],
    voiceCues: [],
    renderTimer: null,
    pendingRenderProject: null,
    completedRenderKey: null,
    previewFrame: null,
    syncingAudio: false,
    subtitleFrameKey: "",
    previewMode: "edit",
    mediaVersion: 0,
  };

  const byId = (id) => document.getElementById(id);
  const editorUi = {
    view: byId("editorView"),
    shell: byId("editorView")?.querySelector(".editor-shell"),
    projectBadge: byId("editorProjectBadge"),
    openCutBtn: byId("editorOpenCutBtn"),
    manifestBtn: byId("editorManifestBtn"),
    renderBtn: byId("editorRenderBtn"),
    reloadBtn: byId("editorReloadBtn"),
    empty: byId("editorEmpty"),
    assets: byId("editorAssets"),
    video: byId("editorVideo"),
    voice: byId("editorVoicePreview"),
    logo: byId("editorLogoOverlay"),
    subtitle: byId("editorSubtitleOverlay"),
    canvas: byId("editorCanvas"),
    canvasEmpty: byId("editorCanvasEmpty"),
    stageStatus: byId("editorStageStatus"),
    previewEditBtn: byId("editorPreviewEditBtn"),
    previewFinalBtn: byId("editorPreviewFinalBtn"),
    playBtn: byId("editorPlayBtn"),
    scrubber: byId("editorScrubber"),
    currentTime: byId("editorCurrentTime"),
    duration: byId("editorDuration"),
    focusBtn: byId("editorFocusBtn"),
    fitBtn: byId("editorFitBtn"),
    muteBtn: byId("editorMuteBtn"),
    timeline: byId("editorTimeline"),
    timelineTitle: byId("editorTimelineTitle"),
    renderStatus: byId("editorRenderStatus"),
    subtitleEnabled: byId("editorSubtitleEnabled"),
    subtitleTemplate: byId("editorSubtitleTemplate"),
    subtitleTemplateButtons: Array.from(document.querySelectorAll("[data-subtitle-template]")),
    subtitleSize: byId("editorSubtitleSize"),
    subtitleMargin: byId("editorSubtitleMargin"),
    subtitleColor: byId("editorSubtitleColor"),
    subtitleAccentColor: byId("editorSubtitleAccentColor"),
    subtitleOutlineColor: byId("editorSubtitleOutlineColor"),
    subtitleBackground: byId("editorSubtitleBackground"),
    subtitleOpacity: byId("editorSubtitleOpacity"),
    subtitleOpacityValue: byId("editorSubtitleOpacityValue"),
    logoEnabled: byId("editorLogoEnabled"),
    logoPosition: byId("editorLogoPosition"),
    logoWidth: byId("editorLogoWidth"),
    logoWidthValue: byId("editorLogoWidthValue"),
    logoOpacity: byId("editorLogoOpacity"),
    logoOpacityValue: byId("editorLogoOpacityValue"),
    voiceVolume: byId("editorVoiceVolume"),
    voiceVolumeValue: byId("editorVoiceVolumeValue"),
    sourceVolume: byId("editorSourceVolume"),
    sourceVolumeValue: byId("editorSourceVolumeValue"),
    quality: byId("editorRenderQuality"),
  };

  if (!editorUi.view) return;

  async function editorApi(url, options = {}) {
    const response = await fetch(url, options);
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : await response.text();
    if (!response.ok) {
      throw new Error(typeof payload === "string" ? payload : payload.detail || `HTTP ${response.status}`);
    }
    return payload;
  }

  function selectedProject() {
    const selectedName = byId("videoSelect")?.value || "";
    return selectedName.replace(/\.(mp4|mkv)$/i, "");
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatBytes(bytes) {
    const units = ["B", "KB", "MB", "GB"];
    let value = Number(bytes || 0);
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return index ? `${value.toFixed(1)} ${units[index]}` : `${value} B`;
  }

  function formatTime(seconds) {
    const safeSeconds = Math.max(0, Number(seconds || 0));
    const minutes = Math.floor(safeSeconds / 60);
    const remainder = safeSeconds - minutes * 60;
    return `${String(minutes).padStart(2, "0")}:${remainder.toFixed(1).padStart(4, "0")}`;
  }

  function assetRows(manifest) {
    const assets = [manifest.source, manifest.assets.voice, manifest.assets.subtitle, manifest.assets.logo].filter(Boolean);
    const labels = { video: "VIDEO", audio: "VOICE", subtitle: "SRT", image: "LOGO" };
    editorUi.assets.innerHTML = assets
      .map(
        (asset) => `
          <div class="editor-asset-row ${escapeHtml(asset.kind)}">
            <span class="editor-asset-icon">${labels[asset.kind] || "FILE"}</span>
            <span class="editor-asset-copy">
              <strong>${escapeHtml(asset.name)}</strong>
              <small>${formatBytes(asset.size)} · đã liên kết</small>
            </span>
            <span class="editor-asset-check">✓</span>
          </div>
        `,
      )
      .join("");
  }

  function renderTimeline(manifest) {
    const trackClasses = { video: "video", audio: "voice", subtitle: "subtitle", overlay: "logo" };
    editorUi.timeline.innerHTML = `
      <div id="editorPlayhead" class="editor-playhead"></div>
      ${manifest.tracks
        .map(
          (track) => `
            <div class="editor-track ${trackClasses[track.type] || ""}">
              <span class="editor-track-label">${escapeHtml(track.label)}</span>
              <div class="editor-track-lane"><div class="editor-track-clip">${escapeHtml(track.label)}</div></div>
            </div>
          `,
        )
        .join("")}
    `;
    editorUi.timelineTitle.textContent = `${manifest.project} · ${formatTime(manifest.duration)}`;
    updatePlayhead();
  }

  function resetEditor(message = "Chọn project ở Workspace") {
    stopPreviewLoop();
    editorState.project = "";
    editorState.manifest = null;
    editorState.cues = [];
    editorState.voiceCues = [];
    editorState.subtitleFrameKey = "";
    editorState.previewMode = "edit";
    editorUi.projectBadge.textContent = "Chưa chọn project";
    editorUi.empty.classList.remove("hidden");
    editorUi.empty.querySelector("strong").textContent = message;
    editorUi.assets.classList.add("hidden");
    editorUi.video.removeAttribute("src");
    editorUi.voice.removeAttribute("src");
    editorUi.logo.removeAttribute("src");
    editorUi.subtitle.replaceChildren();
    editorUi.canvasEmpty.classList.remove("hidden");
    editorUi.playBtn.disabled = true;
    editorUi.scrubber.disabled = true;
    editorUi.manifestBtn.disabled = true;
    editorUi.renderBtn.disabled = true;
    editorUi.previewEditBtn.disabled = true;
    editorUi.previewFinalBtn.disabled = true;
    editorUi.timeline.innerHTML = '<div class="editor-timeline-empty">Timeline sẽ xuất hiện sau khi tải project.</div>';
    editorUi.timelineTitle.textContent = "Chưa tải project";
    setStageStatus("Chờ project", false);
  }

  function setStageStatus(text, ready = false) {
    editorUi.stageStatus.textContent = text;
    editorUi.stageStatus.closest(".editor-stage-status")?.classList.toggle("ready", ready);
  }

  function missingCompositionAssets(manifest) {
    return [
      !manifest.assets.subtitle && "SRT Việt",
      !manifest.assets.voice && "giọng lồng tiếng",
    ].filter(Boolean);
  }

  function selectPreviewMode(mode) {
    if (!editorState.manifest) return;
    const manifest = editorState.manifest;
    const final = mode === "final" && Boolean(manifest.assets.finalVideo);
    editorState.previewMode = final ? "final" : "edit";
    editorUi.video.pause();
    editorUi.voice.pause();
    const asset = final ? manifest.assets.finalVideo : manifest.source;
    editorUi.video.src = `${asset.url}?v=${editorState.mediaVersion}`;
    editorUi.video.volume = final ? 1 : Number(editorUi.sourceVolume.value) / 100;
    editorUi.scrubber.value = 0;
    editorUi.currentTime.textContent = formatTime(0);
    editorUi.previewEditBtn.classList.toggle("active", !final);
    editorUi.previewFinalBtn.classList.toggle("active", final);
    editorUi.previewEditBtn.setAttribute("aria-pressed", String(!final));
    editorUi.previewFinalBtn.setAttribute("aria-pressed", String(final));
    editorUi.logo.style.display = final ? "none" : editorUi.logoEnabled.checked && manifest.assets.logo ? "block" : "none";
    updateSubtitle(true);
    const missing = missingCompositionAssets(manifest);
    setStageStatus(missing.length ? `Thiếu ${missing.join(" và ")} · chạy lại pipeline`
      : final ? "Đang xem video final" : "Đang xem bản dựng", !missing.length);
  }

  function applyManifestSettings(settings) {
    const subtitle = settings.subtitle;
    const logo = settings.logo;
    const audio = settings.audio;
    editorUi.subtitleEnabled.checked = subtitle.enabled;
    editorUi.subtitleTemplate.value = subtitle.template || "classic";
    editorUi.subtitleSize.value = subtitle.fontSize;
    editorUi.subtitleMargin.value = subtitle.marginBottom;
    editorUi.subtitleColor.value = subtitle.color;
    editorUi.subtitleAccentColor.value = subtitle.accentColor || "#FACC15";
    editorUi.subtitleOutlineColor.value = subtitle.outlineColor || "#050816";
    editorUi.subtitleBackground.value = subtitle.background;
    editorUi.subtitleOpacity.value = Math.round(subtitle.backgroundOpacity * 100);
    editorUi.logoEnabled.checked = logo.enabled;
    editorUi.logoPosition.value = logo.position;
    editorUi.logoWidth.value = logo.width;
    editorUi.logoOpacity.value = Math.round(logo.opacity * 100);
    editorUi.voiceVolume.value = Math.round(audio.voiceVolume * 100);
    editorUi.sourceVolume.value = Math.round(audio.sourceVolume * 100);
    updatePreviewStyles();
  }

  async function loadEditorProject(force = false, includeRenderStatus = true) {
    const project = selectedProject();
    if (!project) {
      resetEditor();
      return;
    }
    if (!force && editorState.project === project && editorState.manifest) return;
    setStageStatus("Đang tải project...", false);
    editorUi.projectBadge.textContent = project;
    try {
      const manifest = await editorApi(`/api/editor/project/${encodeURIComponent(project)}`);
      editorState.project = project;
      editorState.manifest = manifest;
      editorState.previewMode = "edit";
      editorState.mediaVersion = Date.now();
      const subtitleTrack = manifest.tracks.find((track) => track.type === "subtitle");
      editorState.cues = manifest.assets.subtitle ? subtitleTrack?.clips || [] : [];
      editorState.voiceCues = manifest.assets.voice ? subtitleTrack?.voiceClips || [] : [];
      editorUi.projectBadge.textContent = manifest.project;
      editorUi.empty.classList.add("hidden");
      editorUi.assets.classList.remove("hidden");
      assetRows(manifest);
      renderTimeline(manifest);
      applyManifestSettings(manifest.settings);

      editorUi.voice.src = manifest.assets.voice ? `${manifest.assets.voice.url}?v=${editorState.mediaVersion}` : "";
      editorUi.logo.src = manifest.assets.logo ? `${manifest.assets.logo.url}?v=${editorState.mediaVersion}` : "";
      selectPreviewMode(manifest.assets.finalVideo && !missingCompositionAssets(manifest).length ? "final" : "edit");
      editorUi.canvasEmpty.classList.add("hidden");
      editorUi.playBtn.disabled = false;
      editorUi.scrubber.disabled = false;
      editorUi.manifestBtn.disabled = false;
      editorUi.renderBtn.disabled = Boolean(missingCompositionAssets(manifest).length);
      editorUi.previewEditBtn.disabled = false;
      editorUi.previewFinalBtn.disabled = !manifest.assets.finalVideo;
      editorUi.duration.textContent = formatTime(manifest.duration);
      editorUi.scrubber.value = 0;
      if (missingCompositionAssets(manifest).length) {
        setRenderStatus("error", "Pipeline chưa hoàn tất", "Project còn thiếu SRT Việt hoặc giọng lồng tiếng. Xem tab Logs rồi chạy lại pipeline.");
      } else if (includeRenderStatus) {
        await refreshRenderStatus();
      }
    } catch (error) {
      resetEditor("Project chưa đủ output");
      setRenderStatus("error", "Không tải được project", error.message);
    }
  }

  function updatePreviewStyles() {
    const template = editorUi.subtitleTemplate.value || "classic";
    const subtitleOpacity = Number(editorUi.subtitleOpacity.value) / 100;
    editorUi.subtitleOpacityValue.textContent = `${editorUi.subtitleOpacity.value}%`;
    editorUi.subtitle.dataset.template = template;
    editorUi.subtitle.style.setProperty("--subtitle-color", editorUi.subtitleColor.value);
    editorUi.subtitle.style.setProperty("--subtitle-accent", editorUi.subtitleAccentColor.value);
    editorUi.subtitle.style.setProperty("--subtitle-outline", editorUi.subtitleOutlineColor.value);
    editorUi.subtitle.style.color = editorUi.subtitleColor.value;
    editorUi.subtitle.style.backgroundColor = colorWithAlpha(editorUi.subtitleBackground.value, subtitleOpacity);
    const templateScale = template === "pop" ? 1.25 : template === "neon" ? 1.08 : 1;
    editorUi.subtitle.style.fontSize = `${Math.max(10, Number(editorUi.subtitleSize.value) * 0.31 * templateScale)}px`;
    editorUi.subtitle.style.bottom = `${Math.max(2, (Number(editorUi.subtitleMargin.value) / 1920) * 100)}%`;
    editorUi.subtitleTemplateButtons.forEach((button) => {
      button.classList.toggle("active", button.dataset.subtitleTemplate === template);
    });
    editorState.subtitleFrameKey = "";
    updateSubtitle(true);

    editorUi.logoWidthValue.textContent = `${editorUi.logoWidth.value}px`;
    editorUi.logoOpacityValue.textContent = `${editorUi.logoOpacity.value}%`;
    editorUi.logo.style.display = editorState.previewMode === "final" ? "none"
      : editorUi.logoEnabled.checked && editorUi.logo.src ? "block" : "none";
    editorUi.logo.style.width = `${(Number(editorUi.logoWidth.value) / 1080) * 100}%`;
    editorUi.logo.style.opacity = String(Number(editorUi.logoOpacity.value) / 100);
    positionLogo(editorUi.logoPosition.value);

    editorUi.voiceVolumeValue.textContent = `${editorUi.voiceVolume.value}%`;
    editorUi.sourceVolumeValue.textContent = `${editorUi.sourceVolume.value}%`;
    editorUi.voice.volume = Math.min(1, Number(editorUi.voiceVolume.value) / 100);
    editorUi.video.volume = editorState.previewMode === "final" ? 1 : Number(editorUi.sourceVolume.value) / 100;
  }

  function colorWithAlpha(hex, alpha) {
    const value = hex.replace("#", "");
    const red = parseInt(value.slice(0, 2), 16);
    const green = parseInt(value.slice(2, 4), 16);
    const blue = parseInt(value.slice(4, 6), 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
  }

  function positionLogo(position) {
    const rules = {
      "top-right": { top: "3%", right: "4%", bottom: "auto", left: "auto" },
      "top-left": { top: "3%", left: "4%", bottom: "auto", right: "auto" },
      "bottom-right": { bottom: "3%", right: "4%", top: "auto", left: "auto" },
      "bottom-left": { bottom: "3%", left: "4%", top: "auto", right: "auto" },
    };
    Object.assign(editorUi.logo.style, rules[position] || rules["top-right"]);
  }

  function currentCue(seconds, template) {
    const currentMs = seconds * 1000;
    const cues = ["pop", "neon"].includes(template) && editorState.voiceCues.length
      ? editorState.voiceCues
      : editorState.cues;
    return cues.find((cue) => currentMs >= cue.startMs && currentMs < cue.endMs);
  }

  function wordTimingWeight(word) {
    const cleanWord = word.replace(/[.,!?;:…]/g, "");
    const lengthBonus = Math.min(0.35, Math.max(0, cleanWord.length - 2) * 0.05);
    const pauseBonus = /[,\.!?;:…]$/.test(word) ? 0.16 : 0;
    return 1 + lengthBonus + pauseBonus;
  }

  function activeWordIndex(cue, currentMs, accelerated = false) {
    const words = cue.text.replace(/\s+/g, " ").trim().split(" ").filter(Boolean);
    if (!words.length) return { words, index: 0 };
    const weights = words.map(wordTimingWeight);
    const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
    const duration = Math.max(1, cue.endMs - cue.startMs);
    const paceRatio = accelerated ? 0.92 : 1;
    const leadMs = accelerated ? Math.min(90, duration * 0.08) : 0;
    const progress = Math.max(0, Math.min(1, (currentMs - cue.startMs + leadMs) / (duration * paceRatio)));
    const target = progress * totalWeight;
    let accumulated = 0;
    let index = words.length - 1;
    for (let wordIndex = 0; wordIndex < weights.length; wordIndex += 1) {
      accumulated += weights[wordIndex];
      if (target < accumulated) {
        index = wordIndex;
        break;
      }
    }
    return { words, index };
  }

  function appendSubtitleWord(word, className) {
    const span = document.createElement("span");
    span.className = `editor-subtitle-word ${className}`.trim();
    span.textContent = word;
    if (editorUi.subtitle.childNodes.length) editorUi.subtitle.append(document.createTextNode(" "));
    editorUi.subtitle.append(span);
  }

  function updateSubtitle(force = false) {
    const template = editorUi.subtitleTemplate.value || "classic";
    const cue = currentCue(editorUi.video.currentTime, template);
    if (editorState.previewMode === "final" || !cue?.text || !editorUi.subtitleEnabled.checked) {
      editorState.subtitleFrameKey = "";
      editorUi.subtitle.replaceChildren();
      editorUi.subtitle.style.display = "none";
      return;
    }
    const { words, index } = activeWordIndex(
      cue,
      editorUi.video.currentTime * 1000,
      ["pop", "neon"].includes(template),
    );
    const frameKey = `${cue.id}:${template}:${template === "classic" ? 0 : index}`;
    if (!force && frameKey === editorState.subtitleFrameKey) return;
    editorState.subtitleFrameKey = frameKey;
    editorUi.subtitle.replaceChildren();
    if (template === "classic") {
      editorUi.subtitle.textContent = cue.text;
    } else if (template === "pop") {
      appendSubtitleWord(words[index], "current");
    } else {
      const visibleWords = template === "reveal" ? words.slice(0, index + 1) : words;
      visibleWords.forEach((word, wordIndex) => {
        const originalIndex = template === "reveal" ? wordIndex : wordIndex;
        const stateClass = originalIndex < index ? "past" : originalIndex === index ? "current" : "future";
        appendSubtitleWord(word, stateClass);
      });
    }
    editorUi.subtitle.style.display = "block";
  }

  function updatePlayhead() {
    const duration = editorState.manifest?.duration || editorUi.video.duration || 0;
    const progress = duration ? Math.min(1, editorUi.video.currentTime / duration) : 0;
    editorUi.scrubber.value = Math.round(progress * 1000);
    editorUi.currentTime.textContent = formatTime(editorUi.video.currentTime);
    const playhead = byId("editorPlayhead");
    if (playhead) playhead.style.left = `calc(90px + (100% - 102px) * ${progress})`;
    updateSubtitle();
  }

  function stopPreviewLoop() {
    if (editorState.previewFrame !== null) cancelAnimationFrame(editorState.previewFrame);
    editorState.previewFrame = null;
  }

  function startPreviewLoop() {
    stopPreviewLoop();
    const tick = () => {
      updatePlayhead();
      if (!editorUi.video.paused && !editorUi.video.ended) {
        editorState.previewFrame = requestAnimationFrame(tick);
      } else {
        editorState.previewFrame = null;
      }
    };
    editorState.previewFrame = requestAnimationFrame(tick);
  }

  async function togglePlayback() {
    if (!editorState.manifest) return;
    if (editorUi.video.paused) {
      if (editorState.previewMode === "final") {
        await editorUi.video.play();
      } else {
        editorUi.voice.currentTime = editorUi.video.currentTime;
        await Promise.allSettled([editorUi.video.play(), editorUi.voice.src ? editorUi.voice.play() : Promise.resolve()]);
      }
    } else {
      editorUi.video.pause();
      editorUi.voice.pause();
    }
  }

  function playbackIcon(playing) {
    editorUi.playBtn.innerHTML = playing
      ? '<svg viewBox="0 0 24 24"><path d="M8 5v14"/><path d="M16 5v14"/></svg>'
      : '<svg viewBox="0 0 24 24"><path d="m7 4 13 8-13 8V4Z"/></svg>';
  }

  function gatherSettings() {
    const quality = editorUi.quality.value;
    return {
      subtitle: {
        enabled: editorUi.subtitleEnabled.checked,
        font: "Arial",
        fontSize: Number(editorUi.subtitleSize.value),
        template: editorUi.subtitleTemplate.value || "classic",
        color: editorUi.subtitleColor.value,
        accentColor: editorUi.subtitleAccentColor.value,
        outlineColor: editorUi.subtitleOutlineColor.value,
        background: editorUi.subtitleBackground.value,
        backgroundOpacity: Number(editorUi.subtitleOpacity.value) / 100,
        marginBottom: Number(editorUi.subtitleMargin.value),
      },
      logo: {
        enabled: editorUi.logoEnabled.checked,
        width: Number(editorUi.logoWidth.value),
        opacity: Number(editorUi.logoOpacity.value) / 100,
        position: editorUi.logoPosition.value,
        margin: 48,
      },
      audio: {
        voiceVolume: Number(editorUi.voiceVolume.value) / 100,
        sourceVolume: Number(editorUi.sourceVolume.value) / 100,
      },
      export: {
        preset: quality,
        crf: quality === "slow" ? 18 : quality === "veryfast" ? 23 : 20,
      },
    };
  }

  function setRenderStatus(mode, title, detail) {
    editorUi.renderStatus.classList.remove("running", "done", "error");
    if (mode) editorUi.renderStatus.classList.add(mode);
    const titleNode = editorUi.renderStatus.querySelector("strong");
    const detailNode = editorUi.renderStatus.querySelector("small");
    titleNode.textContent = title;
    detailNode.textContent = detail;
  }

  async function startRender() {
    if (!editorState.project) return;
    editorUi.renderBtn.disabled = true;
    setRenderStatus("running", "Đang render video final", "FFmpeg đang dựng canvas, subtitle, logo và trộn audio...");
    try {
      const started = await editorApi("/api/editor/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project: editorState.project, settings: gatherSettings() }),
      });
      editorState.pendingRenderProject = started.project || editorState.project;
      editorState.completedRenderKey = null;
      beginRenderPolling();
    } catch (error) {
      editorUi.renderBtn.disabled = false;
      setRenderStatus("error", "Không thể bắt đầu render", error.message);
    }
  }

  function beginRenderPolling() {
    clearInterval(editorState.renderTimer);
    editorState.renderTimer = setInterval(refreshRenderStatus, 1500);
    refreshRenderStatus();
  }

  async function refreshRenderStatus() {
    try {
      const status = await editorApi("/api/editor/render");
      const renderKey = `${status.project}:${status.startedAt}`;
      if (status.running) {
        if (renderKey !== editorState.completedRenderKey) {
          editorState.pendingRenderProject = status.project;
        }
        editorUi.renderBtn.disabled = true;
        const lastLog = status.logs?.at(-1) || "Đang xử lý...";
        setRenderStatus("running", `Đang render ${status.project || "video"}`, lastLog);
        return;
      }
      clearInterval(editorState.renderTimer);
      editorState.renderTimer = null;
       editorUi.renderBtn.disabled = !editorState.manifest || Boolean(missingCompositionAssets(editorState.manifest).length);
      if (status.error) {
        editorState.pendingRenderProject = null;
        if (status.project === editorState.project) {
          setRenderStatus("error", "Render thất bại", status.error);
        }
      } else if (status.output) {
        if (status.project === editorState.project) {
          setRenderStatus("done", "Đã tạo video_final.mp4", "Mở Xuất bản ở cột phải để kiểm tra và đăng video.");
        }
        if (editorState.pendingRenderProject === status.project && renderKey !== editorState.completedRenderKey) {
          editorState.pendingRenderProject = null;
          editorState.completedRenderKey = renderKey;
           await loadEditorProject(true, false);
           document.dispatchEvent(new CustomEvent("shorts:editor-rendered", { detail: { project: status.project } }));
        }
      }
    } catch (error) {
      setRenderStatus("error", "Không đọc được trạng thái render", error.message);
    }
  }

  function downloadManifest() {
    if (!editorState.manifest) return;
    const blob = new Blob([JSON.stringify({ ...editorState.manifest, settings: gatherSettings() }, null, 2)], {
      type: "application/json;charset=utf-8",
    });
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(blob);
    anchor.download = `${editorState.project}.opencut.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(anchor.href), 500);
  }

  async function openOpenCut() {
    try {
      const config = await editorApi("/api/config");
      const openCutUrl = config.settings?.openCutUrl || "http://localhost:5173";
      window.open(openCutUrl, "_blank", "noopener,noreferrer");
    } catch (error) {
      setRenderStatus("error", "Không mở được OpenCut Labs", error.message);
    }
  }

  const previewInputs = [
    editorUi.subtitleEnabled,
    editorUi.subtitleSize,
    editorUi.subtitleMargin,
    editorUi.subtitleColor,
    editorUi.subtitleAccentColor,
    editorUi.subtitleOutlineColor,
    editorUi.subtitleBackground,
    editorUi.subtitleOpacity,
    editorUi.logoEnabled,
    editorUi.logoPosition,
    editorUi.logoWidth,
    editorUi.logoOpacity,
    editorUi.voiceVolume,
    editorUi.sourceVolume,
  ];
  previewInputs.forEach((input) => {
    const refreshPreview = () => {
      if (editorState.previewMode === "final") selectPreviewMode("edit");
      updatePreviewStyles();
    };
    input?.addEventListener("input", refreshPreview);
    input?.addEventListener("change", refreshPreview);
  });

  editorUi.subtitleTemplateButtons.forEach((button) => {
    button.addEventListener("click", () => {
      editorUi.subtitleTemplate.value = button.dataset.subtitleTemplate || "classic";
      if (editorState.previewMode === "final") selectPreviewMode("edit");
      updatePreviewStyles();
    });
  });

  editorUi.playBtn.addEventListener("click", togglePlayback);
  editorUi.previewEditBtn.addEventListener("click", () => selectPreviewMode("edit"));
  editorUi.previewFinalBtn.addEventListener("click", () => selectPreviewMode("final"));
  editorUi.video.addEventListener("play", () => {
    playbackIcon(true);
    startPreviewLoop();
  });
  editorUi.video.addEventListener("pause", () => {
    stopPreviewLoop();
    playbackIcon(false);
    editorUi.voice.pause();
    updatePlayhead();
  });
  editorUi.video.addEventListener("ended", () => {
    stopPreviewLoop();
    playbackIcon(false);
    editorUi.voice.pause();
  });
  editorUi.video.addEventListener("timeupdate", () => {
    updatePlayhead();
    if (!editorUi.voice.paused && Math.abs(editorUi.voice.currentTime - editorUi.video.currentTime) > 0.18) {
      editorUi.voice.currentTime = editorUi.video.currentTime;
    }
  });
  editorUi.video.addEventListener("seeked", () => {
    editorUi.voice.currentTime = editorUi.video.currentTime;
    updatePlayhead();
  });
  editorUi.scrubber.addEventListener("input", () => {
    const duration = editorState.manifest?.duration || 0;
    editorUi.video.currentTime = (Number(editorUi.scrubber.value) / 1000) * duration;
  });
  editorUi.fitBtn.addEventListener("click", () => {
    editorUi.canvas.classList.toggle("fit");
    editorUi.fitBtn.classList.toggle("active", editorUi.canvas.classList.contains("fit"));
    editorUi.fitBtn.textContent = editorUi.canvas.classList.contains("fit") ? "Fit" : "Cover";
  });
  editorUi.focusBtn.addEventListener("click", () => {
    const focused = editorUi.shell.classList.toggle("preview-focus");
    editorUi.focusBtn.classList.toggle("active", focused);
    editorUi.focusBtn.setAttribute("aria-pressed", String(focused));
    editorUi.focusBtn.title = focused ? "Thoát chế độ phóng lớn" : "Phóng lớn vùng preview";
    if (focused) editorUi.shell.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  editorUi.muteBtn.addEventListener("click", () => {
    const muted = !editorUi.video.muted;
    editorUi.video.muted = muted;
    editorUi.voice.muted = muted;
    editorUi.muteBtn.classList.toggle("active", muted);
  });
  editorUi.reloadBtn.addEventListener("click", () => loadEditorProject(true));
  editorUi.manifestBtn.addEventListener("click", downloadManifest);
  editorUi.renderBtn.addEventListener("click", startRender);
  editorUi.openCutBtn.addEventListener("click", openOpenCut);

  document.addEventListener("shorts:view-change", (event) => {
    if (event.detail?.name === "overview") loadEditorProject();
  });
  document.addEventListener("shorts:selection-changed", () => {
    if (editorUi.view.closest(".view")?.classList.contains("active")) loadEditorProject(true);
  });

  resetEditor();
})();

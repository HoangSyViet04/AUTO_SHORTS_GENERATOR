(function () {
  const escapeHtml = (value) =>
    String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const defaultVoices = [
    {
      id: "",
      name: "Adam",
      description: "Giọng adam của ElevenLabs, hợp review sản phẩm.",
      category: "default",
      labels: { gender: "nam", style: "review" },
      previewUrl: "",
    },
    {
      id: "",
      name: "Ethan",
      description: "Preset tham khảo: nam trầm ấm, kể chuyện nhẹ và rõ.",
      category: "preset",
      labels: { gender: "nam", style: "story" },
      previewUrl: "",
    },
    {
      id: "",
      name: "Brian",
      description: "Preset tham khảo: nam truyền cảm, nhấn tốt ở đoạn hook.",
      category: "preset",
      labels: { gender: "nam", style: "ads" },
      previewUrl: "",
    },
  ];

  function normalizeVoices(voices) {
    return (voices?.length ? voices : defaultVoices).map((voice) => ({
      id: voice.id || "",
      name: voice.name || "Unnamed voice",
      description: voice.description || "Giọng nói từ thư viện API.",
      category: voice.category || "voice",
      labels: voice.labels || {},
      previewUrl: voice.previewUrl || voice.preview_url || "",
    }));
  }

  function voiceOptionHtml(voices) {
    return normalizeVoices(voices)
      .map((voice) => `<option value="${escapeHtml(voice.id)}">${escapeHtml(voice.name)}</option>`)
      .join("");
  }

  function voiceLibraryHtml(voices, query = "") {
    const normalizedQuery = query.trim().toLowerCase();
    const filtered = normalizeVoices(voices).filter((voice) => {
      const text = `${voice.name} ${voice.description} ${Object.values(voice.labels).join(" ")}`.toLowerCase();
      return !normalizedQuery || text.includes(normalizedQuery);
    });

    if (!filtered.length) {
      return `<div class="empty">Không tìm thấy giọng phù hợp.</div>`;
    }

    return filtered
      .map((voice) => {
        const tags = Object.values(voice.labels).filter(Boolean).slice(0, 3);
        const safeId = escapeHtml(voice.id);
        const safePreview = escapeHtml(voice.previewUrl);
        return `
          <article class="voice-library-row" data-voice-id="${safeId}" data-preview-url="${safePreview}">
            <button class="voice-play-button" type="button" data-voice-action="preview" aria-label="Nghe thử ${escapeHtml(voice.name)}">▶</button>
            <div>
              <strong>${escapeHtml(voice.name)}</strong>
              <p>${escapeHtml(voice.description)}</p>
              <div class="voice-row-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("") || `<span>${escapeHtml(voice.category)}</span>`}</div>
            </div>
            <button class="voice-use-button" type="button" data-voice-action="use">Dùng giọng</button>
          </article>
        `;
      })
      .join("");
  }

  function historyHtml(videos, formatBytes, formatDate) {
    if (!videos.length) {
      return `<div class="empty">Chưa có video trong input_videos để hiển thị lịch sử.</div>`;
    }

    return videos
      .map((video) => {
        const readyCount = ["video", "subtitle", "audio", "logo"].filter((key) => video.complete?.[key]).length;
        const status = readyCount === 4 ? "Hoàn thành" : "Chưa đủ output";
        return `
          <article class="history-row">
            <div class="history-icon">${readyCount}/4</div>
            <div>
              <strong>${escapeHtml(video.name)}</strong>
              <small>${formatBytes(video.size)} • ${formatDate(video.modified)} • ${status}</small>
            </div>
            <button class="secondary-action" data-history-video="${escapeHtml(video.stem)}">Mở output</button>
          </article>
        `;
      })
      .join("");
  }

  window.VoiceModules = {
    defaultVoices,
    normalizeVoices,
    voiceOptionHtml,
    voiceLibraryHtml,
    historyHtml,
  };
})();

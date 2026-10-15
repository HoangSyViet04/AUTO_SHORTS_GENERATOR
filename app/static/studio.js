(() => {
  const overview = document.getElementById("overviewView");
  const editorView = document.getElementById("editorView");
  const publishView = document.getElementById("publishView");
  const overviewGrid = overview?.firstElementChild;
  const editorShell = editorView?.querySelector(".editor-shell");
  const workspace = editorShell?.querySelector(".editor-workspace");
  if (!overviewGrid || !editorShell || !workspace || !publishView) return;

  const inputColumn = overviewGrid.children[0];
  const pipelinePanel = overviewGrid.children[1];
  const outputPanel = overviewGrid.children[2];
  const inputPanel = inputColumn.children[0];
  const filesPanel = inputColumn.children[1];
  const assetsPanel = workspace.querySelector(".editor-assets-panel");
  const stage = workspace.querySelector(".editor-stage-panel");
  const inspector = workspace.querySelector(".editor-inspector");
  const inspectorHeading = inspector.querySelector(".editor-panel-head");
  const controlSections = [...inspector.querySelectorAll(":scope > .editor-control-section")];
  const exportCard = inspector.querySelector(".editor-export-card");

  editorView.classList.remove("view");
  editorView.classList.add("studio-host");
  publishView.classList.remove("view");
  publishView.classList.add("studio-publish-view");
  editorShell.classList.add("studio-shell");
  editorShell.querySelector(".editor-kicker").textContent = "AUTO SHORTS · COMPOSITION STUDIO";
  editorShell.querySelector(".editor-heading p").textContent = "Chọn video → xử lý → chỉnh sửa → xuất bản, trên cùng một màn hình.";
  assetsPanel.querySelector(".editor-panel-head h3").textContent = "Tài nguyên dựng";
  inspectorHeading.querySelector("h3").textContent = "Inspector & Publish";
  inspectorHeading.querySelector("p").textContent = "Nội dung, hình ảnh, âm thanh và đăng bài";

  const left = document.createElement("aside");
  left.className = "studio-left";
  left.setAttribute("aria-label", "Project và pipeline");
  const workflow = document.createElement("details");
  workflow.className = "studio-workflow";
  workflow.open = true;
  const workflowSummary = document.createElement("summary");
  workflowSummary.textContent = "Tiến trình xử lý";
  workflow.append(workflowSummary, pipelinePanel);
  left.append(inputPanel, assetsPanel, workflow, filesPanel);

  const progress = document.createElement("div");
  progress.className = "studio-progress";
  progress.setAttribute("aria-label", "Tiến trình dựng video");
  const workflowCards = [...pipelinePanel.querySelectorAll(".workflow-card")];
  workflowCards.forEach((card) => {
    const item = document.createElement("span");
    item.className = "studio-progress-step";
    item.dataset.progressStep = card.dataset.step;
    item.innerHTML = `<i></i><span>${card.querySelector("h3").textContent}</span>`;
    progress.append(item);
  });
  editorShell.querySelector(".editor-header").insertBefore(progress, editorShell.querySelector(".editor-header-actions"));
  const updateProgress = () => {
    workflowCards.forEach((card) => {
      const item = progress.querySelector(`[data-progress-step="${card.dataset.step}"]`);
      item.classList.toggle("done", card.classList.contains("done"));
      item.classList.toggle("active", card.classList.contains("active"));
      item.classList.toggle("error", card.classList.contains("error"));
    });
  };
  new MutationObserver(updateProgress).observe(pipelinePanel, { attributes: true, attributeFilter: ["class"], subtree: true });
  updateProgress();

  const tabs = document.createElement("div");
  tabs.className = "studio-tabs";
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "Công cụ studio");
  const panes = {};
  const tabNames = [
    ["content", "Nội dung"],
    ["subtitle", "Phụ đề"],
    ["audio", "Âm thanh"],
    ["publish", "Xuất bản"],
  ];
  tabNames.forEach(([name, label]) => {
    const tab = document.createElement("button");
    tab.type = "button";
    tab.className = "studio-tab";
    tab.id = `studio-tab-${name}`;
    tab.dataset.studioPane = name;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", `studio-pane-${name}`);
    tab.textContent = label;
    tabs.append(tab);

    const pane = document.createElement("div");
    pane.className = "studio-pane";
    pane.id = `studio-pane-${name}`;
    pane.setAttribute("role", "tabpanel");
    pane.setAttribute("aria-labelledby", tab.id);
    panes[name] = pane;
  });
  panes.content.append(outputPanel);
  panes.subtitle.append(controlSections[0]);
  panes.audio.append(controlSections[1], controlSections[2], exportCard);
  panes.publish.append(publishView);
  const publishShell = publishView.querySelector(".publish-center-shell");
  publishShell.prepend(publishShell.querySelector(".publish-integrations"));
  inspector.replaceChildren(inspectorHeading, tabs, ...tabNames.map(([name]) => panes[name]));
  inspector.classList.add("studio-inspector");
  const resizer = document.createElement("div");
  resizer.className = "studio-resizer";
  resizer.setAttribute("role", "separator");
  resizer.setAttribute("aria-label", "Chỉnh độ rộng Inspector");
  resizer.setAttribute("aria-orientation", "vertical");
  resizer.tabIndex = 0;
  workspace.replaceChildren(left, stage, resizer, inspector);
  overview.replaceChildren(editorView);

  const inspectorWidthKey = "studio-inspector-width";
  const savedInspectorWidth = Number(localStorage.getItem(inspectorWidthKey));
  function inspectorBounds() {
    const freeWidth = workspace.clientWidth - left.getBoundingClientRect().width - 360 - 3 * 8 - 10;
    const max = Math.max(340, Math.min(900, freeWidth));
    return { min: Math.min(420, max), max };
  }
  function setInspectorWidth(width, persist = false) {
    const { min, max } = inspectorBounds();
    const next = Math.round(Math.max(min, Math.min(max, width)));
    workspace.style.setProperty("--studio-inspector-width", `${next}px`);
    resizer.setAttribute("aria-valuemin", String(min));
    resizer.setAttribute("aria-valuemax", String(max));
    resizer.setAttribute("aria-valuenow", String(next));
    if (persist) localStorage.setItem(inspectorWidthKey, String(next));
  }
  setInspectorWidth(savedInspectorWidth > 0 ? savedInspectorWidth : inspector.getBoundingClientRect().width);
  resizer.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    resizer.setPointerCapture(event.pointerId);
    workspace.classList.add("studio-resizing");
  });
  resizer.addEventListener("pointermove", (event) => {
    if (!resizer.hasPointerCapture(event.pointerId)) return;
    setInspectorWidth(workspace.getBoundingClientRect().right - event.clientX - 8);
  });
  function stopResizing(event) {
    if (!resizer.hasPointerCapture(event.pointerId)) return;
    resizer.releasePointerCapture(event.pointerId);
    workspace.classList.remove("studio-resizing");
    localStorage.setItem(inspectorWidthKey, resizer.getAttribute("aria-valuenow"));
  }
  resizer.addEventListener("pointerup", stopResizing);
  resizer.addEventListener("pointercancel", stopResizing);
  resizer.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    setInspectorWidth(Number(resizer.getAttribute("aria-valuenow") || inspector.getBoundingClientRect().width)
      + (event.key === "ArrowLeft" ? 24 : -24), true);
  });
  window.addEventListener("resize", () => {
    if (workspace.style.getPropertyValue("--studio-inspector-width")) {
      setInspectorWidth(Number(resizer.getAttribute("aria-valuenow")));
    }
  });

  function activatePane(name, focus = false) {
    const selected = panes[name] ? name : "content";
    tabs.querySelectorAll(".studio-tab").forEach((tab) => {
      const active = tab.dataset.studioPane === selected;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active && focus) tab.focus();
    });
    Object.entries(panes).forEach(([paneName, pane]) => {
      pane.hidden = paneName !== selected;
    });
    localStorage.setItem("studio-pane", selected);
  }

  tabs.addEventListener("click", (event) => {
    const tab = event.target.closest(".studio-tab");
    if (tab) activatePane(tab.dataset.studioPane);
  });
  tabs.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const buttons = [...tabs.querySelectorAll(".studio-tab")];
    const current = buttons.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
      : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
    activatePane(buttons[next].dataset.studioPane, true);
  });

  activatePane(localStorage.getItem("studio-pane") || "content");
  window.ShortsStudio = { activatePane };
})();

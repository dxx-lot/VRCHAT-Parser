"use strict";

(() => {
  const form = document.getElementById("parseForm");
  const urlInput = document.getElementById("mediaUrl");
  const cookieInput = document.getElementById("cookieInput");
  const biliMode = document.getElementById("biliMode");
  const parseButton = document.getElementById("parseButton");
  const status = document.getElementById("status");
  const resultPanel = document.getElementById("resultPanel");
  const resultTitle = document.getElementById("resultTitle");
  const resultMeta = document.getElementById("resultMeta");
  const mediaLink = document.getElementById("mediaLink");
  const copyButton = document.getElementById("copyButton");
  const rawJson = document.getElementById("rawJson");
  const tokenMeta = document.querySelector('meta[name="local-token"]');

  let activeController = null;
  let activeTimeoutId = null;
  let requestNumber = 0;
  let currentMediaUrl = "";

  function setStatus(message, kind = "info") {
    status.textContent = message;
    status.dataset.kind = kind;
  }

  function clearResult() {
    resultPanel.hidden = true;
    resultTitle.textContent = "";
    resultMeta.textContent = "";
    mediaLink.textContent = "";
    mediaLink.removeAttribute("href");
    mediaLink.hidden = true;
    rawJson.textContent = "";
    currentMediaUrl = "";
  }

  function safeHttpUrl(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      const parsed = new URL(value);
      if ((parsed.protocol !== "http:" && parsed.protocol !== "https:") || !parsed.hostname || parsed.username || parsed.password) return null;
      return parsed.href;
    } catch {
      return null;
    }
  }

  function renderResult(result) {
    const title = typeof result.title === "string" && result.title.trim() ? result.title : "未提供标题";
    const platform = typeof result.platform === "string" ? result.platform : "未知平台";
    const author = typeof result.author === "string" && result.author.trim() ? result.author : "未提供作者";
    resultTitle.textContent = title;
    resultMeta.textContent = `${platform} · ${author}`;

    const allowedUrl = safeHttpUrl(result.direct_url);
    if (allowedUrl) {
      currentMediaUrl = allowedUrl;
      mediaLink.href = allowedUrl;
      mediaLink.textContent = "打开解析地址 ↗";
      mediaLink.hidden = false;
    }
    rawJson.textContent = JSON.stringify(result, null, 2);
    resultPanel.hidden = false;
  }

  function cancelActiveRequest() {
    requestNumber += 1;
    if (activeTimeoutId !== null) window.clearTimeout(activeTimeoutId);
    activeTimeoutId = null;
    if (activeController) activeController.abort();
    activeController = null;
    parseButton.disabled = false;
    parseButton.querySelector(".button-label").textContent = "开始解析";
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    cancelActiveRequest();
    clearResult();

    const url = urlInput.value.trim();
    if (!urlInput.checkValidity()) {
      urlInput.reportValidity();
      setStatus("请填写有效的媒体链接。", "error");
      return;
    }

    const thisRequest = requestNumber;
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 40000);
    activeTimeoutId = timeoutId;
    activeController = controller;
    parseButton.disabled = true;
    parseButton.querySelector(".button-label").textContent = "正在解析…";
    setStatus("正在本机处理这条链接…");

    try {
      const token = tokenMeta ? tokenMeta.content : "";
      const response = await fetch("/api/parse", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-VRC-Local-Token": token,
        },
        body: JSON.stringify({ url, cookie: cookieInput.value, bili_mode: biliMode.value }),
        credentials: "omit",
        cache: "no-store",
        signal: controller.signal,
      });
      const payload = await response.json();
      if (thisRequest !== requestNumber) return;

      if (!response.ok || !payload || payload.ok !== true || !payload.result || typeof payload.result !== "object") {
        const message = payload && typeof payload.error === "string" ? payload.error : "解析未能完成，请检查链接后重试。";
        setStatus(message, "error");
        return;
      }

      renderResult(payload.result);
      setStatus("解析完成。结果仅保留在当前页面中。", "success");
    } catch (error) {
      if (thisRequest !== requestNumber) return;
      if (timedOut) {
        setStatus("解析超过 40 秒，已自动取消。请检查链接或稍后重试。", "error");
      } else if (error.name !== "AbortError") {
        setStatus("本机服务暂时无法完成解析，请确认服务正在运行后重试。", "error");
      }
    } finally {
      window.clearTimeout(timeoutId);
      if (thisRequest === requestNumber) {
        activeController = null;
        activeTimeoutId = null;
        parseButton.disabled = false;
        parseButton.querySelector(".button-label").textContent = "开始解析";
      }
    }
  });

  form.addEventListener("reset", () => {
    const wasActive = Boolean(activeController);
    cancelActiveRequest();
    clearResult();
    setStatus(wasActive ? "已取消解析并清空当前内容。" : "结果只显示在此页面，不会保存。");
  });

  copyButton.addEventListener("click", async () => {
    if (!currentMediaUrl) {
      setStatus("当前结果没有可复制的安全链接。", "error");
      return;
    }
    try {
      await navigator.clipboard.writeText(currentMediaUrl);
      setStatus("解析链接已复制。", "success");
    } catch {
      setStatus("无法访问剪贴板，请使用链接菜单手动复制。", "error");
    }
  });
})();

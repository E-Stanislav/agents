const PHASES = [
    { id: "analyzing", label: "Analyzing" },
    { id: "clarifying", label: "Clarifying" },
    { id: "architecting", label: "Architecting" },
    { id: "approving_architecture", label: "Approval" },
    { id: "coding", label: "Coding" },
    { id: "reviewing", label: "Reviewing" },
    { id: "testing", label: "Testing" },
    { id: "delivering", label: "Delivering" },
];

let ws = null;
let currentTaskId = null;

// DOM elements
const uploadSection = document.getElementById("upload-section");
const progressSection = document.getElementById("progress-section");
const resultSection = document.getElementById("result-section");
const fileInput = document.getElementById("file-input");
const mdInput = document.getElementById("md-input");
const startBtn = document.getElementById("start-btn");
const dropZone = document.getElementById("drop-zone");
const chatMessages = document.getElementById("chat-messages");
const chatInputArea = document.getElementById("chat-input-area");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");
const progressFill = document.getElementById("progress-fill");
const progressPhases = document.getElementById("progress-phases");
const archApproval = document.getElementById("arch-approval");
const archPlanContent = document.getElementById("arch-plan-content");
const archApprove = document.getElementById("arch-approve");
const archReject = document.getElementById("arch-reject");
const archFeedback = document.getElementById("arch-feedback");
const archSubmitFeedback = document.getElementById("arch-submit-feedback");
const downloadBtn = document.getElementById("download-btn");
const resultMessage = document.getElementById("result-message");
const historyList = document.getElementById("history-list");

// ── Session persistence ──

function saveSession(taskId) {
    sessionStorage.setItem("currentTaskId", taskId);
}

function clearSession() {
    sessionStorage.removeItem("currentTaskId");
}

function getSavedTaskId() {
    return sessionStorage.getItem("currentTaskId");
}

// ── Phase rendering ──

function initPhases() {
    progressPhases.innerHTML = PHASES.map(
        (p) => `<span class="phase-badge" data-phase="${p.id}">${p.label}</span>`
    ).join("");
}

function updatePhase(phaseId) {
    const phaseIndex = PHASES.findIndex((p) => p.id === phaseId);
    if (phaseIndex === -1) return;

    const progress = ((phaseIndex + 1) / PHASES.length) * 100;
    progressFill.style.width = `${progress}%`;

    document.querySelectorAll(".phase-badge").forEach((badge, i) => {
        badge.classList.remove("active", "done");
        if (i < phaseIndex) badge.classList.add("done");
        if (i === phaseIndex) badge.classList.add("active");
    });
}

function addChatMessage(text, type = "system") {
    const msg = document.createElement("div");
    msg.className = `chat-msg ${type}`;
    msg.textContent = text;
    chatMessages.appendChild(msg);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function showSection(section) {
    [uploadSection, progressSection, resultSection].forEach((s) =>
        s.classList.add("hidden")
    );
    section.classList.remove("hidden");
}

function checkInput() {
    startBtn.disabled = !mdInput.value.trim();
}

mdInput.addEventListener("input", checkInput);

// ── File upload ──

fileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
        mdInput.value = ev.target.result;
        checkInput();
    };
    reader.readAsText(file);
});

dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".md")) {
        const reader = new FileReader();
        reader.onload = (ev) => {
            mdInput.value = ev.target.result;
            checkInput();
        };
        reader.readAsText(file);
    }
});

// ── Start generation ──

startBtn.addEventListener("click", async () => {
    const content = mdInput.value.trim();
    if (!content) return;

    try {
        const res = await fetch("/api/tasks", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ md_content: content }),
        });
        const data = await res.json();
        if (!res.ok) {
            alert(data.detail || "Failed to create task");
            return;
        }

        currentTaskId = data.task_id;
        saveSession(currentTaskId);
        addToHistory({ task_id: currentTaskId, status: "created", phase: "init" });
        showSection(progressSection);
        initPhases();
        connectWebSocket(currentTaskId);
    } catch (err) {
        alert("Failed to create task: " + err.message);
    }
});

// ── WebSocket connection ──

function connectWebSocket(taskId) {
    if (ws) {
        try { ws.close(); } catch (_) {}
    }

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${location.host}/ws/${taskId}`);

    ws.onopen = () => {
        addChatMessage("Connected.", "system");
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
    };

    ws.onclose = () => {
        addChatMessage("Connection closed.", "system");
    };

    ws.onerror = () => {
        addChatMessage("Connection error.", "error");
    };
}

function handleMessage(msg) {
    switch (msg.type) {
        case "progress":
            updatePhase(msg.phase);
            addChatMessage(`[${msg.node || msg.phase}] ${msg.message}`, "system");
            break;

        case "interrupt":
            handleInterrupt(msg);
            break;

        case "done":
            handleDone(msg);
            break;

        case "error":
            addChatMessage(`Error: ${msg.message}`, "error");
            break;
    }
}

function handleInterrupt(msg) {
    if (msg.interrupt_type === "clarification") {
        const questions = msg.data.questions || [];
        questions.forEach((q) => {
            let text = q.question;
            if (q.options && q.options.length) {
                text += "\nOptions: " + q.options.join(", ");
            }
            addChatMessage(text, "agent");
        });

        chatInputArea.classList.remove("hidden");
        chatInput.focus();

        const handler = () => {
            const answer = chatInput.value.trim();
            if (!answer) return;

            addChatMessage(answer, "user");
            chatInput.value = "";
            chatInputArea.classList.add("hidden");

            const answers = questions.map((q) => ({
                question_id: q.id,
                answer: answer,
            }));

            ws.send(JSON.stringify({ type: "resume", data: answers }));
            chatSend.removeEventListener("click", handler);
        };

        chatSend.addEventListener("click", handler);
        chatInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handler();
            }
        });
    } else if (msg.interrupt_type === "architecture_approval") {
        archApproval.classList.remove("hidden");
        archPlanContent.textContent = JSON.stringify(msg.data.plan, null, 2);
        addChatMessage("Architecture plan ready for review.", "agent");
    }
}

// ── Architecture approval ──

archApprove.addEventListener("click", () => {
    ws.send(JSON.stringify({ type: "resume", data: { approved: true } }));
    archApproval.classList.add("hidden");
    addChatMessage("Architecture approved. Starting code generation...", "user");
});

archReject.addEventListener("click", () => {
    archFeedback.classList.remove("hidden");
    archSubmitFeedback.classList.remove("hidden");
});

archSubmitFeedback.addEventListener("click", () => {
    const feedback = archFeedback.value.trim();
    ws.send(
        JSON.stringify({
            type: "resume",
            data: { approved: false, feedback: feedback },
        })
    );
    archApproval.classList.add("hidden");
    archFeedback.classList.add("hidden");
    archSubmitFeedback.classList.add("hidden");
    addChatMessage(`Requested changes: ${feedback}`, "user");
});

// ── Done ──

function handleDone(msg) {
    clearSession();
    showSection(resultSection);
    resultMessage.textContent = "Your project has been generated successfully.";
    downloadBtn.href = `/api/tasks/${currentTaskId}/download`;
    downloadBtn.download = true;
    refreshHistory();
}

// ── Resume task (reconnect after page refresh) ──

async function resumeTask(taskId) {
    try {
        const res = await fetch(`/api/tasks/${taskId}`);
        if (!res.ok) {
            clearSession();
            return;
        }
        const task = await res.json();

        if (task.phase === "done" || task.status === "done") {
            currentTaskId = taskId;
            showSection(resultSection);
            resultMessage.textContent = "Your project has been generated successfully.";
            downloadBtn.href = `/api/tasks/${currentTaskId}/download`;
            downloadBtn.download = true;
            clearSession();
            return;
        }

        if (task.phase === "error" || task.status === "error") {
            clearSession();
            return;
        }

        // Task is in progress or waiting for input — reconnect
        currentTaskId = taskId;
        saveSession(taskId);
        showSection(progressSection);
        initPhases();
        updatePhase(task.phase);

        if (task.interrupt_type) {
            addChatMessage(
                `Reconnecting to task ${taskId}... Awaiting your input.`,
                "system"
            );
        } else {
            addChatMessage(
                `Reconnecting to task ${taskId}...`,
                "system"
            );
        }

        connectWebSocket(taskId);
    } catch (e) {
        clearSession();
    }
}

// ── History sidebar ──

function addToHistory(taskInfo) {
    const existing = historyList.querySelector(`[data-task-id="${taskInfo.task_id}"]`);
    if (existing) {
        updateHistoryItem(existing, taskInfo);
        return;
    }

    const li = document.createElement("li");
    li.dataset.taskId = taskInfo.task_id;
    updateHistoryItem(li, taskInfo);
    li.addEventListener("click", () => onHistoryItemClick(taskInfo.task_id));
    historyList.prepend(li);
}

function updateHistoryItem(li, taskInfo) {
    const statusClass = getStatusClass(taskInfo);
    const statusIcon = getStatusIcon(taskInfo);
    li.className = `history-item ${statusClass}`;
    li.innerHTML = `
        <span class="history-icon">${statusIcon}</span>
        <span class="history-label">Task ${taskInfo.task_id}</span>
        <span class="history-status">${taskInfo.phase || taskInfo.status}</span>
    `;
}

function isWaitingForInput(task) {
    if (task.status === "waiting_for_input") return true;
    if (task.interrupt_type && task.interrupt_type !== "") return true;
    const waitingPhases = ["clarifying", "approving_architecture"];
    if (waitingPhases.includes(task.phase) && task.status !== "running") return true;
    return false;
}

function getStatusClass(task) {
    if (task.status === "done" || task.phase === "done") return "status-done";
    if (task.status === "error" || task.phase === "error") return "status-error";
    if (isWaitingForInput(task)) return "status-waiting";
    if (task.status === "running") return "status-running";
    return "status-idle";
}

function getStatusIcon(task) {
    if (task.status === "done" || task.phase === "done") return "\u2705";
    if (task.status === "error" || task.phase === "error") return "\u274C";
    if (isWaitingForInput(task)) return "\u{1F7E1}";
    if (task.status === "running") return "\u23F3";
    return "\u26AA";
}

function onHistoryItemClick(taskId) {
    if (currentTaskId === taskId && !progressSection.classList.contains("hidden")) {
        return;
    }
    resumeTask(taskId);
}

async function loadHistory() {
    try {
        const res = await fetch("/api/tasks");
        const tasks = await res.json();
        tasks.forEach((t) => addToHistory(t));
    } catch (e) {
        // ignore
    }
}

async function refreshHistory() {
    historyList.innerHTML = "";
    await loadHistory();
}

// ── Page load: check for interrupted session ──

async function init() {
    await loadHistory();

    const savedTaskId = getSavedTaskId();
    if (savedTaskId) {
        resumeTask(savedTaskId);
    }
}

init();

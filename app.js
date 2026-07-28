const DATA_URL = "data/exams.json";
const STORAGE_KEY = "rtve_journalist_exam_progress_v1";
const EMBEDDED_EXAM_DATA = { version: 1, updatedAt: null, exams: [] };

let exams = [];
let currentExam = null;
let progress = loadProgress();
let currentFilter = "all";

const dashboardView = document.getElementById("dashboardView");
const examView = document.getElementById("examView");
const examList = document.getElementById("examList");
const stats = document.getElementById("stats");
const quizForm = document.getElementById("quizForm");
const resultPanel = document.getElementById("resultPanel");

function loadProgress() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function saveProgress() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
}

async function loadExams(forceRefresh = false) {
  let data = EMBEDDED_EXAM_DATA;
  const separator = DATA_URL.includes("?") ? "&" : "?";
  const url = forceRefresh ? `${DATA_URL}${separator}v=${Date.now()}` : DATA_URL;

  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(`No se pudo cargar el catálogo (${response.status}).`);
    const remoteData = await response.json();
    if (!remoteData || !Array.isArray(remoteData.exams)) {
      throw new Error("El catálogo de exámenes no tiene un formato válido.");
    }
    data = remoteData;
  } catch (error) {
    console.warn("No se pudo cargar data/exams.json.", error);
  }

  exams = [...data.exams].sort((a, b) => String(b.id).localeCompare(String(a.id)));
  renderDashboard();
}

function getStatus(exam) {
  const item = progress[exam.id];
  if (item?.completedAt) return "completed";
  if (item?.answers?.some(value => value !== null && value !== undefined)) return "in-progress";
  return "pending";
}

function statusLabel(status) {
  return {
    completed: "Realizado",
    "in-progress": "En curso",
    pending: "Pendiente"
  }[status];
}

function getStoredNetScore(exam) {
  const item = progress[exam.id];
  if (!item?.completedAt) return null;
  if (typeof item.netScore === "number") return item.netScore;
  if (typeof item.score === "number") return item.score;
  return null;
}

function renderStats() {
  const completed = exams.filter(exam => getStatus(exam) === "completed");
  const pending = exams.length - completed.length;
  const scores = completed
    .map(getStoredNetScore)
    .filter(value => typeof value === "number");
  const average = scores.length
    ? scores.reduce((sum, value) => sum + value, 0) / scores.length
    : 0;
  const best = scores.length ? Math.max(...scores) : 0;

  stats.innerHTML = `
    <article class="stat-card"><span class="stat-label">Total</span><strong class="stat-value">${exams.length}</strong></article>
    <article class="stat-card"><span class="stat-label">Realizados</span><strong class="stat-value">${completed.length}</strong></article>
    <article class="stat-card"><span class="stat-label">Pendientes</span><strong class="stat-value">${pending}</strong></article>
    <article class="stat-card"><span class="stat-label">Media / Mejor</span><strong class="stat-value">${formatScore(average)} / ${formatScore(best)}</strong></article>
  `;
}

function renderDashboard() {
  renderStats();
  const filtered = exams.filter(exam => {
    const status = getStatus(exam);
    if (currentFilter === "completed") return status === "completed";
    if (currentFilter === "pending") return status !== "completed";
    return true;
  });

  if (!filtered.length) {
    examList.innerHTML = `
      <div class="empty">
        <strong>Aún no hay exámenes publicados.</strong><br>
        Ejecuta una vez el workflow <em>RTVE Periodista - Examen diario</em> con <em>force</em> activado.
      </div>`;
    return;
  }

  examList.innerHTML = filtered.map(exam => {
    const status = getStatus(exam);
    const item = progress[exam.id];
    const netScore = getStoredNetScore(exam);
    const score = item?.completedAt && netScore !== null ? `${formatScore(netScore)}/${exam.questions.length}` : "—";
    const action = status === "completed" ? "Repetir" : status === "in-progress" ? "Continuar" : "Empezar";
    return `
      <article class="exam-card ${status}">
        <div>
          <div class="exam-title-row">
            <h2 class="exam-title">${escapeHtml(exam.title)}</h2>
            <span class="status-pill ${status}">${statusLabel(status)}</span>
          </div>
          <div class="exam-meta">${formatDate(exam.date)} · ${escapeHtml(exam.level)} · ${exam.timeMinutes} min · ${exam.questions.length} preguntas</div>
          ${exam.currentAffairsCutoff ? `<div class="cutoff">Actualidad verificada hasta ${formatDate(exam.currentAffairsCutoff)}</div>` : ""}
          <div class="tags">${exam.blocks.map(block => `<span class="tag">${escapeHtml(block)}</span>`).join("")}</div>
          <div class="card-actions">
            <button class="open-button" type="button" data-open="${escapeHtml(exam.id)}">${action}</button>
            ${item?.completedAt ? `<button class="clear-result" type="button" data-clear="${escapeHtml(exam.id)}">Borrar resultado</button>` : ""}
          </div>
        </div>
        <div class="score-box">
          <div class="score-number">${score}</div>
          <div class="score-caption">${item?.completedAt ? "Puntuación neta" : "Sin nota"}</div>
        </div>
      </article>
    `;
  }).join("");

  document.querySelectorAll("[data-open]").forEach(button => {
    button.addEventListener("click", () => openExam(button.dataset.open));
  });
  document.querySelectorAll("[data-clear]").forEach(button => {
    button.addEventListener("click", () => clearResult(button.dataset.clear));
  });
}

function openExam(id) {
  currentExam = exams.find(exam => String(exam.id) === String(id));
  if (!currentExam) return;

  dashboardView.classList.add("hidden");
  examView.classList.remove("hidden");
  resultPanel.classList.add("hidden");

  const saved = progress[id] || { answers: Array(currentExam.questions.length).fill(null) };
  if (!Array.isArray(saved.answers) || saved.answers.length !== currentExam.questions.length) {
    saved.answers = Array(currentExam.questions.length).fill(null);
  }
  progress[id] = saved;
  saveProgress();

  document.getElementById("examHeader").innerHTML = `
    <div class="exam-hero">
      <h2>${escapeHtml(currentExam.title)}</h2>
      <div class="exam-meta">${formatDate(currentExam.date)} · ${escapeHtml(currentExam.level)} · ${currentExam.timeMinutes} minutos</div>
      ${currentExam.currentAffairsCutoff ? `<div class="cutoff">Actualidad verificada hasta ${formatDate(currentExam.currentAffairsCutoff)}</div>` : ""}
      <div class="tags">${currentExam.blocks.map(block => `<span class="tag">${escapeHtml(block)}</span>`).join("")}</div>
    </div>
  `;

  quizForm.innerHTML = currentExam.questions.map((question, index) => `
    <section class="question" data-question="${index}">
      <div class="question-kicker">${escapeHtml(question.category || "Información y Contenidos")}</div>
      <h3>${index + 1}. ${escapeHtml(question.prompt)}</h3>
      ${question.options.map((option, optionIndex) => `
        <label class="option">
          <input type="radio" name="q${index}" value="${optionIndex}" ${saved.answers[index] === optionIndex ? "checked" : ""}>
          <span><strong>${letter(optionIndex)}.</strong> ${escapeHtml(option)}</span>
        </label>
      `).join("")}
      <div class="feedback"></div>
    </section>
  `).join("");

  quizForm.querySelectorAll("input[type=radio]").forEach(input => {
    input.addEventListener("change", event => {
      const questionIndex = Number(event.target.name.substring(1));
      progress[currentExam.id].answers[questionIndex] = Number(event.target.value);
      delete progress[currentExam.id].completedAt;
      delete progress[currentExam.id].score;
      delete progress[currentExam.id].netScore;
      saveProgress();
    });
  });

  window.scrollTo({ top: 0, behavior: "smooth" });
}

function gradeCurrentExam() {
  if (!currentExam) return;
  const saved = progress[currentExam.id];
  let correct = 0;
  let incorrect = 0;
  let blank = 0;

  currentExam.questions.forEach((question, index) => {
    const section = quizForm.querySelector(`[data-question="${index}"]`);
    const feedback = section.querySelector(".feedback");
    const answer = saved.answers[index];
    const source = renderSource(question);

    section.classList.remove("correct", "incorrect", "unanswered");
    feedback.className = "feedback show";

    if (answer === null || answer === undefined) {
      blank += 1;
      section.classList.add("unanswered");
      feedback.classList.add("unanswered");
      feedback.innerHTML = `<strong>Sin responder.</strong> Correcta: ${letter(question.correctIndex)}. ${escapeHtml(question.explanation)}${source}`;
      return;
    }

    if (answer === question.correctIndex) {
      correct += 1;
      section.classList.add("correct");
      feedback.classList.add("correct");
      feedback.innerHTML = `<strong>Correcta.</strong> ${escapeHtml(question.explanation)}${source}`;
    } else {
      incorrect += 1;
      section.classList.add("incorrect");
      feedback.classList.add("incorrect");
      feedback.innerHTML = `<strong>Incorrecta.</strong> Correcta: <strong>${letter(question.correctIndex)}. ${escapeHtml(question.options[question.correctIndex])}</strong><br>${escapeHtml(question.explanation)}${source}`;
    }
  });

  const netScore = correct - (incorrect / 3);
  saved.score = correct;
  saved.netScore = Number(netScore.toFixed(2));
  saved.correct = correct;
  saved.incorrect = incorrect;
  saved.blank = blank;
  saved.completedAt = new Date().toISOString();
  saveProgress();

  const percentage = Math.max(0, Math.round((netScore / currentExam.questions.length) * 100));
  const message = netScore >= 15 ? "Nivel muy alto."
    : netScore >= 12 ? "Buen nivel competitivo."
    : netScore >= 9 ? "Base aceptable, con lagunas."
    : "Conviene reforzar temario y actualidad.";

  resultPanel.innerHTML = `
    <div class="result-score">${formatScore(netScore)}/${currentExam.questions.length}</div>
    <strong>${percentage}% neto · ${message}</strong>
    <div class="result-breakdown">
      <span class="result-chip">✓ ${correct} correctas</span>
      <span class="result-chip">✕ ${incorrect} incorrectas</span>
      <span class="result-chip">— ${blank} en blanco</span>
    </div>
    <p>Se ha aplicado la fórmula oficial: +1 por acierto, −1/3 por error y 0 por respuesta en blanco. El resultado queda guardado en este dispositivo.</p>
  `;
  resultPanel.classList.remove("hidden");
  resultPanel.scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderSource(question) {
  const url = safeUrl(question.sourceUrl);
  if (!url) return "";
  const title = question.sourceTitle || "Fuente de verificación";
  const date = question.sourceDate ? ` · ${escapeHtml(question.sourceDate)}` : "";
  return `<br><a class="source-link" href="${url}" target="_blank" rel="noopener noreferrer">Fuente: ${escapeHtml(title)}${date}</a>`;
}

function safeUrl(value) {
  try {
    const url = new URL(String(value));
    if (url.protocol === "https:" || url.protocol === "http:") return escapeHtml(url.href);
  } catch {}
  return "";
}

function resetCurrentExam() {
  if (!currentExam) return;
  if (!confirm("¿Quieres borrar todas las respuestas y el resultado de este examen?")) return;
  progress[currentExam.id] = { answers: Array(currentExam.questions.length).fill(null) };
  saveProgress();
  openExam(currentExam.id);
}

function clearResult(id) {
  const exam = exams.find(item => String(item.id) === String(id));
  if (!exam) return;
  if (!confirm(`¿Borrar el resultado de ${exam.title}?`)) return;
  progress[id] = { answers: Array(exam.questions.length).fill(null) };
  saveProgress();
  renderDashboard();
}

function backToDashboard() {
  currentExam = null;
  examView.classList.add("hidden");
  dashboardView.classList.remove("hidden");
  renderDashboard();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function formatDate(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("es-ES", { day: "2-digit", month: "2-digit", year: "numeric" })
    .format(new Date(`${value}T12:00:00`));
}

function formatScore(value) {
  const number = Number(value || 0);
  return number.toLocaleString("es-ES", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function letter(index) {
  return String.fromCharCode(65 + index);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.querySelectorAll(".filter").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".filter").forEach(item => item.classList.remove("active"));
    button.classList.add("active");
    currentFilter = button.dataset.filter;
    renderDashboard();
  });
});

document.getElementById("backButton").addEventListener("click", backToDashboard);
document.getElementById("gradeButton").addEventListener("click", gradeCurrentExam);
document.getElementById("resetExamButton").addEventListener("click", resetCurrentExam);
document.getElementById("refreshButton").addEventListener("click", async () => {
  await loadExams(true);
  alert("Exámenes actualizados.");
});

loadExams().catch(error => {
  examList.innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
});

/* dashboard.js - UI de carga de actas y graficas */
(function () {
  const raw = document.getElementById("resultados-json");
  const resultados = raw ? JSON.parse(raw.textContent || "[]") : [];
  const searchNumeroInput = document.getElementById("search-numero");
  const searchNombreInput = document.getElementById("search-nombre");
  const sortSelect = document.getElementById("sort-actas");
  const cards = Array.from(document.querySelectorAll(".card"));
  const mainGrid = document.querySelector("main.grid");
  const searchEmpty = document.getElementById("search-empty");
  const duplicateCount = document.getElementById("duplicate-count");
  const duplicateList = document.getElementById("duplicate-list");
  const duplicateWarning = document.getElementById("duplicate-warning");
  const duplicadosMenu = document.getElementById("duplicados-menu");

  const authModal = document.getElementById("auth-modal");
  const authUsuario = document.getElementById("auth-usuario");
  const authContrasena = document.getElementById("auth-contrasena");
  const authMsg = document.getElementById("auth-msg");
  const authCancel = document.getElementById("auth-cancel");
  const authConfirm = document.getElementById("auth-confirm");

  function pedirAutorizacion() {
    return new Promise((resolve) => {
      if (!authModal) {
        resolve(null);
        return;
      }

      authModal.style.display = "flex";
      authUsuario.value = "";
      authContrasena.value = "";
      authMsg.textContent = "";
      authUsuario.focus();

      function limpiar() {
        authModal.style.display = "none";
        authConfirm.removeEventListener("click", onConfirm);
        authCancel.removeEventListener("click", onCancel);
      }

      function onConfirm() {
        const usuario = (authUsuario.value || "").trim();
        const contrasena = (authContrasena.value || "").trim();
        if (!usuario || !contrasena) {
          authMsg.textContent = "Debes capturar usuario y contrasena.";
          return;
        }
        limpiar();
        resolve({ usuario, contrasena });
      }

      function onCancel() {
        limpiar();
        resolve(null);
      }

      authConfirm.addEventListener("click", onConfirm);
      authCancel.addEventListener("click", onCancel);
    });
  }

  async function eliminarActa(card) {
    const cred = await pedirAutorizacion();
    if (!cred) return;

    const actaId = Number(card.getAttribute("data-id") || 0);
    if (!actaId) return;

    const res = await fetch(`/api/actas/${actaId}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(cred),
    });
    const json = await res.json().catch(() => ({}));
    if (!res.ok || json.status !== "ok") {
      alert((json && json.mensaje) || "No se pudo eliminar el acta.");
      return;
    }
    window.location.reload();
  }

  function descargarPdfActa(card) {
    const actaId = Number(card.getAttribute("data-id") || 0);
    if (!actaId) {
      alert("No se pudo identificar el acta para descargar PDF.");
      return;
    }
    window.open(`/api/actas/${actaId}/pdf`, "_blank");
  }

  function activarAccionesActa() {
    cards.forEach((card) => {
      const pdfBtn = card.querySelector(".pdf-btn");
      const editBtn = card.querySelector(".edit-btn");
      const deleteBtn = card.querySelector(".delete-btn");

      if (pdfBtn) {
        pdfBtn.addEventListener("click", () => {
          descargarPdfActa(card);
        });
      }
      if (editBtn) {
        editBtn.addEventListener("click", () => {
          editarActa(card).catch(() => alert("Error al editar acta."));
        });
      }
      if (deleteBtn) {
        deleteBtn.addEventListener("click", () => {
          eliminarActa(card).catch(() => alert("Error al eliminar acta."));
        });
      }
    });
  }
  let estadoActual = {
    total_actas: resultados.length,
    ultimo_id: 0,
  };

  resultados.forEach((r, i) => {
    const id = `chart${i + 1}`;
    const canvas = document.getElementById(id);
    if (!canvas) return;

    const labels = (r.planillas || []).map((c) => c.planilla || "Sin planilla");
    const datos = (r.planillas || []).map((c) => Number(c.votos || 0));
    const maxVotos = Math.max(...datos, 0);
    const winnerIndex = datos.findIndex((v) => v === maxVotos);
    const coloresBarras = datos.map((_, idx) => ["#16a34a", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"][idx % 6]);
    const bordesBarras = coloresBarras.map(() => "#ffffff");

    if (!labels.length) return;

    new Chart(canvas, {
      type: "pie",
      options: {
        responsive: true,
        maintainAspectRatio: false,
        layout: {
          padding: { bottom: 50 },
        },
        animation: {
          duration: 650,
          easing: "easeOutQuart",
        },
        plugins: {
          legend: {
            display: true,
            position: "bottom",
            labels: { boxWidth: 12, boxHeight: 12, color: "#334155" },
          },
          tooltip: {
            backgroundColor: "#0f172a",
            titleColor: "#f8fafc",
            bodyColor: "#e2e8f0",
            padding: 10,
            callbacks: {
              label: (ctx) => {
                const total = ctx.dataset.data.reduce((a, b) => a + b, 0) || 1;
                const pct = ((ctx.raw / total) * 100).toFixed(2);
                const expr = ((r.planillas || [])[ctx.dataIndex] || {}).expresion_politica || "";
                return expr ? `${ctx.label} (${expr}): ${ctx.raw} votos (${pct}%)` : `${ctx.label}: ${ctx.raw} votos (${pct}%)`;
              },
            },
          },
        },
      },
      data: {
        labels,
        datasets: [
          {
            label: "Votos por planilla",
            data: datos,
            backgroundColor: coloresBarras,
            borderColor: bordesBarras,
            borderWidth: 2,
            hoverOffset: 8,
          },
        ],
      },
    });
  });

  let estadoInicializado = false;

  async function verificarActualizacion() {
    try {
      const res = await fetch("/api/actas/estado", {
        method: "GET",
        headers: { "Cache-Control": "no-cache" },
      });
      if (!res.ok) return;
      const json = await res.json();
      if (!json || json.status !== "ok" || !json.data) return;

      const nuevo = json.data;
      if (!estadoInicializado) {
        estadoActual = {
          total_actas: Number(nuevo.total_actas || 0),
          ultimo_id: Number(nuevo.ultimo_id || 0),
        };
        estadoInicializado = true;
        return;
      }

      const cambio =
        Number(nuevo.total_actas || 0) !== Number(estadoActual.total_actas || 0) ||
        Number(nuevo.ultimo_id || 0) !== Number(estadoActual.ultimo_id || 0);

      if (cambio) {
        window.location.reload();
      }
    } catch (_) {
      // silencioso para no molestar al usuario por errores temporales
    }
  }

  // Primer estado real desde backend, luego polling.
  verificarActualizacion().then(() => {
    setInterval(verificarActualizacion, 5000);
  });

  function normalizar(texto) {
    return (texto || "")
      .toString()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .trim();
  }

  function detectarDuplicados() {
    const mapa = new Map();
    const faltantes = [];

    cards.forEach((card, idx) => {
      const numero = normalizar(card.getAttribute("data-numero"));
      const nombre = normalizar(card.getAttribute("data-nombre"));
      const fecha = normalizar(card.getAttribute("data-fecha"));

      card.classList.remove("is-duplicate");

      if (!numero || !nombre || !fecha) {
        faltantes.push(idx + 1);
        return;
      }

      const key = `${numero}||${nombre}||${fecha}`;
      if (!mapa.has(key)) {
        mapa.set(key, []);
      }
      mapa.get(key).push({ card, idx: idx + 1, numero, nombre, fecha });
    });

    const grupos = Array.from(mapa.values()).filter((items) => items.length > 1);

    grupos.forEach((grupo) => {
      grupo.forEach((item) => item.card.classList.add("is-duplicate"));
    });

    if (duplicateCount) {
      duplicateCount.textContent = String(grupos.length);
    }

    if (duplicateList) {
      duplicateList.innerHTML = "";
      if (!grupos.length) {
        const li = document.createElement("li");
        li.textContent = "No se detectaron actas duplicadas con numero + nombre + fecha.";
        duplicateList.appendChild(li);
      } else {
        grupos.forEach((grupo, index) => {
          const item0 = grupo[0];
          const li = document.createElement("li");
          const refs = grupo.map((x) => `acta ${x.idx}`).join(", ");
          li.textContent = `Coincidencia ${index + 1}: dependencia ${item0.numero}, ${item0.nombre}, fecha ${item0.fecha} (${refs}).`;
          duplicateList.appendChild(li);
        });
      }
    }

    if (duplicateWarning) {
      if (faltantes.length) {
        duplicateWarning.style.display = "";
        duplicateWarning.textContent = `Aviso: hay ${faltantes.length} acta(s) con datos incompletos (numero, nombre o fecha). Revisar manualmente.`;
      } else {
        duplicateWarning.style.display = "none";
        duplicateWarning.textContent = "";
      }
    }
  }

  function ordenarCards() {
    if (!mainGrid || !cards.length || !sortSelect) return;
    const tipo = sortSelect.value || "recientes";
    const ordenadas = cards.slice();

    if (tipo === "numero_asc") {
      ordenadas.sort((a, b) => {
        const aNum = Number(a.getAttribute("data-numero"));
        const bNum = Number(b.getAttribute("data-numero"));
        const aVal = Number.isFinite(aNum) ? aNum : Number.MAX_SAFE_INTEGER;
        const bVal = Number.isFinite(bNum) ? bNum : Number.MAX_SAFE_INTEGER;
        return aVal - bVal;
      });
    } else if (tipo === "numero_desc") {
      ordenadas.sort((a, b) => {
        const aNum = Number(a.getAttribute("data-numero"));
        const bNum = Number(b.getAttribute("data-numero"));
        const aVal = Number.isFinite(aNum) ? aNum : Number.MIN_SAFE_INTEGER;
        const bVal = Number.isFinite(bNum) ? bNum : Number.MIN_SAFE_INTEGER;
        return bVal - aVal;
      });
    } else if (tipo === "nombre_asc") {
      ordenadas.sort((a, b) => {
        const aNom = normalizar(a.getAttribute("data-nombre"));
        const bNom = normalizar(b.getAttribute("data-nombre"));
        return aNom.localeCompare(bNom, "es", { sensitivity: "base" });
      });
    } else if (tipo === "nombre_desc") {
      ordenadas.sort((a, b) => {
        const aNom = normalizar(a.getAttribute("data-nombre"));
        const bNom = normalizar(b.getAttribute("data-nombre"));
        return bNom.localeCompare(aNom, "es", { sensitivity: "base" });
      });
    } else {
      // "Recientes": respetar el orden original del backend (id DESC).
      ordenadas.sort((a, b) => cards.indexOf(a) - cards.indexOf(b));
    }

    ordenadas.forEach((card) => mainGrid.appendChild(card));
  }
  function sincronizarBuscadores() {
    if (!searchNumeroInput || !searchNombreInput) return;

    const numeroConValor = (searchNumeroInput.value || "").trim().length > 0;
    const nombreConValor = (searchNombreInput.value || "").trim().length > 0;

    searchNombreInput.readOnly = numeroConValor;
    searchNumeroInput.readOnly = nombreConValor;

    searchNombreInput.title = numeroConValor ? "Limpia el filtro por numero para buscar por nombre" : "";
    searchNumeroInput.title = nombreConValor ? "Limpia el filtro por nombre para buscar por numero" : "";
  }
  function filtrarActas() {
    const soloDuplicadas = Boolean(duplicadosMenu && duplicadosMenu.open);
    if (!cards.length) return;

    const qNumero = normalizar(searchNumeroInput ? searchNumeroInput.value : "");
    const qNombre = normalizar(searchNombreInput ? searchNombreInput.value : "");

    let visibles = 0;

    cards.forEach((card) => {
      const numeroRaw = card.getAttribute("data-numero") || "";
      const numeroNormalizado = normalizar(numeroRaw);
      const nombre = normalizar(card.getAttribute("data-nombre"));

      const matchNumero = !qNumero || numeroNormalizado === qNumero;
      const matchNombre = !qNombre || nombre.includes(qNombre);
      const matchDuplicada = !soloDuplicadas || card.classList.contains("is-duplicate");
      const match = matchNumero && matchNombre && matchDuplicada;

      card.style.display = match ? "" : "none";
      if (match) visibles += 1;
    });

    if (searchEmpty) {
      searchEmpty.style.display = visibles === 0 ? "" : "none";
    }

    sincronizarBuscadores();
    ordenarCards();
  }

  if (searchNumeroInput) {
    searchNumeroInput.addEventListener("focus", () => {
      if (searchNumeroInput.readOnly && searchNombreInput) {
        searchNombreInput.value = "";
        searchNumeroInput.readOnly = false;
        searchNombreInput.readOnly = false;
        filtrarActas();
      }
    });

    searchNumeroInput.addEventListener("input", () => {
      const v = (searchNumeroInput.value || "").trim();
      if (v && searchNombreInput && searchNombreInput.value) {
        searchNombreInput.value = "";
      }
      filtrarActas();
    });
  }
  if (searchNombreInput) {
    searchNombreInput.addEventListener("focus", () => {
      if (searchNombreInput.readOnly && searchNumeroInput) {
        searchNumeroInput.value = "";
        searchNombreInput.readOnly = false;
        searchNumeroInput.readOnly = false;
        filtrarActas();
      }
    });

    searchNombreInput.addEventListener("input", () => {
      const v = (searchNombreInput.value || "").trim();
      if (v && searchNumeroInput && searchNumeroInput.value) {
        searchNumeroInput.value = "";
      }
      filtrarActas();
    });
  }
  if (duplicadosMenu) {
    duplicadosMenu.addEventListener("toggle", filtrarActas);
  }
  if (sortSelect) {
    sortSelect.addEventListener("change", ordenarCards);
  }

  detectarDuplicados();
  activarAccionesActa();
  filtrarActas();
})();
















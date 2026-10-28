/* Comportamiento del panel y del simulador. Sin dependencias externas. */
(function () {
  "use strict";

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

  function guardar(clave, valor) {
    try { localStorage.setItem(clave, valor); } catch (e) { /* almacenamiento no disponible */ }
  }

  function leer(clave) {
    try { return localStorage.getItem(clave); } catch (e) { return null; }
  }

  async function enviarJSON(url, datos) {
    const respuesta = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, "Accept": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(datos || {}),
    });
    const cuerpo = await respuesta.json().catch(() => ({}));
    if (!respuesta.ok) throw new Error(cuerpo.error || "No fue posible enviar el mensaje.");
    return cuerpo;
  }

  function horaActual() {
    const d = new Date();
    return d.getHours() + ":" + String(d.getMinutes()).padStart(2, "0");
  }

  /* Formato de WhatsApp en los mensajes del bot: *negrita* y enlaces. Se construyen nodos
     (nunca innerHTML), así un texto con etiquetas se muestra como texto. */
  const PATRON_FORMATO = /(https?:\/\/[^\s<>"]+[^\s<>".,;:!?)\]])|\*([^*\n]+)\*/g;

  function formatear(contenedor, texto) {
    let ultimo = 0;
    for (const m of texto.matchAll(PATRON_FORMATO)) {
      if (m.index > ultimo) contenedor.appendChild(document.createTextNode(texto.slice(ultimo, m.index)));
      if (m[1]) {
        const enlace = document.createElement("a");
        enlace.href = m[1];
        enlace.textContent = m[1];
        enlace.target = "_blank";
        enlace.rel = "noopener noreferrer nofollow";
        contenedor.appendChild(enlace);
      } else {
        const negrita = document.createElement("strong");
        negrita.textContent = m[2];
        contenedor.appendChild(negrita);
      }
      ultimo = m.index + m[0].length;
    }
    if (ultimo < texto.length) contenedor.appendChild(document.createTextNode(texto.slice(ultimo)));
  }

  /* Las respuestas llegan como {texto, botones} (o como texto, en versiones anteriores). */
  function normalizarRespuesta(r) {
    return typeof r === "string" ? { texto: r, botones: [] } : { texto: r.texto || "", botones: r.botones || [] };
  }

  /* Menú en pantallas chicas */
  document.querySelectorAll("[data-abrir-menu]").forEach((boton) => {
    const panel = boton.closest("[data-panel]");
    boton.addEventListener("click", () => {
      const abierto = panel.dataset.menu === "abierto";
      panel.dataset.menu = abierto ? "" : "abierto";
      boton.setAttribute("aria-expanded", String(!abierto));
    });
    panel.querySelector(".contenido")?.addEventListener("click", () => {
      if (panel.dataset.menu === "abierto") {
        panel.dataset.menu = "";
        boton.setAttribute("aria-expanded", "false");
      }
    });
  });

  /* Copiar enlace */
  document.querySelectorAll("[data-copiar]").forEach((boton) => {
    boton.addEventListener("click", async () => {
      const campo = document.querySelector(boton.dataset.copiar);
      if (!campo) return;
      const original = boton.textContent;
      try {
        await navigator.clipboard.writeText(campo.value);
      } catch (e) {
        campo.select();
        document.execCommand("copy");
      }
      boton.textContent = boton.dataset.copiado || "Copiado";
      setTimeout(() => { boton.textContent = original; }, 1800);
    });
  });

  document.querySelectorAll("[data-imprimir]").forEach((b) => b.addEventListener("click", () => window.print()));

  /* Formulario de medio de pago: campo «nombre» para la opción Otro y ejemplo del detalle */
  document.querySelectorAll("[data-formulario-medio]").forEach((formulario) => {
    const tipo = formulario.querySelector("[data-tipo-medio]");
    const otro = formulario.querySelector("[data-campo-otro]");
    const detalle = formulario.querySelector("[data-detalle-medio]");
    if (!tipo) return;
    const actualizar = () => {
      if (otro) otro.hidden = tipo.value !== "Otro";
      const opcion = tipo.selectedOptions[0];
      if (detalle && opcion && opcion.dataset.ejemplo) detalle.placeholder = opcion.dataset.ejemplo;
    };
    tipo.addEventListener("change", actualizar);
    actualizar();
  });

  /* Chat: prueba del panel (CU07) y simulador de WhatsApp */
  document.querySelectorAll("[data-chat]").forEach((chat) => {
    const modo = chat.dataset.modo;
    const mensajes = chat.querySelector("[data-chat-mensajes]");
    const formulario = chat.querySelector("[data-chat-formulario]");
    const entrada = chat.querySelector("[data-chat-texto]");
    const subtitulo = chat.querySelector("[data-chat-subtitulo]");
    let ocupado = false;

    function quitarVacio() {
      chat.querySelector("[data-chat-vacio]")?.remove();
    }

    function burbuja(texto, propia, hora, botones) {
      quitarVacio();
      const div = document.createElement("div");
      div.className = "burbuja" + (propia ? " burbuja--propia" : "");
      if (propia) div.textContent = texto;
      else formatear(div, texto);
      const h = document.createElement("span");
      h.className = "burbuja__hora";
      h.textContent = hora || horaActual();
      div.appendChild(h);
      mensajes.appendChild(div);
      if (!propia && botones && botones.length) {
        // Botones de respuesta rápida, como los muestra WhatsApp debajo del mensaje.
        const fila = document.createElement("div");
        fila.className = "chat__botones";
        fila.setAttribute("role", "group");
        fila.setAttribute("aria-label", "Opciones de respuesta");
        botones.forEach((b) => {
          const boton = document.createElement("button");
          boton.type = "button";
          boton.textContent = b.titulo;
          boton.addEventListener("click", () => enviar(b.titulo, b.id));
          fila.appendChild(boton);
        });
        mensajes.appendChild(fila);
      }
      mensajes.scrollTop = mensajes.scrollHeight;
    }

    function nota(texto, clase) {
      quitarVacio();
      const span = document.createElement("span");
      span.className = clase || "chat__nota";
      span.textContent = texto;
      mensajes.appendChild(span);
      mensajes.scrollTop = mensajes.scrollHeight;
    }

    function escribiendo(mostrar) {
      let indicador = mensajes.querySelector(".chat__escribiendo");
      if (mostrar && !indicador) {
        indicador = document.createElement("span");
        indicador.className = "chat__escribiendo";
        indicador.textContent = "escribiendo…";
        mensajes.appendChild(indicador);
        mensajes.scrollTop = mensajes.scrollHeight;
      } else if (!mostrar && indicador) {
        indicador.remove();
      }
    }

    // --- Simulador: comprador de prueba persistente en el navegador ---
    const sim = modo === "simulador" ? window.SIMULADOR || {} : null;
    const legible = document.querySelector("[data-sim-numero-legible]");
    const nombre = document.querySelector("[data-sim-nombre]");
    let telefono = null;

    function numeroAleatorio() {
      let n = "5493510";
      for (let i = 0; i < 6; i++) n += Math.floor(Math.random() * 10);
      return n;
    }

    function mostrarNumero() {
      if (legible && telefono) {
        legible.textContent = "+54 9 " + telefono.slice(3, 6) + " " + telefono.slice(6, 9) + "-" + telefono.slice(9);
      }
    }

    async function cargarHistorial() {
      mensajes.innerHTML = "";
      try {
        const r = await fetch(sim.historial + "?telefono=" + encodeURIComponent(telefono), { credentials: "same-origin" });
        const datos = await r.json();
        let fecha = null;
        (datos.mensajes || []).forEach((m) => {
          if (m.fecha !== fecha) { fecha = m.fecha; nota(m.fecha, "chat__fecha"); }
          burbuja(m.texto, !m.saliente, m.hora, m.saliente ? m.botones : null);
        });
        if (!datos.mensajes || !datos.mensajes.length) {
          nota("Abra el enlace de un comercio o escriba su código para empezar.", "chat__fecha");
        }
      } catch (e) {
        nota("No fue posible cargar la conversación.", "chat__nota");
      }
    }

    if (sim) {
      telefono = leer("simulador_telefono");
      if (!/^5493510\d{6}$/.test(telefono || "")) {
        telefono = sim.numeroSugerido || numeroAleatorio();
        guardar("simulador_telefono", telefono);
      }
      if (nombre) {
        nombre.value = leer("simulador_nombre") || "";
        nombre.addEventListener("change", () => guardar("simulador_nombre", nombre.value.trim()));
      }
      mostrarNumero();
      cargarHistorial();

      document.querySelector("[data-sim-nuevo]")?.addEventListener("click", () => {
        telefono = numeroAleatorio();
        guardar("simulador_telefono", telefono);
        if (nombre) { nombre.value = ""; guardar("simulador_nombre", ""); }
        mostrarNumero();
        subtitulo.textContent = "Comprador nuevo";
        cargarHistorial();
      });

      document.querySelectorAll("[data-sim-enlace]").forEach((b) => {
        b.addEventListener("click", () => {
          entrada.value = b.dataset.simEnlace;
          entrada.focus();
        });
      });
    }

    async function enviar(texto, boton) {
      texto = (texto || "").trim();
      if (!texto || ocupado) return;
      ocupado = true;
      burbuja(texto, true);
      if (!boton) entrada.value = "";
      escribiendo(true);
      try {
        const datos = sim
          ? { texto, telefono, nombre: nombre ? nombre.value.trim() : "" }
          : { texto };
        if (boton) datos.boton = boton;
        const r = await enviarJSON(chat.dataset.endpoint, datos);
        await new Promise((ok) => setTimeout(ok, 350));
        escribiendo(false);
        (r.respuestas || []).map(normalizarRespuesta).forEach((m) => burbuja(m.texto, false, null, m.botones));
        if (r.nota) nota(r.nota);
        if (sim) {
          if (r.comercio) subtitulo.textContent = "Conversando con " + r.comercio;
          if (r.silencio) {
            nota(r.estado === "Derivada"
              ? "El bot no responde: la consulta ya está a cargo de una persona del comercio y el aviso ya se envió."
              : "El bot no responde: es el tercer mensaje seguido que no entiende.");
          }
        }
      } catch (e) {
        escribiendo(false);
        nota(e.message);
      } finally {
        ocupado = false;
        entrada.focus();
      }
    }

    formulario.addEventListener("submit", (ev) => {
      ev.preventDefault();
      enviar(entrada.value);
    });

    chat.querySelectorAll("[data-sugerencia]").forEach((b) => {
      b.addEventListener("click", () => enviar(b.dataset.sugerencia));
    });

    chat.querySelector("[data-chat-reiniciar]")?.addEventListener("click", async () => {
      try { await enviarJSON(chat.dataset.reiniciar, {}); } catch (e) { /* sin efecto */ }
      mensajes.innerHTML = "";
      nota("Conversación de prueba reiniciada", "chat__fecha");
    });
  });
})();

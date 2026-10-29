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
    // Datos del simulador en atributos data-* (la política de contenido no admite scripts en línea).
    const raizSim = document.querySelector("[data-simulador-historial]");
    const sim =
      modo === "simulador" && raizSim
        ? { historial: raizSim.dataset.simuladorHistorial, numeroSugerido: raizSim.dataset.simuladorNumero }
        : null;
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
  /* CU15: vista previa y contador de una respuesta propia */
  document.querySelectorAll("[data-formulario-respuesta]").forEach((formulario) => {
    const texto = formulario.querySelector("[data-texto-respuesta]");
    const contador = formulario.querySelector("[data-contador-respuesta]");
    const vista = document.querySelector("[data-vista-previa]");
    if (!texto) return;
    function actualizar() {
      if (vista) {
        vista.textContent = "";
        formatear(vista, texto.value.trim() || "La respuesta aparece acá mientras la escribe.");
      }
      if (contador) contador.textContent = texto.value.length + " de " + texto.maxLength + " caracteres.";
    }
    texto.addEventListener("input", actualizar);
    actualizar();
  });

  /* CU15: prueba de la respuesta en edición con un mensaje de ejemplo (no guarda nada) */
  document.querySelectorAll("[data-probar-respuesta]").forEach((caja) => {
    const formulario = caja.querySelector("[data-probar-formulario]");
    const entrada = caja.querySelector("[data-probar-mensaje]");
    const resultado = caja.querySelector("[data-probar-resultado]");
    const datos = document.querySelector("[data-formulario-respuesta]");
    if (!formulario || !datos) return;

    function veredicto(texto, clase) {
      const p = document.createElement("p");
      p.className = "probar__veredicto" + (clase ? " probar__veredicto--" + clase : "");
      p.textContent = texto;
      return p;
    }

    formulario.addEventListener("submit", async (evento) => {
      evento.preventDefault();
      const mensaje = entrada.value.trim();
      if (!mensaje) { entrada.focus(); return; }
      resultado.textContent = "Probando…";
      try {
        const r = await enviarJSON(caja.dataset.url, {
          mensaje: mensaje,
          id_respuesta: caja.dataset.id || null,
          titulo: datos.querySelector("[name=titulo]").value,
          palabras: datos.querySelector("[name=palabras]").value,
          respuesta: datos.querySelector("[name=respuesta]").value,
        });
        resultado.textContent = "";
        resultado.appendChild(veredicto(r.explicacion, r.usa ? "si" : ""));
        const chat = document.createElement("div");
        chat.className = "vista-whatsapp";
        const propia = document.createElement("div");
        propia.className = "burbuja burbuja--propia";
        propia.textContent = mensaje;
        chat.appendChild(propia);
        (r.respuestas || []).map(normalizarRespuesta).forEach((respuesta) => {
          const b = document.createElement("div");
          b.className = "burbuja";
          formatear(b, respuesta.texto);
          chat.appendChild(b);
        });
        resultado.appendChild(chat);
      } catch (e) {
        resultado.textContent = "";
        resultado.appendChild(veredicto(e.message, "error"));
      }
    });
  });
  /* #8: el contador de pendientes se actualiza solo y, si el navegador lo permite, avisa */
  const panel = document.querySelector("[data-estado-pendientes]");
  if (panel) {
    const contador = panel.querySelector("[data-contador-pendientes]");
    const avisoNuevas = document.querySelector("[data-aviso-nuevas]");
    const botonAvisos = document.querySelector("[data-activar-avisos]");
    const tituloBase = document.title.replace(/^\(\d+\) /, "");
    const puedeNotificar = "Notification" in window;
    let ultima = null;

    function mostrar(estado) {
      const n = estado.pendientes || 0;
      if (contador) {
        contador.textContent = String(n);
        contador.hidden = n === 0;
        contador.setAttribute("aria-label", n + " pendientes");
      }
      document.title = n ? "(" + n + ") " + tituloBase : tituloBase;
      if (ultima !== null && estado.ultima && estado.ultima > ultima) {
        if (avisoNuevas) {
          avisoNuevas.querySelector("span").textContent = "Llegó una consulta nueva: " + estado.detalle + ".";
          avisoNuevas.hidden = false;
        }
        if (puedeNotificar && Notification.permission === "granted") {
          const aviso = new Notification(n === 1 ? "1 consulta pendiente" : n + " consultas pendientes", {
            body: estado.detalle, tag: "pendientes",
          });
          aviso.onclick = () => { window.focus(); window.location.href = panel.dataset.urlResumen; };
        }
      }
      if (estado.ultima !== undefined) ultima = Math.max(ultima || 0, estado.ultima);
    }

    async function consultar() {
      if (document.hidden) return;
      try {
        const respuesta = await fetch(panel.dataset.estadoPendientes, {
          headers: { "Accept": "application/json" }, credentials: "same-origin",
        });
        if (respuesta.ok) mostrar(await respuesta.json());
      } catch (e) { /* sin conexión: se reintenta en la próxima vuelta */ }
    }

    consultar();
    setInterval(consultar, 30000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) consultar(); });

    if (botonAvisos && puedeNotificar && Notification.permission === "default") {
      botonAvisos.hidden = false;
      botonAvisos.addEventListener("click", async () => {
        const permiso = await Notification.requestPermission();
        botonAvisos.hidden = permiso !== "default";
      });
    }
  }
})();

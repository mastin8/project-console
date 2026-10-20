/* Il coordinatore: la pagina che legge i registri di un workspace e mostra dove sta il lavoro.
   Sola lettura tranne il submit di una risposta, che passa dal server e quindi dal lock. */

const $ = (sel) => document.querySelector(sel);
/* Una fase e' aperta quando NON e' accettata. Elencare gli stati aperti uno per uno sembrava piu'
   preciso ed era piu' fragile: bastava che un progetto usasse `ready`, `blocked_dependency` o una
   parola sua — tutti stati legittimi del registro — e l'unita' spariva dalla vista «Aperte».
   L'unica cosa che il coordinatore deve sapere e' quale stato CHIUDE: `accepted`. */
const CLOSED_STATES = ["accepted"];
let snapshot = null;
let strictMode = false;
let filter = "open";
let loadedAt = 0;
let versioneVista = null;
let selectedBlock = null;
let consoleConfig = null;

/* L'interfaccia non conosce il progetto: nome, vista e fasi arrivano dal workspace. Se
   `/config.json` non risponde, quello che si vede resta quello di serie — la pagina funziona
   anche senza, e non finge un nome. */
async function loadConfig() {
  try {
    const response = await fetch("/config.json");
    if (!response.ok) return;
    consoleConfig = await response.json();
  } catch (error) {
    return;
  }
  const project = consoleConfig.project || "";
  const surface = consoleConfig.surface || "";
  if (project) {
    document.title = surface ? `${project} · ${surface}` : project;
    const nome = $("#brand-project");
    if (nome) nome.textContent = project;
    const vista = $("#brand-surface");
    if (vista) vista.textContent = surface ? `· ${surface}` : "";
    const mono = document.querySelector("#logo .mono");
    if (mono) mono.textContent = (project.trim()[0] || "•").toUpperCase();
  }
  const fasi = consoleConfig.phases || [];
  const hint = $("#path-hint");
  if (hint && fasi.length) {
    hint.append(
      document.createTextNode(
        ` Il ciclo di questo progetto ha ${fasi.length} fasi: ${fasi.join(" · ")}.`
      )
    );
  }
}

/* ------------------------------------------------------------------ utilità */
function h(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of [].concat(children)) if (child) node.append(child);
  return node;
}

const isOpen = (unit) => unit.phases.some((p) => !CLOSED_STATES.includes(p.status));
const hasIssues = (unit) => unit.phases.some((p) => ["needs_changes", "failed"].includes(p.status));

/* -------------------------------------------------------------------- avvio */
async function load() {
  let response;
  try {
    response = await fetch("/api/state");
  } catch (error) {
    $("#status-line").textContent = "Il servizio non risponde: il server è ancora in esecuzione?";
    return;
  }
  if (!response.ok) {
    $("#status-line").textContent = `Errore nel leggere lo stato (${response.status}).`;
    return;
  }
  snapshot = await response.json();
  loadedAt = Date.now();
  versioneVista = snapshot.versione || null;
  const avviso = $("#nuovo-registro");
  if (avviso) avviso.hidden = true;
  render(snapshot);
}

function render(data) {
  const s = data.summary;
  const obblighi = Number(
    s.open_obligations != null ? s.open_obligations : (data.obligations || []).length
  );
  const obblighiGate = Number(s.open_gate_obligations || 0);
  const debiti = Number(
    s.open_independence_debts != null
      ? s.open_independence_debts
      : (data.independence_debts || []).length
  );
  $("#generated").textContent = `aggiornato ${data.generated} · dati letti dai registri del progetto`;

  const ratio = s.units ? Math.round((s.accepted / s.units) * 100) : 0;
  const line = $("#status-line");
  // replaceChildren converte i non-nodi in testo: un null diventerebbe la parola "null"
  // in fondo alla riga (visto a schermo). Si passano solo i nodi che esistono.
  line.replaceChildren(...[
    h("b", { text: `${s.accepted} di ${s.units}` }),
    document.createTextNode(` unità accettate (${ratio}%)`),
    s.incoherent
      ? h("span", { class: "warnnote" }, [
          document.createTextNode(" · "),
          h("b", { text: String(s.incoherent) }),
          document.createTextNode(
            s.incoherent === 1
              ? " voce incoerente nel registro (fase respinta su unità già accettata)"
              : " voci incoerenti nel registro (fasi respinte su unità già accettate)"
          ),
        ])
      : null,
    obblighi
      ? h("span", { class: "warnnote" }, [
          document.createTextNode(" · "),
          h("b", { text: String(obblighi) }),
          document.createTextNode(
            obblighi === 1
              ? " obbligo aperto"
              : ` obblighi aperti${obblighiGate ? ` (${obblighiGate} bloccano la chiusura)` : ""}`
          ),
        ])
      : null,
    debiti
      ? h("span", { class: "warnnote" }, [
          document.createTextNode(" · "),
          h("b", { text: String(debiti) }),
          document.createTextNode(
            debiti === 1 ? " ratifica mancante" : " ratifiche mancanti"
          ),
        ])
      : null
  ].filter(Boolean));
  $("#rail").setAttribute("aria-valuenow", String(ratio));
  $("#rail").setAttribute("aria-valuetext", `${s.accepted} di ${s.units} unità accettate`);
  // transform, non width: l'animazione non deve far ricalcolare il layout.
  requestAnimationFrame(() => ($("#rail-fill").style.transform = `scaleX(${ratio / 100})`));

  renderQuestions(data.questions, data.decisions);
  renderNextPrompts(data.next_prompts);
  renderActivation(data);
  renderInbox(data.inbox);
  renderTestimone(data);
  mostraPagina();
  renderClaims(data.claims);
  renderAnswered(data.answered);
  renderBlocks();
  renderTally(data);
  renderFinishing(data);
  renderIndice(data);
  renderTabs(data);
  renderCoda(data.queue, data.applicazione);
  loadTimeline();
  refreshAge();
}

/* ----------------------------------------------------------------- domande */
/* «Cosa aspetta te» tiene insieme le due cose che appartengono davvero all'utente: le domande di
   un task e le decisioni di governo del lavoro. Prima le seconde stavano dentro la linea del
   tempo, fra i commit: erano raggiungibili ma fuori dal loro posto. */
function renderQuestions(questions, decisions) {
  const box = $("#questions");
  const gov = decisions || [];
  if (!questions.length && !gov.length) {
    // La sezione non si nasconde piu' da sola: `hidden` lo governa la barra delle schede (una
    // scheda vuota resta visibile e lo dice, invece di sparire e spostare le altre).
    box.replaceChildren(
      h("p", { class: "empty" }, [
        h("b", { text: "Niente da decidere. " }),
        document.createTextNode(
          "Nessuna domanda di un task e nessuna decisione di governo aspettano una tua risposta."
        ),
      ])
    );
    return;
  }
  // Le decisioni di governo hanno la stessa forma delle domande, controllo compreso: si
  // registrano da qui, non serve che una corsia le promuova a domanda formale.
  box.replaceChildren(...questions.map(questionCard), ...gov.map(governanceCard));
}

/* Una decisione di governo: la domanda, il perché è tua, le misure che la sostengono (chiuse, in
   un `details`, perché sono lunghe) e il controllo per registrarla. Se la voce dichiara le
   alternative si scelgono; altrimenti si scrive. Nessuna opzione dedotta dalla prosa. */
/* «IN PAROLE POVERE»: cosa la domanda tocca davvero, e in che stato sono quelle cose ADESSO.

   Perché esiste. Il 2026-10-15 l'utente ha risposto a una domanda sulle ratifiche scegliendo «si
   fornisce una firma distinta»: la domanda non diceva che, senza una seconda firma, quelle quattro
   ratifiche sarebbero rimaste respinte per sempre — e non esisteva. I numeri c'erano tutti nel
   registro; mancavano accanto alla domanda, dove servivano. Qui non si riscrive il testo di chi
   chiede (quello resta suo, parola per parola): si mettono i numeri che la piattaforma misura. */
function parolePovere(item) {
  const tocca = item.tocca || [];
  const firme = item.firme;
  const scope = item.blocked_scope;
  if (!tocca.length && !firme && !scope) return null;
  const parti = [];
  if (tocca.length) {
    parti.push(
      h("p", {}, [
        h("b", { text: tocca.length === 1 ? "Di cosa si parla: " : `Cosa tocca (${tocca.length}): ` }),
        document.createTextNode(tocca.map(rigaTocca).join(" · ")),
      ])
    );
  }
  if (scope) {
    parti.push(h("p", {}, [h("b", { text: "Resta fermo finché non rispondi: " }), document.createTextNode(scope)]));
  }
  if (firme) {
    const quante =
      firme.distinte === 0
        ? "nessuna presa con un titolare nominato"
        : firme.distinte === 1
          ? "una sola"
          : `${firme.distinte}`;
    parti.push(
      h("p", {}, [
        h("b", { text: `Firme nel registro: ${quante}. ` }),
        document.createTextNode(
          (firme.elenco.length ? `${firme.elenco.map((voce) => `${voce.chi} (${voce.prese} prese)`).join(", ")}. ` : "") +
            (firme.distinte <= 1
              ? "Una firma distinta non esiste ancora: una risposta che la pretende la deve anche creare, altrimenti quelle fasi restano respinte."
              : "")
        ),
      ])
    );
  }
  return h("div", { class: "plain" }, parti);
}

function rigaTocca(voce) {
  const pezzi = [`${voce.code} — ${voce.status}`];
  if (voce.respinte > 1) pezzi.push(`respinta ${voce.respinte} volte su ${voce.tentativi}`);
  if (voce.ostacolo) pezzi.push(`ostacolo «${voce.ostacolo}»${voce.bloccante ? " bloccante" : ""}`);
  if (voce.chi) {
    const chi = voce.chi.length > 90 ? `${voce.chi.slice(0, 87)}…` : voce.chi;
    pezzi.push(`lo deve: ${chi}`);
  }
  return pezzi.join(", ");
}

function governanceCard(item) {
  const options = item.options || [];
  const fieldset = options.length
    ? h("fieldset", { class: "opts" }, [
        h("legend", { text: "Scegli una risposta" }),
        ...options.map((option, index) => {
          const voce = typeof option === "string" ? { label: option, description: "" } : option;
          const input = h("input", {
            type: "radio",
            name: `gov-${item.id}`,
            value: voce.label,
            id: `gov-${item.id}-${index}`,
          });
          return h("label", { class: "opt" }, [
            input,
            h("span", {}, [
              h("b", { text: voce.label }),
              voce.description ? h("i", { class: "optwhy", text: ` — ${voce.description}` }) : null,
            ]),
          ]);
        }),
      ])
    : null;
  const textarea = h("textarea", {
    id: `answer-${item.id}`,
    placeholder: options.length
      ? "Oppure scrivi la decisione con parole tue…"
      : "La tua decisione, con parole tue…",
  });
  const message = h("p", { class: "msg", role: "status", "aria-live": "polite" });
  const submit = h("button", { type: "button", text: "Registra la decisione" });
  submit.addEventListener("click", () => sendDecision(item, fieldset, textarea, message, submit));
  if (fieldset) fieldset.addEventListener("change", () => (textarea.value = ""));

  const card = h(
    "article",
    { class: "qcard govcard", id: `q-card-${item.id}`, "aria-labelledby": `q-topic-${item.id}` },
    [
      h("h3", { class: "topic", id: `q-topic-${item.id}`, text: item.topic || item.id }),
      h("p", {
        class: "qmeta",
        text: `${item.id} · decisione di governo · non è il compito di un task: la prendono solo gli umani`,
      }),
      parolePovere(item),
      h("p", { class: "ask", text: item.question || "" }),
      item.why
        ? h("p", { class: "why" }, [
            h("b", { text: "Perché è tua: " }),
            document.createTextNode(item.why),
          ])
        : null,
      item.evidence
        ? h("details", { class: "explain" }, [
            h("summary", { text: "le misure che la sostengono" }),
            h("p", { text: item.evidence }),
          ])
        : null,
      fieldset,
      textarea,
      h("div", { class: "row" }, [
        submit,
        h("span", {
          class: "hint",
          text: "la scrittura passa dal lock e dalla validazione dei registri",
        }),
      ]),
      message,
    ]
  );
  return card;
}

/* Registrare una decisione è la stessa operazione di rispondere a una domanda: stesso lock, stessa
   validazione, stessa storia in fondo alla pagina. Cambia solo dove finisce. */
async function sendDecision(item, fieldset, textarea, message, button) {
  const chosen = fieldset ? fieldset.querySelector("input:checked") : null;
  const answer = textarea.value.trim() || (chosen ? chosen.value : "");
  const setMessage = (kind, text) => {
    message.className = `msg show ${kind}`;
    message.textContent = text;
  };
  if (!answer) {
    setMessage("err", "Scrivi la decisione: senza una decisione non registro nulla.");
    textarea.focus();
    return;
  }
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  setMessage("pending", "Scrittura in corso…");
  try {
    const response = await fetch("/api/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        decision_id: item.id,
        answer,
        label: chosen ? chosen.value : null,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `errore ${response.status}`);
    setMessage(
      "ok",
      `Registrata come ${payload.decision_id}. Campi scritti nei registri: ${payload.applied.join(", ")}. Chi deve applicarla la legge in decisions.yaml.`
    );
    setTimeout(load, 1600);
  } catch (error) {
    setMessage("err", `Non registrata: ${error.message}`);
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

/* ------------------------------------------------------------- scorciatoie */
/* La barra dice a che punto siamo e, soprattutto, porta dove serve: «respinte» filtra la vista e
   atterra sulla prima fase respinta in verifica, senza doverla cercare dentro i blocchi. */
function unitFacts(data) {
  const units = (data.blocks || []).flatMap((block) => block.units);
  const stalled = units.filter((unit) =>
    (unit.phases || []).some((phase) => ["needs_changes", "failed"].includes(phase.status))
  );
  const open = units.filter((unit) => !unit.accepted);
  return { units, stalled, open };
}

function renderTally(data) {
  const box = $("#tally");
  if (!box) return;
  const facts = unitFacts(data);
  // «In corso» = qualcuno tiene la fase (taken/active). «Attivate» = riservate e in attesa di un
  // esecutore (pre_registered/ready): due cose diverse, e la pagina non le confonde.
  const attive = (data.activated || []).filter((voce) =>
    ["active", "taken", "active_extension"].includes(voce.status)
  );
  const riservate = (data.activated || []).filter((voce) =>
    ["pre_registered", "ready"].includes(voce.status)
  );
  const perTe =
    (data.questions || []).length +
    (data.decisions || []).length +
    (data.next_prompts || []).filter((prompt) => prompt.state === "da_lanciare").length;
  const chips = [
    {
      label: `${facts.open.length} aperte`,
      title: "unità non ancora accettate: le vedi nella linea del tempo",
      disabled: !facts.open.length,
      run: () => {
        setFilter("open");
        jumpTo("timeline-section");
      },
    },
    {
      label: `${facts.stalled.length} respinte`,
      title: "fasi respinte in verifica: le filtro e ti porto sulla prima",
      disabled: !facts.stalled.length,
      warn: true,
      run: () => focusStalled(),
    },
    {
      label: `${attive.length} in corso`,
      title: "chi tiene una fase adesso (taken/active)",
      disabled: !attive.length,
      run: () => jumpTo("now-section"),
    },
    {
      label: `${riservate.length} attivate`,
      title: "riservate e in attesa di un esecutore: le vedi in «Cosa puoi attivare»",
      disabled: !riservate.length,
      warn: Boolean(riservate.length),
      run: () => jumpTo("activation-section"),
    },
    {
      label: `${perTe} per te`,
      title: "domande e prompt che aspettano una tua mossa",
      disabled: !perTe,
      accent: true,
      run: () => jumpToFirstYours(data),
    },
  ];
  box.replaceChildren(
    ...chips.map((chip) => {
      const node = h("button", {
        type: "button",
        class: `chip tally-chip${chip.warn ? " warn" : ""}${chip.accent ? " accent" : ""}`,
        title: chip.title,
        text: chip.label,
        disabled: chip.disabled,
      });
      node.addEventListener("click", chip.run);
      return node;
    })
  );
}

function setFilter(value) {
  const input = document.querySelector(`input[name="filter"][value="${value}"]`);
  if (!input || input.checked) return;
  input.checked = true;
  filter = value;
  renderBlocks();
  renderGantt();
}

function jumpTo(target) {
  const node = typeof target === "string" ? document.getElementById(target) : target;
  if (!node) return;
  // Se il bersaglio e' dentro una scheda chiusa, aprirla prima: dai tastini dello stato in alto
  // («per te») si chiede di andare su una cosa, non di aprire una scheda a mano.
  const scheda = SCHEDE.find((voce) => voce.sezione === node.id);
  if (scheda && node.hidden) scegliScheda(scheda.chiave, true);
  // Salto Istantaneo, non animato: si ripete spesso e uno scorrimento lungo farebbe perdere il
  // punto. Il `scroll-margin-top` tiene conto dell'header che resta appiccicato in cima.
  node.scrollIntoView({ block: "start" });
}

/* Un anello di stato, non un'animazione: si toglie da solo dopo il tempo di guardarlo. */
function flash(node) {
  if (!node) return;
  node.classList.add("flash");
  setTimeout(() => node.classList.remove("flash"), 1800);
}

function focusStalled() {
  setFilter("issues");
  const block = document.querySelector(".gblock.respinta");
  if (!block) return;
  const toggle = block.querySelector(".gtoggle");
  if (toggle && toggle.getAttribute("aria-expanded") !== "true") toggle.click();
  const unit = block.querySelector(".gunit.respinta") || block;
  unit.scrollIntoView({ block: "center" });
  flash(unit);
}

function jumpToFirstYours(data) {
  if ((data.questions || []).length || (data.decisions || []).length) {
    jumpTo("questions-section");
    const card = document.querySelector("#questions .qcard");
    flash(card);
    return;
  }
  const prompt = (data.next_prompts || []).find((item) => item.state === "da_lanciare");
  if (!prompt) return;
  const card = document.getElementById(`prompt-${prompt.anchor || prompt.number}`);
  jumpTo(card || "prompts-section");
  flash(card);
}

/* ------------------------------------------------------ prompt da eseguire */
/* Lo stato non arriva scritto a mano: lo ricava il server dai registri e dai file di consegna,
   con la regola di tools/next_prompts.py — una sola implementazione per questa pagina e per la
   vista statica STATUS.html, cosi' le due non possono raccontare cose diverse. */
const PROMPT_STATE = {
  fatto: "fatto",
  in_azione: "in azione",
  da_lanciare: "da lanciare",
  parziale: "parziale",
  ignoto: "ignoto",
};

/* I gruppi in cui si leggono i prompt. `respinta` non è uno stato del registro: è un prompt
   consegnato la cui verifica ha detto di no, ed è la cosa che va distinta a colpo d'occhio da
   «già fatto» — per questo il risolutore la assegna lì e non fra i consegnati. */
const PROMPT_GROUPS = [
  {
    key: "da_lanciare",
    label: "Da lanciare",
    short: "da lanciare",
    hint: "pronti da incollare in una chat nuova",
    tone: "accent",
  },
  {
    key: "in_azione",
    label: "In azione",
    short: "in azione",
    hint: "già presi: lanciarli di nuovo sarebbe un secondo esecutore",
    tone: "warn",
  },
  {
    key: "respinta",
    label: "Consegna respinta",
    short: "respinte",
    one: "respinta",
    hint: "consegnati, e la verifica ha detto di no",
    tone: "bad",
  },
  {
    key: "parziale",
    label: "Consegna parziale",
    short: "parziali",
    hint: "una parte della consegna esiste su disco",
    tone: "warn",
  },
  {
    key: "ignoto",
    label: "Da verificare",
    short: "da verificare",
    hint: "nel testo non c'è un codice del registro",
    tone: "warn",
  },
  {
    key: "fatto",
    label: "Già consegnati",
    short: "già consegnati",
    hint: "la consegna esiste su disco",
    tone: "ok",
    chiuso: true,
  },
];

function renderNextPrompts(prompts) {
  const box = $("#prompts");
  const count = $("#prompts-count");
  if (!box || !count) return;
  const list = prompts || [];
  const gruppi = PROMPT_GROUPS.map((group) => ({
    ...group,
    items: list.filter((item) => (item.group || item.state) === group.key),
  })).filter((group) => group.items.length);
  count.textContent = gruppi.length
    ? gruppi
        .map(
          (group) =>
            `${group.items.length} ${
              group.items.length === 1 && group.one ? group.one : group.short
            }`
        )
        .join(" · ")
    : `${list.length} nel quaderno`;
  if (!list.length) {
    box.replaceChildren(
      h("p", { class: "empty" }, [
        h("b", { text: "Nessun prompt nel quaderno. " }),
        document.createTextNode(
          "Le sezioni numerate di PARALLEL-PROMPTS.md compaiono qui, con lo stato ricavato."
        ),
      ])
    );
    return;
  }
  // I gruppi si leggono nell'ordine in cui si decide: cosa posso lanciare, cosa è già preso, cosa
  // è tornato indietro, e infine la storia — chiusa, perché non serve aprirla per lavorare.
  const parti = [];
  gruppi.forEach((group) => {
    const testa = [
      h("span", { class: "mark", "aria-hidden": "true" }),
      h("span", { class: "plabel", text: group.label }),
      h("span", { class: "pcount", text: String(group.items.length) }),
      h("span", { class: "phint", text: group.hint }),
    ];
    if (group.chiuso) {
      parti.push(
        h("details", { class: `pgroupbox ${group.tone}`, id: `prompts-${group.key}` }, [
          h("summary", {}, [h("h3", { class: "pgroup" }, testa)]),
          h("div", { class: "pgroupbody" }, group.items.map(promptCard)),
        ])
      );
    } else {
      parti.push(
        h("div", { class: `pgroupbox ${group.tone}`, id: `prompts-${group.key}` }, [
          h("h3", { class: "pgroup" }, testa),
          h("div", { class: "pgroupbody" }, group.items.map(promptCard)),
        ])
      );
    }
  });
  box.replaceChildren(...parti);
}

function promptCard(prompt) {
  const registry = prompt.registry || {};
  const deliveries = prompt.deliverables || [];
  const written = deliveries.filter((item) => item.exists).length;
  const facts = [];
  if (deliveries.length) {
    const first = deliveries[0];
    facts.push(
      deliveries.length === 1
        ? `consegna ${first.path} — ${first.exists ? `esiste dal ${first.mtime}` : "assente"}`
        : `consegne ${written}/${deliveries.length}: ${first.path}${first.exists ? "" : " (assente)"}`
    );
  }
  if (registry.found) {
    facts.push(
      `registro: ${registry.status} in ${registry.where}${registry.live ? " · viva" : ""}`
    );
    if (registry.taken_at) facts.push(`presa ${registry.taken_at}`);
    if (registry.owner_short) facts.push(registry.owner_short);
  } else if (prompt.anchor) {
    facts.push("nessuna voce con questo codice nel registro");
  }
  const code = prompt.anchor
    ? `${prompt.anchor}${prompt.anchor_kind === "obbligo" ? " · obbligo" : ""}`
    : "senza codice";
  const message = h("span", { class: "msg", role: "status", "aria-live": "polite" });
  const copy = h("button", { type: "button", class: "ghost", text: "Copia il prompt" });
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(prompt.prompt || "");
      message.className = "msg show ok";
      message.textContent = "copiato: incollalo come primo messaggio di una chat nuova.";
    } catch (error) {
      message.className = "msg show err";
      message.textContent = `non copiato (${error.message}): seleziona il testo e copialo a mano.`;
    }
  });
  // Attivare da qui: se il codice del prompt e' una fase attivabile, il pulsante la riserva e
  // deposita l'ordine. Se e' gia' attivata, si puo' togliere la riserva. Se il codice non e' una
  // fase del registro (ci sono prompt che nominano un obbligo), il pulsante non compare: meglio
  // niente che un pulsante che fallisce.
  const attivabile = ((snapshot && snapshot.activatable) || []).find((v) => v.phase === prompt.anchor);
  const attivata = ((snapshot && snapshot.activated) || []).find(
    (v) => v.phase === prompt.anchor && ["pre_registered", "ready"].includes(v.status)
  );
  const attiva = [];
  if (attivata) {
    attiva.push(activationButton(prompt.anchor, "release", "Rilascia la fase", message, false));
  } else if (attivabile) {
    attiva.push(
      activationButton(
        prompt.anchor,
        "activate",
        prompt.state === "da_lanciare" ? "Attiva questo prompt" : "Attiva la fase",
        message,
        false
      )
    );
  }
  return h("article", { class: "prompt", id: `prompt-${prompt.anchor || prompt.number}`, "data-state": prompt.state }, [
    h("div", { class: "ph" }, [
      h("span", { class: "state" }, [
        h("i", { class: "mark", "aria-hidden": "true" }),
        document.createTextNode(PROMPT_STATE[prompt.state] || prompt.state),
      ]),
      h("span", { class: "code", text: `§${prompt.number} · ${code}` }),
    ]),
    h("p", { class: "ptitle", text: prompt.title || "" }),
    facts.length ? h("p", { class: "pmeta", text: facts.join(" · ") }) : null,
    prompt.notes && prompt.notes.length
      ? h("p", { class: `pflag${(prompt.flags || []).includes("esito_respinto") ? " bad" : ""}` }, [
          h("b", { text: "Da guardare: " }),
          document.createTextNode(prompt.notes.join("; ")),
        ])
      : null,
    h("div", { class: "prow" }, [
      h("button", {
        type: "button",
        class: "ghost",
        text: "Leggi il prompt",
        onclick: () =>
          apriTesto(`${prompt.anchor || "§" + prompt.number} — il prompt`, prompt.prompt, {
            copia: true,
            file: `prompt-${prompt.anchor || prompt.number}.md`,
          }),
      }),
      copy,
      prompt.prompt
        ? h("button", {
            type: "button",
            class: "ghost",
            text: "Salva come file",
            onclick: () =>
              scaricaFile(prompt.prompt, `prompt-${prompt.anchor || prompt.number}.md`),
          })
        : null,
      ...attiva,
      message,
    ]),
    prompt.prompt
      ? null
      : h("p", {
          class: "pmeta",
          text: "testo non estraibile dal quaderno: apri la sezione nel file.",
        }),
  ]);
}

/* La pagina e' un'istantanea: il registro e' vivo e cambia sotto. Dire da quanto e' ferma
   questa fotografia e' l'unico modo onesto di mostrarla. */
function refreshAge() {
  const node = $("#generated");
  if (!node || !loadedAt || !snapshot) return;
  const minutes = Math.floor((Date.now() - loadedAt) / 60000);
  const age = minutes < 1 ? "adesso" : minutes === 1 ? "1 minuto fa" : `${minutes} minuti fa`;
  node.textContent = `istantanea di ${snapshot.generated} (${age}) · i registri del progetto cambiano sotto`;
}
setInterval(refreshAge, 30000);

/* UNA PRESA APPLICATA DOPO IL CARICAMENTO RESTAVA INVISIBILE. La pagina e' un'istantanea, e finora
   l'unico modo di accorgersene era leggere l'eta' in testa o premere «Ricarica». Qui si guarda solo
   il tempo di scrittura dei registri (due `stat`), non si ricarica da soli: un avviso compare, e il
   clic resta dell'utente. Si tace mentre si scrive o si legge un dialogo. */
async function controllaVersione() {
  if (document.visibilityState !== "visible" || !versioneVista) return;
  if (document.querySelector("dialog[open]")) return;
  const attivo = document.activeElement;
  if (attivo && /^(INPUT|TEXTAREA|SELECT)$/.test(attivo.tagName)) return;
  try {
    const risposta = await fetch("/api/versione", { cache: "no-store" });
    if (!risposta.ok) return;
    const nuova = await risposta.json();
    if (
      nuova.state_mtime_ns !== versioneVista.state_mtime_ns ||
      nuova.tasks_mtime_ns !== versioneVista.tasks_mtime_ns
    ) {
      const avviso = $("#nuovo-registro");
      if (avviso) avviso.hidden = false;
    }
  } catch {
    // Il prossimo giro riprova: un avviso mancato non deve rompere la pagina.
  }
}
setInterval(controllaVersione, 20000);

function questionCard(question) {
  const fieldset = h("fieldset", { class: "opts" }, [h("legend", { text: "Scegli una risposta" })]);
  (question.options || []).forEach((option, index) => {
    const voce = typeof option === "string" ? { label: option, description: "" } : option;
    const input = h("input", {
      type: "radio",
      name: `opt-${question.id}`,
      value: voce.label,
      id: `opt-${question.id}-${index}`,
    });
    fieldset.append(
      h("label", { class: "opt" }, [
        input,
        h("span", {}, [
          h("b", { text: voce.label }),
          voce.description ? h("i", { class: "optwhy", text: ` — ${voce.description}` }) : null,
        ]),
      ])
    );
  });

  const textarea = h("textarea", {
    id: `answer-${question.id}`,
    placeholder: "Oppure scrivi la risposta con parole tue…",
  });
  const message = h("p", { class: "msg", role: "status", "aria-live": "polite" });
  const submit = h("button", { type: "button", text: "Invia la risposta" });
  submit.addEventListener("click", () => send(question, fieldset, textarea, message, submit));
  // Scegliere un'opzione svuota il testo libero: due risposte insieme sarebbero ambigue.
  fieldset.addEventListener("change", () => (textarea.value = ""));

  return h("article", { class: "qcard", id: `q-card-${question.id}`, "aria-labelledby": `q-topic-${question.id}` }, [
    h("h3", { class: "topic", id: `q-topic-${question.id}`, text: question.topic || question.id }),
    h("p", {
      class: "qmeta",
      text: `${question.id} · aperta il ${question.asked_on || "?"} · blocca ${(question.blocks || []).join(", ") || "—"}`,
    }),
    parolePovere(question),
    h("p", { class: "ask", text: question.question || "" }),
    question.why
      ? h("p", { class: "why" }, [h("b", { text: "Perché è aperta: " }), document.createTextNode(question.why)])
      : null,
    fieldset,
    h("label", { class: "answer-label", for: `answer-${question.id}` }, [
      document.createTextNode(`${question.id} — la tua risposta, oppure l'opzione scelta qui sopra`),
    ]),
    textarea,
    h("div", { class: "row" }, [
      submit,
      h("span", {
        class: "hint",
        text: "la scrittura passa dal lock e dalla validazione dei registri",
      }),
    ]),
    message,
  ]);
}

async function send(question, fieldset, textarea, message, button) {
  const chosen = fieldset.querySelector("input:checked");
  const answer = textarea.value.trim() || (chosen ? chosen.value : "");
  const setMessage = (kind, text) => {
    message.className = `msg show ${kind}`;
    message.textContent = text;
  };
  if (!answer) {
    setMessage("err", "Scegli un'opzione oppure scrivi la risposta: senza una risposta non registro nulla.");
    textarea.focus();
    return;
  }
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  setMessage("pending", "Scrittura in corso…");
  try {
    const response = await fetch("/api/answer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question_id: question.id,
        answer,
        label: chosen ? chosen.value : null,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      if (payload.code === "not_stalled") {
        message.className = "msg show err";
        message.textContent = `Il registro e' cambiato mentre guardavi: ${payload.task_id} ora e' «${payload.current_status}». Aggiorno la pagina…`;
        setTimeout(load, 1500);
        return;
      }
      throw new Error(payload.error || `errore ${response.status}`);
    }
    setMessage(
      "ok",
      `Registrata come ${payload.decision_id}. Campi scritti nei registri: ${payload.applied.join(", ")}.`
    );
    setTimeout(load, 1400);
  } catch (error) {
    setMessage("err", `Non registrata: ${error.message}`);
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
}

/* -------------------------------------------------------- prese e risposte */
function renderClaims(claims) {
  const box = $("#claims");
  if (!claims.length) {
    box.replaceChildren(
      h("p", { class: "empty" }, [
        h("b", { text: "Nessuna presa viva. " }),
        document.createTextNode("Nessuno sta scrivendo su una fase in questo momento."),
      ])
    );
    return;
  }
  // «IN CORSO» NON VUOL DIRE «QUALCUNO STA LAVORANDO». Il registro dice chi ha preso la fase e quando:
  // se sono passate ore e non c'e' un tentativo nuovo, quello che la pagina chiamava «in corso» e' una
  // presa MORTA — e il difetto peggiore e' che non c'era modo di scioglierla. Misurato il 2026-10-16:
  // `REG03T` tenuta da 25 ore da una corsia che non ha scritto un byte, e l'utente convinto che
  // qualcuno ci stesse lavorando.
  box.replaceChildren(
    h(
      "ul",
      { class: "claims" },
      claims.map((claim) => {
        const ore = oreDa(claim.taken_at);
        const morta = ore !== null && ore >= 2;
        const riga = h("li", {}, [
          h("span", { class: "id" }, [
            document.createTextNode(claim.task_id || ""),
            claim.phase ? h("span", { class: "phase", text: ` · ${claim.phase}` }) : null,
          ]),
          h("span", { class: "who", title: claim.owner || "", text: claim.owner || "" }),
          h("span", {
            class: morta ? "when warnnote" : "when",
            text: `${claim.taken_at || ""}${ore !== null ? ` · ${ore < 1 ? "meno di un'ora" : `${ore.toFixed(0)} ore`} fa` : ""}`,
          }),
        ]);
        if (morta) {
          const message = h("span", { class: "msg", role: "status", "aria-live": "polite" });
          riga.append(
            h("div", { class: "actmeta" }, [
              h("b", { class: "warnnote", text: "presa probabilmente morta: " }),
              document.createTextNode(
                `da ${ore.toFixed(0)} ore, e nessun tentativo nuovo. Se quella corsia non è più viva, la presa la sta solo bloccando.`
              ),
            ]),
            h("div", { class: "actactions" }, [
              h("button", {
                type: "button",
                class: "actbtn release",
                text: "Annulla la presa",
                title: "toglie la presa dal registro: la fase torna libera e si può rimandare a una corsia viva",
                onclick: async () => {
                  try {
                    const risposta = await fetch("/api/activate", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ target: claim.task_id, action: "release" }),
                    });
                    const payload = await risposta.json();
                    if (!risposta.ok) throw new Error(payload.error || `errore ${risposta.status}`);
                    message.className = "msg show ok";
                    message.textContent = "presa annullata: la fase è di nuovo libera.";
                    setTimeout(load, 1500);
                  } catch (error) {
                    message.className = "msg show err";
                    message.textContent = `non fatto: ${error.message}`;
                  }
                },
              }),
            ]),
            message
          );
        }
        return riga;
      })
    )
  );
}

/* Quante ore fa: `taken_at` arriva dal registro come data (anche senza fuso: allora vale l'ora
   locale, come in tutto il resto del tool). */
function oreDa(quando) {
  if (!quando) return null;
  const quandoData = new Date(String(quando).replace(" ", "T"));
  if (Number.isNaN(quandoData.getTime())) return null;
  return (Date.now() - quandoData.getTime()) / 3600000;
}

function renderAnswered(answered) {
  /* Una risposta si legge come una frase. Puo' arrivare come stringa, come alternativa scelta
     (`{label, description}`), o — caso registrato sul campo — come STRINGA che CONTIENE quel
     dizionario, perche' chi l'ha scritta nel registro l'ha serializzata cosi'. Il registro resta
     quello che e'; qui si mostra il contenuto, non la sintassi: `{'label': 'Si fornisce una firma
     distinta', …}` a schermo e' illeggibile proprio dove devi riconoscere cosa hai deciso. */
  const leggibile = (valore) => {
    if (!valore) return { testo: "", spiegazione: "" };
    if (typeof valore === "object") {
      return {
        testo: String(valore.label || valore.answer || valore.testo || "").trim(),
        spiegazione: String(valore.description || valore.consequence || "").trim(),
      };
    }
    const testo = String(valore).trim();
    const etichetta = testo.match(/'label':\s*'([^']*)'/);
    if (etichetta) {
      const descrizione = testo.match(/'description':\s*'([^']*)'/);
      return { testo: etichetta[1], spiegazione: descrizione ? descrizione[1] : "" };
    }
    return { testo, spiegazione: "" };
  };
  const box = $("#answered");
  if (!answered || !answered.length) {
    box.replaceChildren(
      h("p", { class: "empty" }, [
        h("b", { text: "Nessuna risposta registrata. " }),
        document.createTextNode("Le risposte che dai compaiono qui, con la decisione che hanno prodotto."),
      ])
    );
    return;
  }
  box.replaceChildren(
    h(
      "ul",
      { class: "answers" },
      answered
        .slice()
        .reverse()
        .map((item) =>
          h("li", {}, [
            h("div", { class: "topic", text: item.topic || item.id }),
            h("div", {
              class: "qmeta",
              text: [item.id, item.date, item.decision_ref ? `decisione ${item.decision_ref}` : null]
                .filter(Boolean)
                .join(" · "),
            }),
            h("p", { class: "said" }, [
              h("b", { text: "Hai risposto: " }),
              document.createTextNode(leggibile(item.answer).testo),
            ]),
            leggibile(item.answer).spiegazione
              ? h("p", { class: "saidwhy", text: leggibile(item.answer).spiegazione })
              : null,
            item.question || item.context
              ? h("details", {}, [
                  h("summary", { text: "la domanda e il contesto registrato" }),
                  item.question ? h("p", { class: "why", text: `Domanda: ${item.question}` }) : null,
                  item.context ? h("p", { class: "why", text: item.context }) : null,
                ])
              : null,
          ])
        )
    )
  );
}

/* ---------------------------------------------------------------- le schede */
/* Dentro «Adesso» c'e' piu' di una cosa da guardare, e prima erano cinque sezioni una sotto
   l'altra: per arrivare a «Risposte che hai gia' dato» si scorreva tutto. Qui sono schede.

   Due regole che tengono insieme la cosa:

   * il numero tondo e' una MISURA, non una decorazione: dice quante cose ci sono in quella scheda
     prima di aprirla. Rosso = aspetta te; verde = l'hai gia' fatto. Si vede solo quando c'e'
     qualcosa da dire, perche' un badge con dentro zero e' un allarme che suona per niente;
   * la scheda scelta sta nell'indirizzo (`#posta`, `#corso`...): la pagina si ricarica da sola ogni
     30 secondi e senza quello tornerebbe sempre alla prima, mentre tu stai leggendo la terza. */
const SCHEDE = [
  { chiave: "oggi", sezione: "activation-section", etichetta: "Cosa fare adesso" },
  { chiave: "posta", sezione: "inbox-section", etichetta: "Posta in arrivo" },
  { chiave: "attesa", sezione: "questions-section", etichetta: "Cosa aspetta te" },
  { chiave: "corso", sezione: "now-section", etichetta: "In corso adesso" },
  { chiave: "date", sezione: "answered-section", etichetta: "Risposte che hai già dato" },
];
let schedaScelta = null;

function schedaDaIndirizzo() {
  const richiesta = (location.hash || "").replace("#", "").toLowerCase();
  return SCHEDE.some((scheda) => scheda.chiave === richiesta) ? richiesta : SCHEDE[0].chiave;
}

/* I pulsanti si costruiscono UNA volta: rifarli a ogni ricarica della pagina (ogni 30 secondi)
   butterebbe via il fuoco da tastiera e la posizione di scorrimento della barra. Dopo, si aggiorna
   solo quello che cambia: numero, scheda scelta, pannello visibile. */
function preparaScheda() {
  const barra = $(".schede");
  if (!barra || barra.dataset.pronta) return;
  barra.dataset.pronta = "1";
  barra.addEventListener("click", (evento) => {
    const bottone = evento.target.closest(".scheda");
    if (bottone) scegliScheda(bottone.dataset.scheda, true);
  });
  barra.addEventListener("keydown", (evento) => {
    const passo = { ArrowRight: 1, ArrowLeft: -1, Home: "prima", End: "ultima" }[evento.key];
    if (!passo) return;
    evento.preventDefault();
    const bottoni = [...barra.querySelectorAll(".scheda")];
    const attuale = bottoni.findIndex((bottone) => bottone.dataset.scheda === schedaScelta);
    const prossima =
      passo === "prima"
        ? 0
        : passo === "ultima"
          ? bottoni.length - 1
          : (attuale + passo + bottoni.length) % bottoni.length;
    scegliScheda(bottoni[prossima].dataset.scheda, true);
    bottoni[prossima].focus();
  });
  scegliScheda(schedaDaIndirizzo(), false);
}

function scegliScheda(chiave, scriviIndirizzo) {
  if (!SCHEDE.some((scheda) => scheda.chiave === chiave)) return;
  schedaScelta = chiave;
  document.querySelectorAll(".schede .scheda").forEach((bottone) => {
    const scelto = bottone.dataset.scheda === chiave;
    bottone.setAttribute("aria-selected", scelto ? "true" : "false");
    bottone.tabIndex = scelto ? 0 : -1;
  });
  SCHEDE.forEach((scheda) => {
    const sezione = document.getElementById(scheda.sezione);
    if (sezione) sezione.hidden = scheda.chiave !== chiave;
  });
  if (scriviIndirizzo && location.hash !== `#${chiave}`) {
    history.replaceState(null, "", `#${chiave}`);
  }
}

/* I numeri. Ognuno e' una cosa che si conta in pagina, non una stima: le righe che hai in quella
   scheda. Per «Risposte che hai gia' dato» il numero e' quello che hai alle spalle, ed e' verde
   perche' non chiede niente. */
function numeriSchede(data) {
  const posta = data.inbox || {};
  const coda =
    (data.obligations || []).length +
    (data.independence_debts || []).length +
    (data.owed || []).length +
    (data.activatable || []).filter(
      (voce) => !voce.altrove && !(voce.waiting_on || []).length
    ).length +
    (data.activated || []).filter((voce) => ["pre_registered", "ready"].includes(voce.status))
      .length;
  return {
    oggi: { numero: coda, tono: "bad", cosa: "da gestire" },
    posta: { numero: posta.non_lavorate || 0, tono: "bad", cosa: "da lavorare" },
    attesa: { numero: data.summary.open_questions || 0, tono: "bad", cosa: "aspettano te" },
    corso: { numero: (data.claims || []).length, tono: "bad", cosa: "in corso" },
    date: { numero: (data.answered || []).length, tono: "ok", cosa: "già risposte" },
  };
}

function renderTabs(data) {
  const barra = $(".schede");
  if (!barra) return;
  const numeri = numeriSchede(data);
  SCHEDE.forEach((scheda) => {
    const bottone = barra.querySelector(`.scheda[data-scheda="${scheda.chiave}"]`);
    if (!bottone) return;
    const voce = numeri[scheda.chiave];
    bottone.replaceChildren(document.createTextNode(scheda.etichetta));
    if (voce.numero > 0) {
      // Il numero e la sua spiegazione stanno nello stesso nodo — fuori, il `gap` della scheda
      // aggiungerebbe una fessura dopo il numero. La cifra e' muta per chi legge con uno schermo
      // (un «8» da solo non dice otto cosa) e la frase e' li' accanto, invisibile ma letta.
      bottone.append(
        h("span", { class: "scheda-numero", "data-tono": voce.tono }, [
          h("span", { "aria-hidden": "true", text: String(voce.numero) }),
          h("span", { class: "vh", text: `${voce.numero} ${voce.cosa}` }),
        ])
      );
    }
  });
}

window.addEventListener("hashchange", () => scegliScheda(schedaDaIndirizzo(), false));

/* LA CODA DELLE TRANSIZIONI. Gli agenti non scrivono i registri: depositano una richiesta per ogni
   modifica, e un programma le applica. Finche' nessuno le applica, il registro racconta il passato —
   e con lui questa pagina: lo stato delle fasi, le respinte, le ratifiche. Misurato il 2026-10-16:
   129 richieste in coda, 93 ferme da piu' di dodici ore, e una fase consegnata alle 10:53 che il
   registro leggeva ancora «respinta».

   Perche' sta SOPRA le schede e non dentro una: vale per tutte. Se la coda e' vuota, non si vede:
   un avviso che c'e' sempre e' un avviso che non si legge piu'. */
function renderCoda(coda, applicazione) {
  const sezione = $("#coda-section");
  if (!sezione) return;
  const numeri = $("#coda-numeri");
  const hint = $("#coda-hint");
  const azioni = $("#coda-copia");
  const liste = $("#coda-liste");
  const esito = $("#coda-esito");
  if (!coda || !coda.totale) {
    sezione.hidden = true;
    return;
  }
  sezione.hidden = false;
  numeri.textContent = [
    `${coda.totale} richieste mai applicate`,
    coda.ferme ? `${coda.ferme} ferme da più di ${coda.soglia_ore} ore` : null,
    coda.sospette_totali ? `${coda.sospette_totali} da guardare prima di applicare` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  hint.replaceChildren(
    h("b", { text: "Il registro è indietro rispetto ai file. " }),
    document.createTextNode(
      `Le ${coda.totale} richieste degli agenti non sono ancora state applicate: stato delle fasi, respinte e ratifiche possono essere vecchi. `
    ),
    document.createTextNode(
      (coda.da_applicare || 0)
        ? "Il pulsante le applica: fa prima una copia dei registri, salta quelle segnalate e ti dice com'è andata."
        : `Nessuna di queste si può applicare da sola: ${coda.sospette_totali} vanno guardate prima (elenco qui sotto), e l'applicatore ha già rifiutato le altre.`
    )
  );

  // Tre passi, e il primo non e' una formalita': i registri di questo progetto non sono tracciati da
  // git, quindi la copia E' l'unico «annulla» che esiste. La prova va su UNA richiesta sola: il
  // dry-run stampa il registro intero (2,3 MB) una volta per file, e su 129 file sono 300 MB.
  const comandi = [
    "# se preferisci farlo a mano, questi sono i tre passi (la copia E' l'unica via del ritorno)",
    coda.comandi.copia,
    coda.comandi.prova,
    coda.comandi.applica,
  ].join("\n");
  // IL PULSANTE CHE FA IL LAVORO. L'utente: «secondo me deve farlo... che cazzo ne so io cosa devo
  // fare». Ha ragione: il tool sa cos'e' la coda e come si applica, quindi la applica lui — copia di
  // sicurezza compresa — e ti dice cosa ha fatto.
  const stato = applicazione || {};
  // Quando le uniche rimaste sono quelle segnalate, il pulsante non ha niente da fare: dirlo, invece
  // di offrire un clic che non cambia niente e far credere che il tool non funzioni.
  const daApplicare = coda.da_applicare || 0;
  const avvia = h("button", {
    type: "button",
    id: "coda-applica",
    text: daApplicare ? `Applica la coda (${daApplicare})` : "Niente da applicare",
    disabled: Boolean(stato.in_corso) || !daApplicare,
    onclick: async () => {
      avvia.disabled = true;
      esito.className = "msg show pending";
      esito.textContent = "avvio…";
      try {
        const risposta = await fetch("/api/coda/apply", { method: "POST" });
        const payload = await risposta.json();
        if (!risposta.ok) throw new Error(payload.error || `errore ${risposta.status}`);
        esito.className = "msg show ok";
        esito.textContent =
          "applicazione avviata: fa una copia dei registri, applica a blocchi e salta quelle segnalate. La pagina si aggiorna da sola.";
      } catch (error) {
        esito.className = "msg show err";
        esito.textContent = `non avviata: ${error.message}`;
        avvia.disabled = false;
      }
    },
  });
  const copiaTutto = h("button", {
    type: "button",
    class: "ghost",
    id: "coda-copia-bottone",
    text: "Copia i comandi (a mano)",
  });
  azioni.replaceChildren(avvia, copiaTutto);
  if (stato.in_corso) {
    esito.className = "msg show pending";
    esito.textContent = `in corso: ${stato.fatte || 0} di ${stato.totali || "?"} applicate, ${
      stato.restanti ?? "?"
    } in coda.`;
  } else if (stato.esito) {
    esito.className = "msg show ok";
    esito.textContent = `${stato.quando}: ${stato.esito}${
      (stato.copie || []).length ? ` — copie: ${stato.copie.join(", ")}` : ""
    }`;
  }
  $("#coda-copia-bottone").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(comandi);
      esito.className = "msg show ok";
      esito.textContent = "copiati: incollali nel terminale del progetto, la prova prima.";
    } catch (error) {
      esito.className = "msg show err";
      esito.textContent = `non copiati (${error.message}): il testo è qui sotto, selezionalo.`;
    }
  });

  const parti = [];
  parti.push(h("pre", { class: "coda-comandi-testo", text: comandi }));
  if (coda.per_fase && coda.per_fase.length) {
    parti.push(
      h("p", {
        class: "coda-riga",
        text: `Le più numerose: ${coda.per_fase.map(([fase, n]) => `${fase} ${n}`).join(" · ")}`,
      })
    );
  }
  if (coda.indietro && coda.indietro.length) {
    parti.push(
      h("details", { class: "coda-dettaglio" }, [
        h("summary", {
          text: `Il registro è indietro su ${coda.indietro.length} fas${coda.indietro.length === 1 ? "e" : "i"}: cosa dicono il registro e i file`,
        }),
        h(
          "ul",
          { class: "coda-elenco" },
          coda.indietro.map((voce) =>
            h("li", {}, [
              h("code", { text: voce.phase }),
              document.createTextNode(` — registro: ${voce.registro}; file: ${voce.disco}`),
            ])
          )
        ),
      ])
    );
  }
  if (coda.sospette && coda.sospette.length) {
    parti.push(
      h("details", { class: "coda-dettaglio" }, [
        h("summary", {
          text: `${coda.sospette_totali} richieste da guardare prima di applicare (le più vecchie sono quasi sempre sostituite da una più recente)`,
        }),
        h(
          "ul",
          { class: "coda-elenco" },
          coda.sospette.map((voce) =>
            h("li", {}, [
              h("code", { text: voce.file }),
              document.createTextNode(` — ${voce.motivi.join("; ")}`),
            ])
          )
        ),
      ])
    );
  }
  liste.replaceChildren(...parti);
}

/* ------------------------------------------------------------- attivazione */
/* PAGINE: intestazione e tastini restano su tutte; il contenuto cambia. La coda e' la pagina che si
   guarda tornando — corta, ordinata per leva, un pulsante per riga; il testo lungo va nel dialogo. */
const PAGINE = {
  "/": ["adesso", "Adesso"],
  "/svolto": ["svolto", "Lavoro svolto"],
  "/tempo": ["tempo", "Tempo"],
  "/testimone": ["testimone", "Testimone"],
  "/prompt": ["prompt", "Prompt"],
  "/percorso": ["percorso", "Percorso"],
};

function paginaCorrente() {
  const percorso = (location.pathname.replace(/\/+$/, "") || "/").toLowerCase();
  return (PAGINE[percorso] || PAGINE["/"])[0];
}

function mostraPagina() {
  const pagina = paginaCorrente();
  document.body.dataset.page = pagina;
  document.querySelectorAll(".pagenav a").forEach((link) => {
    if (link.dataset.nav === pagina) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  const trovata = Object.keys(PAGINE).find((chiave) => PAGINE[chiave][0] === pagina);
  const nome = (PAGINE[trovata] || [])[1] || "";
  const progetto = (consoleConfig && consoleConfig.project) || "";
  document.title = [progetto, nome].filter(Boolean).join(" · ");
}

/* I testi lunghi (prompt, dichiarazioni, report) vivono in un dialogo: la pagina resta una lista di
   righe, e il testo e' a un clic con «Copia» accanto. */
function apriTesto(titolo, testo, opzioni = {}) {
  const dialog = $("#report-dialog");
  $("#report-title").textContent = titolo;
  $("#report-body").textContent = testo || "—";
  let azioni = $("#report-actions");
  if (!azioni) {
    azioni = h("div", { id: "report-actions", class: "row" });
    dialog.insertBefore(azioni, $("#report-body"));
  }
  azioni.replaceChildren();
  if (opzioni.copia) {
    const esito = h("span", { class: "msg", role: "status", "aria-live": "polite" });
    const copia = h("button", { type: "button", class: "ghost", text: "Copia" });
    copia.addEventListener("click", async () => {
      try {
        const esitoCopia = await copiaTesto(testo || "");
        if (!esitoCopia.ok) throw new Error("il browser non ha concesso gli appunti: seleziona il testo e premi Ctrl+C");
        esito.className = "msg show ok";
        esito.textContent = "copiato: incollalo come primo messaggio di una chat nuova.";
      } catch (error) {
        esito.className = "msg show err";
        esito.textContent = `non copiato (${error.message}): seleziona il testo e copialo a mano.`;
      }
    });
    azioni.append(copia, esito);
  }
  if (opzioni.file) {
    azioni.append(linkSalvaFile(testo, opzioni.file));
  }
  if (!dialog.open) dialog.showModal();
  // Se la copia non è riuscita, il ripiego utile è il testo SELEZIONATO: un Ctrl+C e basta. Il
  // selettore non prende i pulsanti, solo il corpo del testo.
  // Sempre, quando il dialogo è aperto per copiare: il testo è già selezionato, e un Ctrl+C basta
  // anche se la Clipboard API ha rifiutato (fuoco, contesto non sicuro, attivazione scaduta).
  if (opzioni.seleziona || opzioni.copia) {
    const corpo = $("#report-body");
    const selezione = window.getSelection();
    if (corpo && selezione) {
      const intervallo = document.createRange();
      intervallo.selectNodeContents(corpo);
      selezione.removeAllRanges();
      selezione.addRange(intervallo);
    }
  }
}

/* «Salva come file»: il prompt come .md. Sta OVUNQUE si apra un prompt — nel dialogo e nel box che
   si apre sulla riga — perche' chi cerca il pulsante non deve sapere quale dei due ha aperto. */
function linkSalvaFile(testo, nome) {
  const indirizzo = URL.createObjectURL(
    new Blob([testo || ""], { type: "text/plain;charset=utf-8" })
  );
  return h("a", { class: "ghost actfile", href: indirizzo, download: nome, text: "Salva come file" });
}

/* Quante unita' ferma una fase: e' la LEVA, ed e' il criterio con cui si ordina la coda. */
/* L'ultimo prompt consegnato per quella fase, se la pagina se l'e' segnato. */
function consegnaDiFase(code) {
  const posta = (snapshot && snapshot.inbox && snapshot.inbox.items) || [];
  return posta
    .filter((voce) => voce.kind === "prompt-consegnato" && voce.phase === code)
    .sort((a, b) => String(b.when).localeCompare(String(a.when)))[0];
}

/* «L'ho mandato e nessuno l'ha dichiarato»: e' diverso da «non l'ho ancora mandato», e il registro
   da solo non li distingue. Questa riga li distingue. */
function rigaConsegna(code, haAtto = false) {
  const traccia = consegnaDiFase(code);
  if (!traccia) return null;
  const inCorso = ((snapshot && snapshot.claims) || []).some((voce) => voce.task_id === code);
  // Se un atto è già su disco, «nessuna presa dichiarata» non è più una notizia: il lavoro è stato
  // fatto (magari è stato respinto, ma è un'altra riga a dirlo).
  if (!inCorso && haAtto) return null;
  const quando = String(traccia.when || "").slice(11, 16);
  return h("div", { class: "actmeta" }, [
    h("b", { class: "warnnote", text: inCorso ? "prompt consegnato, presa dichiarata" : "prompt consegnato, NESSUNA presa dichiarata" }),
    document.createTextNode(
      inCorso
        ? ` — alle ${quando}.`
        : ` — alle ${quando}: chi l'ha ricevuto non ha depositato la presa, quindi il registro lo vede libero. Guarda quella chat, non rifare il lavoro qui.`
    ),
  ]);
}

function leva(fase) {
  const unita = ((snapshot && snapshot.blocks) || [])
    .flatMap((blocco) => blocco.units)
    .find((voce) => voce.id === fase || (voce.phases || []).some((p) => p.id === fase));
  return (unita && unita.blocked) || 0;
}

/* Il campo che manca quando la pagina non ha niente da chiedere: far partire una fase. Attivare
   scrive l'ordine e riserva la fase; non avvia nessun agente, e la pagina non lo finge. */
function renderActivation(data) {
  const box = $("#activation");
  const count = $("#activation-count");
  if (!box || !count) return;
  const obblighi = data.obligations || [];
  const obblighiGate = obblighi.filter((voce) => voce.gate).length;
  const debiti = data.independence_debts || [];
  const dovuti = data.owed || [];
  // LA SORGENTE E' IL PERCORSO, non le dichiarazioni dei report: quelle nominano anche fasi vecchie o
  // di unità mai iniziate (49 «mandabili» su un progetto, fra cui la R di un'unità ferma alla A).
  // Una riga per unità aperta, nell'ordine del percorso critico.
  const percorso = data.percorso || [];
  // Una fase RISERVATA non è «pronta» (l'ordine è già depositato: l'attivazione la rifiuterebbe) e non
  // è «in corso» (nessuno l'ha presa): vive nel gruppo delle riservate, con «Copia il prompt».
  const pronti = percorso.filter(
    (voce) =>
      !(voce.attesa || []).length && !voce.live && !voce.riservata && !voce.consegnata
  );
  // CONSEGNATE, DA ACCETTARE: l'atto esiste (verdetto positivo) e il registro dice ancora `pending`,
  // perché l'accettazione dell'handoff è un atto a sé. Senza questo gruppo la pagina rimandava la
  // stessa fase — «Attiva e copia il prompt» su un lavoro già consegnato — che è il ciclo peggiore.
  const daAccettare = percorso.filter((voce) => voce.consegnata && !voce.live && !voce.riservata);
  const attese = percorso.filter((voce) => (voce.attesa || []).length && !voce.live);
  const inCorso = percorso.filter((voce) => voce.live);
  const riservate = (data.activated || []).filter((voce) =>
    ["pre_registered", "ready"].includes(voce.status)
  );
  count.textContent = [
    pronti.length ? `${pronti.length} da mandare` : "niente da mandare",
    daAccettare.length ? `${daAccettare.length} da accettare` : null,
    inCorso.length ? `${inCorso.length} in corso` : null,
    riservate.length ? `${riservate.length} riservate` : null,
    attese.length ? `${attese.length} in attesa` : null,
    obblighi.length
      ? `${obblighi.length} obblighi aperti${obblighiGate ? ` (${obblighiGate} di gate)` : ""}`
      : null,
    debiti.length
      ? `${debiti.length} ${debiti.length === 1 ? "ratifica mancante" : "ratifiche mancanti"}`
      : null,
    dovuti.length ? `${dovuti.length} direzioni da leggere` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const suggerimento = $("#activation-hint");
  if (suggerimento) {
    suggerimento.replaceChildren(
      document.createTextNode(
        pronti.length
          ? "Il percorso è obbligato: una unità alla volta, e si parte solo con i prerequisiti accettati. Una riga, un'azione — premi e incolla il prompt in una chat."
          : obblighi.length || debiti.length
            ? "Non ci sono fasi da mandare, ma restano obblighi aperti e ratifiche mancanti. Parti dalle rifiniture marcate GATE."
            : dovuti.length
              ? "Non ci sono fasi da mandare, ma restano direzioni dei report da leggere: non eseguirle in serie, solo quelle con «Prompt» sono da rilanciare."
              : "Niente da mandare adesso: il lavoro è in mano a qualcuno, oppure aspetta che un'altra unità sia accettata (vedi «in attesa»)."
      )
    );
  }
  const parti = [];
  if (pronti.length) parti.push(h("div", { class: "actbox" }, pronti.map(codaRow)));
  if (daAccettare.length) {
    parti.push(
      h("div", { class: "actbox" }, [
        h("p", { class: "actgroup accent" }, [
          h("b", { text: "Consegnate: manca l'accettazione dell'handoff" }),
          h("span", { class: "actcount", text: String(daAccettare.length) }),
        ]),
        ...daAccettare.map((voce) => {
          const riga = h("div", { class: "actrow" });
          const testo = h("div", { class: "acttext" });
          testo.append(h("code", { class: "actcode", text: voce.phase }));
          testo.append(
            h("div", {
              class: "actmeta",
              text: `${voce.verdetto} · ${voce.report}. Il lavoro è fatto: il registro dice ancora «${voce.status}» perché manca l'atto di accettazione del coordinamento.`,
            })
          );
          const bloccanti = Number(voce.bloccanti || 0);
          if (bloccanti) {
            const chi = (voce.bloccanti_chi || []).filter(Boolean).join(", ");
            const chiBreve = chi.length > 70 ? `${chi.slice(0, 70)}…` : chi;
            const prossima = (voce.apre || [])[0];
            const analisi = String(voce.phase || "").toUpperCase().endsWith("A");
            testo.append(
              h("div", { class: "actmeta" }, [
                h("b", {
                  class: "warnnote",
                  text: `${bloccanti} finding bloccanti aperti`,
                }),
                document.createTextNode(
                  `${chiBreve ? ` (owner: ${chiBreve})` : ""} — leggili in «Esiti». ` +
                    (analisi
                      ? `L'analisi non si rifà: i bloccanti sono il suo output e passano a ${
                          prossima || "chi esegue"
                        }.`
                      : `Non spariscono con l'accettazione: passano a ${prossima || "chi esegue"}.`)
                ),
              ])
            );
          }
          riga.append(testo);
          const message = h("span", { class: "msg", role: "status", "aria-live": "polite" });
          // «Rifai» non è un'azione normale e i finding bloccanti NON sono un motivo per rifare:
          // sono l'output dell'atto, e passano alla fase successiva. Il pulsante esiste solo per il
          // caso in cui il cancello rifiuta l'accettazione (revisione mossa, puntatore indietro):
          // in quel caso viene scoperto, perché l'atto va ripreso sui byte vivi.
          const rifai = owedPromptButton(voce.phase, "Rifai (prompt)");
          rifai.hidden = true;
          riga.append(
            h("div", { class: "actactions" }, [
              bottoneEsiti(voce.phase),
              rifai,
              acceptButton(voce.phase, message, () => {
                rifai.hidden = false;
              }),
            ]),
            message
          );
          return riga;
        }),
      ])
    );
  }
  if (inCorso.length) {
    parti.push(
      h("div", { class: "actbox" }, [
        h("p", { class: "actgroup warn" }, [
          h("b", { text: "In corso: aspetta la loro consegna" }),
          h("span", { class: "actcount", text: String(inCorso.length) }),
        ]),
        ...inCorso.map((voce) =>
          h("div", { class: "actrow waiting" }, [
            h("div", { class: "acttext" }, [
              h("code", { class: "actcode", text: voce.phase }),
              h("div", {
                class: "actmeta",
                text: `${voce.status} · presa da ${voce.owner || "—"}. Quando consegna, la riga dopo è la sua.`,
              }),
            ]),
          ])
        ),
      ])
    );
  }
  if (riservate.length) {
    parti.push(
      h("div", { class: "actbox" }, [
        h("p", { class: "actgroup warn" }, [
          h("b", { text: "Riservate: nessuno le sta facendo" }),
          h("span", { class: "actcount", text: String(riservate.length) }),
        ]),
        ...riservate.map(riservataRow),
      ])
    );
  }
  if (attese.length) {
    parti.push(
      h("div", { class: "actbox" }, [
        h("p", { class: "actgroup" }, [
          h("b", { text: "In attesa: il percorso non è ancora arrivato lì" }),
          h("span", { class: "actcount", text: String(attese.length) }),
        ]),
        ...attese.map((voce) =>
          h("div", { class: "actrow waiting" }, [
            h("div", { class: "acttext" }, [
              h("code", { class: "actcode", text: voce.phase }),
              h("div", { class: "actmeta", text: `aspetta ${(voce.attesa || []).join(", ")}` }),
            ]),
          ])
        ),
      ])
    );
  }
  if (obblighi.length) parti.unshift(obligationsGroup(obblighi));
  // I timbri diversi si RACCONDANO qui, con un pulsante solo (legge del project-tool).
  const timbri = data.pins || [];
  if (timbri.length) parti.unshift(pinsGroup(timbri));
  if (debiti.length) parti.unshift(debtsGroup(debiti));
  if (dovuti.length) parti.push(owedGroup(dovuti));
  if (!parti.length) {
    parti.push(
      h("p", { class: "empty" }, [
        h("b", { text: "Tutto chiuso. " }),
        document.createTextNode("Nessuna unità aperta: il progetto è alla fine del percorso."),
      ])
    );
  }
  box.replaceChildren(...parti);
}

/* Una riga della coda: il codice, l'eventuale traccia del prompt consegnato, UN pulsante. La
   spiegazione («perche' lo dice X», la misura delle respinte) sta chiusa in un `details`. */
function codaRow(voce) {
  const riga = h("div", { class: "actrow" });
  const testo = h("div", { class: "acttext" });
  testo.append(h("code", { class: "actcode", text: voce.code }));
  const titolo = ((voce.fase || {}).title || "").trim().replace(/^(Accettare|Implementare|Verificare|Analizzare):\s*/, "");
  if (titolo) testo.append(document.createTextNode(` ${titolo}`));
  const traccia = rigaConsegna(voce.code, Boolean(voce.report));
  if (traccia) testo.append(traccia);
  // LA STESSA UNITA' CON UN'ALTRA FASE IN CORSO. Non si vieta (il tester puo' derivare i casi dal
  // design mentre l'esecuzione lavora) ma si dice: misurare adesso significa misurare byte che si
  // muovono — ed e' la classe di difetto che ha bruciato undici atti su `UPL04ZR`.
  const unita = (voce.code.match(/^[A-Z]+[0-9]+/) || [""])[0];
  const sorelle = ((snapshot && snapshot.claims) || [])
    .filter((altra) => altra.task_id !== voce.code && String(altra.task_id).startsWith(unita))
    .map((altra) => altra.task_id);
  if (sorelle.length) {
    // CHI MISURA: la verifica indipendente (`T`). La `R` non riesegue niente, giudica; la `E` scrive;
    // la `A` progetta. L'avviso quindi non può dire «se misuri» a tutti: parla del gesto che QUELLA
    // fase fa davvero.
    const chi = sorelle.join(", ");
    const suffisso = (voce.code.match(/([A-Z])$/) || [])[1] || "";
    const gesto = {
      T: `Se fai girare i casi adesso, misuri byte che si stanno muovendo: derivali dal design e aspetta la consegna di ${chi}.`,
      R: `Se giudichi adesso, giudichi byte che si stanno muovendo: aspetta la consegna di ${chi}, oppure accetta dichiarando il limite.`,
      E: `Attenzione: nella stessa unità è al lavoro ${chi}. Due mani sugli stessi file è il difetto più caro: leggi i path dichiarati prima del primo byte.`,
      A: `Nella stessa unità è al lavoro ${chi}: puoi procedere, ma dichiara il perimetro sapendo che quei byte si muovono.`,
    }[suffisso] || `Nella stessa unità c'è ${chi} in corso.`;
    testo.append(
      h("div", { class: "actmeta" }, [
        h("b", { class: "warnnote", text: "unità già in corso: " }),
        document.createTextNode(gesto),
      ])
    );
  }
  const dentro = [];
  if (voce.perche) {
    dentro.push(
      h("summary", {
        text: `perché: lo dice ${voce.da}${voce.quando ? `, ${String(voce.quando).slice(0, 16).replace("T", " ")}` : ""}`,
      }),
      h("pre", { class: "coda-perche", text: voce.perche })
    );
  }
  if (voce.fase && (voce.fase.misura || {}).tentativi > 1) {
    dentro.push(h("div", { class: "actmeta", text: reworkLine(voce.fase.misura) }));
  }
  if (dentro.length) testo.append(h("details", { class: "coda-dettaglio" }, dentro));
  riga.append(testo);

  const message = h("span", { class: "msg", role: "status", "aria-live": "polite" });
  const azioni = h("div", { class: "actactions" });
  // Il pulsante giusto dipende da cosa la fase è: attivabile (nessun ordine depositato) → si attiva
  // e si copia il prompt; già accettata e con un atto dovuto → si copia e basta; accettazione → si può
  // anche firmare.
  const attivabile = ((snapshot && snapshot.activatable) || []).some((voce2) => voce2.phase === voce.code);
  const fasi = (consoleConfig && consoleConfig.phases) || [];
  const accettazione = fasi.length
    ? String(voce.code).toUpperCase().endsWith(String(fasi[fasi.length - 1]).toUpperCase())
    : false;
  if ((voce.busy || []).length) {
    // Le fasi della stessa unità sono sequenziali: qui non c'è niente da mandare, si aspetta.
    testo.append(
      h("div", { class: "actmeta" }, [
        h("b", { class: "warnnote", text: "in attesa: " }),
        document.createTextNode(
          `la sua unità ha ${voce.busy.join(", ")} in corso. Le fasi della stessa unità sono sequenziali: ognuna misura l'output della precedente.`
        ),
      ])
    );
    riga.append(azioni);
    return riga;
  }
  if (voce.rifai) {
    // La verifica è rossa e il report dice dove tornare: rilanciare la stessa fase sugli stessi
    // byte rifarebbe la stessa misura. Il pulsante è il prompt della fase da riprendere.
    testo.append(
      h("div", { class: "actmeta" }, [
        h("b", { class: "warnnote", text: "da rifare a monte: " }),
        document.createTextNode(
          `${voce.code} ha respinto (${voce.verdetto})${
            Number(voce.bloccanti || 0) ? ` con ${voce.bloccanti} finding bloccanti` : ""
          } e il report dice di riprendere ${voce.rifai}. ` +
            `Rilanciare ${voce.code} sugli stessi byte rifarebbe la stessa misura.`
        ),
      ])
    );
    azioni.append(owedPromptButton(voce.rifai));
    riga.append(azioni, message);
    return riga;
  }
  if (voce.fase && (voce.fase.misura || {}).solo_firma) {
    azioni.append(acceptButton(voce.code, message));
  } else if (attivabile) {
    azioni.append(attivaEConsegna(voce.code, message));
  } else {
    // La fase NON è attivabile: quasi sempre perché è GIÀ ACCETTATA, e l'atto dovuto è un tentativo
    // NUOVO su di lei (il copy da rientrare, la verifica da rifare). Attivarla non si può e non
    // serve: si copia il prompt e lo si dà a una corsia. Era l'errore che ha prodotto «fase non
    // attivabile o inesistente: NAV03E» su un clic perfettamente legittimo.
    azioni.append(copiaPromptButton(voce.code, message));
  }
  // La R non ha ancora un report suo: l'evidenza e' quella della fase che la precede.
  if (accettazione && voce.esiti_di) {
    const suffisso = voce.unit ? String(voce.esiti_di).slice(String(voce.unit).length) : "";
    azioni.append(bottoneEsiti(voce.esiti_di, `Esiti di ${suffisso || voce.esiti_di}`));
  }
  if (accettazione && !(voce.busy || []).length) azioni.append(acceptButton(voce.code, message));
  if (voce.fase) azioni.append(attivaButtonPlain(voce.code, message));
  riga.append(azioni, message);
  return riga;
}

function riservataRow(voce) {
  const riga = h("div", { class: "actrow waiting" });
  const testo = h("div", { class: "acttext" });
  testo.append(h("code", { class: "actcode", text: voce.phase }));
  testo.append(
    h("div", {
      class: "actmeta",
      text: `RISERVATA: l'ordine è depositato (${voce.order || "—"}) e nessuno l'ha ancora presa, dalle ${String(
        voce.since || ""
      )
        .slice(11, 16)
        .replace("T", " ")}.`,
    })
  );
  // LA SEQUENZA, scritta per esteso. «Rilascia» sembrava il passo successivo a «Copia il prompt» e non
  // lo è: è il contrario, l'annullamento. I passi sono due, e il secondo non è tuo.
  testo.append(
    h("div", {
      class: "actmeta",
      text: "1) copia il prompt e dallo a una corsia → 2) la corsia dichiara la presa e questa riga passa in «in corso». Qui non c'è altro da fare.",
    })
  );
  riga.append(testo);
  const message = h("span", { class: "msg", role: "status", "aria-live": "polite" });
  riga.append(
    h("div", { class: "actactions" }, [
      promptCopiaButton(voce.phase),
      // «Annulla la riserva», non «Rilascia»: la fase torna libera e l'ordine resta sul disco come
      // storia. Non serve per consegnare il prompt — serve solo se decidi che nessuno la farà.
      h("button", {
        type: "button",
        class: "actbtn release",
        text: "Annulla la riserva",
        title:
          "la fase torna libera e la si può riattivare; l'ordine resta sul disco. Non è un passo della consegna: è l'annullamento",
        onclick: async () => {
          try {
            const risposta = await fetch("/api/activate", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ target: voce.phase, action: "release" }),
            });
            const payload = await risposta.json();
            if (!risposta.ok) throw new Error(payload.error || `errore ${risposta.status}`);
            message.className = "msg show ok";
            message.textContent = "riserva annullata: la fase è di nuovo libera.";
            setTimeout(load, 1500);
          } catch (error) {
            message.className = "msg show err";
            message.textContent = `non fatto: ${error.message}`;
          }
        },
      }),
    ]),
    message
  );
  return riga;
}

function reworkLine(misura) {
  const primo = (misura.ricorrenti || [])[0];
  if (misura.solo_firma) return `respinta ${misura.respinte} volte \u00b7 l'ostacolo che torna è la firma, non il prodotto`;
  if (primo) return `respinta ${misura.respinte} volte \u00b7 ostacolo in ${primo.volte} su ${misura.tentativi}: ${primo.id}`;
  return `respinta ${misura.respinte} volte \u00b7 ogni atto nomina punti nuovi`;
}

/* UN PULSANTE SOLO: attiva (ordine + riserva) e poi COPIA il prompt, aprendolo come ripiego. */
/* Il prompt di una fase che NON si attiva — perché è già accettata e l'atto dovuto è un tentativo
   nuovo. Copia, apre, e lascia la traccia che l'hai consegnato. */
function copiaPromptButton(code, message) {
  const bottone = h("button", { type: "button", class: "actbtn", text: "Copia il prompt" });
  bottone.addEventListener("click", async () => {
    bottone.disabled = true;
    message.className = "msg show pending";
    message.textContent = "compongo il prompt…";
    try {
      const testo = await chiediPrompt(code);
      annotaPromptConsegnato(code);
      const copia = await copiaTesto(testo.text || "");
      const copiato = copia.ok;
      message.className = copiato ? "msg show ok" : "msg show pending";
      message.textContent = copiato
        ? `prompt copiato (${(testo.text || "").length} caratteri): dallo a una corsia — la fase è già accettata, quindi è un tentativo NUOVO, non una riattivazione.`
        : "la copia non è riuscita (il browser vuole la finestra a fuoco): il prompt è qui, copialo a mano dal riquadro.";
      // Il prompt si apre SEMPRE: la copia è una comodità, non la consegna.
      apriTesto(`${code} — il prompt`, testo.text, {
        copia: true,
        file: `prompt-${code}.md`,
      });
    } catch (error) {
      message.className = "msg show err";
      message.textContent = `non copiato: ${error.message}`;
      bottone.disabled = false;
    }
  });
  return bottone;
}

function attivaEConsegna(phase, message) {
  const bottone = h("button", { type: "button", class: "actbtn", text: "Attiva e copia il prompt" });
  bottone.addEventListener("click", async () => {
    bottone.disabled = true;
    message.className = "msg show pending";
    message.textContent = "deposito l'ordine\u2026";
    try {
      const risposta = await fetch("/api/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: phase, action: "activate" }),
      });
      const payload = await risposta.json();
      if (!risposta.ok) throw new Error(payload.error || `errore ${risposta.status}`);
      const testo = await chiediPrompt(phase);
      const copia = await copiaTesto(testo.text || "");
      annotaPromptConsegnato(phase);
      message.className = "msg show ok";
      message.textContent = copia.ok
        ? `fatto: ordine in ${payload.order}, fase riservata, prompt COPIATO (${(testo.text || "").length} caratteri). Incollalo in una chat.`
        : `ordine in ${payload.order} e fase riservata, ma il prompt NON è stato copiato: è qui sotto, selezionalo e premi Ctrl+C.`;
      apriTesto(`${phase} \u2014 il prompt (già copiato)`, testo.text, {
        copia: true,
        file: `prompt-${phase}.md`,
      });
      setTimeout(load, 1500);
    } catch (error) {
      message.className = "msg show err";
      message.textContent = `non fatto: ${error.message}`;
      bottone.disabled = false;
    }
  });
  return bottone;
}

function attivaButtonPlain(phase, message) {
  return h("button", {
    type: "button",
    class: "actbtn release",
    text: "Solo l'ordine",
    title: "deposita l'ordine e riserva la fase, senza copiare il prompt",
    onclick: async () => {
      try {
        const risposta = await fetch("/api/activate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: phase, action: "activate" }),
        });
        const payload = await risposta.json();
        if (!risposta.ok) throw new Error(payload.error || `errore ${risposta.status}`);
        message.className = "msg show ok";
        message.textContent = `ordine in ${payload.order}, fase riservata.`;
        setTimeout(load, 1500);
      } catch (error) {
        message.className = "msg show err";
        message.textContent = `non fatto: ${error.message}`;
      }
    },
  });
}

/* LA PAGINA TESTIMONE: le dichiarazioni di chi ha consegnato, e chi non le ha lasciate. E' un
   corpus (202 voci sul progetto di origine), quindi ha filtro e ricerca, il testo CHIUSO, e le
   lacune col campo per scriverle. */

/* LA POSTA IN ARRIVO: i messaggi depositati interi, e il modulo per depositarne uno. E' l'unica
   parte della pagina che non legge i registri: legge una cartella di file di testo. Per questo
   nulla di quello che si scrive qui puo' rompere lo stato vivo del progetto, ed e' il motivo per
   cui un messaggio che arriva da una chat ha un posto dove stare. */
function renderInbox(data) {
  const box = $("#inbox");
  const count = $("#inbox-count");
  if (!box || !count) return;
  const posta = data || { items: [], non_lavorate: 0, cartella: "inbox" };
  const aperte = (posta.items || []).filter((voce) => voce.open);
  const lavorate = (posta.items || []).filter((voce) => !voce.open);
  count.textContent = posta.items.length
    ? `${aperte.length ? `${aperte.length} da lavorare` : "niente da lavorare"} · ${lavorate.length} lavorate`
    : "";
  collegaModuloPosta();
  if (!posta.items.length) {
    box.replaceChildren(
      h("p", { class: "empty" }, [
        h("b", { text: "Posta vuota. " }),
        document.createTextNode(
          `Il deposito non è un registro: crea un file di testo in ${posta.cartella}/, uno per messaggio. Niente da leggere, niente da formattare.`
        ),
      ])
    );
    return;
  }
  const parti = [];
  if (aperte.length) parti.push(postaGroup(`Da lavorare (${aperte.length})`, "warn", aperte));
  if (lavorate.length) {
    parti.push(
      h("details", { class: "actbox" }, [
        h("summary", { class: "acthead" }, [
          h("b", { text: `Già lavorate (${lavorate.length})` }),
          document.createTextNode(" — il report di quella fase è arrivato dopo la ricevuta."),
        ]),
        ...lavorate.map(postaRow),
      ])
    );
  }
  box.replaceChildren(...parti);
}

function postaGroup(titolo, tono, voci) {
  return h("div", { class: "actbox" }, [
    h("p", { class: `actgroup ${tono}` }, [h("b", { text: titolo })]),
    ...voci.map(postaRow),
  ]);
}

/* QUELLO CHE IL REGISTRO DICE CHE È DOVUTO. Ogni riga è una dichiarazione di chi ha finito: «il
   prossimo passo è il rientro di copy in NAV03E attempt 4», «la palla è di UPL04ZT attempt 2».
   Accanto, il pulsante che compone il prompt di QUELLA fase (anche se è già accettata: l'atto
   dovuto è un tentativo nuovo). È la risposta alla domanda «cosa mando adesso?». */
/* GLI OBBLIGHI NOMINATI DEL REGISTRO. Non sono unità: restano aperti anche quando tutte le unità
   sono accettate, e senza questa sezione la pagina poteva dire «Tutto chiuso» mentre il registro
   aveva nove righe `OBBLIGO` con la scadenza già decorsa. La riga mostra la scadenza e il
   proprietario; «Leggi» apre il testo intero, senza riscriverlo. */
/* LE RATIFICHE INDIPENDENTI MANCANTI. Un debito D008 non è un obbligo `execution_attempts` e
   non è una fase aperta: la fase è `accepted`. Va mostrato come azione, altrimenti l'unica
   traccia è il testo `next` di un report e la pagina offre i prompt delle fasi già accettate. */
function debtsGroup(voci) {
  return h("div", { class: "actbox" }, [
    h("p", { class: "actgroup warn" }, [
      h("b", { text: "Ratifiche indipendenti mancanti" }),
      h("span", { class: "actcount", text: String(voci.length) }),
    ]),
    ...voci.map(debtRow),
  ]);
}

function debtRow(voce) {
  const riga = h("div", { class: "actrow" });
  const testo = h("div", { class: "acttext" });
  testo.append(h("code", { class: "actcode", text: voce.unit }));
  testo.append(document.createTextNode(" — ratifica mancante"));
  testo.append(
    h("div", {
      class: "actmeta",
      text: [
        voce.tasks.join(", "),
        voce.status,
        voce.required_before ? `prima di ${voce.required_before}` : null,
        voce.owner,
      ]
        .filter(Boolean)
        .join(" · "),
    })
  );
  if (voce.what) testo.append(h("div", { class: "actmeta", text: voce.what }));
  const istruzioni = [
    `Ratifica indipendente di ${voce.unit}.`,
    `Fasi: ${voce.tasks.join(", ")}.`,
    `Pubblica un atto di ratifica da una firma che non ha eseguito quei byte; giudica i report e registra il campo ratification su ${voce.tasks.join(" e ")}.`,
    "Per D020 basta che la firma non abbia eseguito quei byte: non serve un canonico diverso da /root.",
    "Poi esegui independence_audit.py e verifica units_with_independence_debt=0.",
    "Non rieseguire le batterie delle fasi.",
  ].join("\n");
  const azioni = h("div", { class: "actactions" }, [
    h("button", {
      type: "button",
      class: "actbtn",
      text: "Prompt istruzioni",
      title: "l'atto di ratifica che manca, pronto da copiare",
      onclick: () =>
        apriTesto(`${voce.unit} — ratifica mancante`, istruzioni, {
          copia: true,
          file: `ratifica-${voce.unit}.md`,
        }),
    }),
  ]);
  riga.append(testo, azioni);
  return riga;
}

function obligationsGroup(voci) {
  const ordinate = [...voci].sort(
    (prima, dopo) => Number(Boolean(dopo.gate)) - Number(Boolean(prima.gate))
  );
  const prese = voci.filter((voce) => voce.taken).length;
  const consegnati = voci.filter((voce) => voce.dispatched).length;
  const finiti = voci.filter((voce) => voce.report_closed).length;
  return h("div", { class: "actbox", id: "rifiniture" }, [
    h("p", { class: "actgroup bad" }, [
      h("b", { text: "Rifiniture finali" }),
      h("span", {
        class: "actcount",
        text: `${voci.length} · ${prese}/${voci.length} in carico · ${consegnati}/${voci.length} consegnati${
          finiti ? ` · ${finiti}/${voci.length} finiti da registrare` : ""
        }`,
      }),
    ]),
    h("button", {
      type: "button",
      class: "ghost",
      text: "Nuova rifinitura",
      onclick: () => apriRifinitura(null, { add: true }),
    }),
    h("button", {
      type: "button",
      class: "ghost",
      text: "Sincronizza dai report",
      onclick: async () => {
        try {
          const response = await fetch("/api/refinement/sync", { method: "POST" });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
          $("#status-line").textContent = `Sincronizzate ${payload.updated.length} voci dai report.`;
          await load();
        } catch (error) {
          $("#status-line").textContent = `Sincronizzazione non riuscita: ${error.message}`;
        }
      },
    }),
    h("label", { class: "strict-toggle" }, [
      h("input", {
        type: "checkbox",
        checked: strictMode,
        onchange: (event) => {
          strictMode = event.target.checked;
          if (snapshot) render(snapshot);
        },
      }),
      document.createTextNode(" Modalità rigorosa"),
    ]),
    h("details", { class: "actdetails" }, [
      h("summary", { text: "Come funziona il ciclo" }),
      h("p", {
        class: "actmeta",
        text:
          "A analisi · E esecuzione · T verifica indipendente · R accettazione. " +
          "Verde = fatto, giallo = parziale, blu = in corso, grigio = mancante.",
      }),
    ]),
    ...ordinate.map(obligationRow),
  ]);
}

function pinsGroup(timbri) {
  const daFare = timbri.filter((voce) => voce.status === "da_raccordare");
  const box = h("div", { class: "actbox", id: "timbri" }, [
    h("p", { class: "actgroup bad" }, [
      h("b", { text: "Timbri diversi" }),
      h("span", { class: "actcount", text: `${daFare.length} da raccordare · ${timbri.length} dichiarati` }),
    ]),
    h("p", {
      class: "actmeta",
      text:
        "Sono le impronte che una prova dichiara di misurare e che oggi descrivono un'altra revisione. " +
        "Il pulsante le riallinea tutte: una copia per file, nessuna domanda.",
    }),
  ]);
  for (const voce of timbri) {
    box.append(
      h("div", { class: "actrow" }, [
        h("div", { class: "acttext" }, [
          h("code", { class: "actcode", text: voce.label }),
          document.createTextNode(` ${voce.file}`),
          h("div", {
            class: "actmeta",
            text: `${voce.declared.slice(0, 12)}… → ${voce.live.slice(0, 12)}… · ${voce.status}`,
          }),
        ]),
      ])
    );
  }
  const esito = h("span", { class: "msg", role: "status", "aria-live": "polite" });
  const avvia = h("button", {
    type: "button",
    id: "pins-raccorda",
    text: daFare.length ? `Raccorda tutti (${daFare.length})` : "Niente da raccordare",
    disabled: !daFare.length,
    onclick: async () => {
      avvia.disabled = true;
      esito.className = "msg show pending";
      esito.textContent = "raccordo…";
      try {
        const risposta = await fetch("/api/pins/reconcile", { method: "POST" });
        const payload = await risposta.json();
        if (!risposta.ok) throw new Error(payload.error || `errore ${risposta.status}`);
        const aperti = (payload.voci || []).filter(
          (voce) => voce.status !== "raccordato" && voce.status !== "gia_allineato"
        );
        esito.className = aperti.length ? "msg show err" : "msg show ok";
        esito.textContent = aperti.length
          ? `raccordati ${payload.raccordati}, restano ${aperti.length} da guardare: ${aperti
              .map((voce) => `${voce.label} (${voce.status})`)
              .join(", ")}`
          : `raccordati ${payload.raccordati} timbri.`;
        await load();
      } catch (error) {
        esito.className = "msg show err";
        esito.textContent = `non raccordati: ${error.message}`;
        avvia.disabled = false;
      }
    },
  });
  box.append(h("div", { class: "actactions" }, [avvia, esito]));
  return box;
}

function obligationRow(voce) {
  const riga = h("div", { class: "actrow" });
  const testo = h("div", { class: "acttext" });
  const rigorosa = Boolean(strictMode || voce.strict_required);
  const dettagli = h("details", { class: "actdetails", open: rigorosa });
  dettagli.append(h("summary", { text: "Dettagli tecnici" }));
  const corpoDettagli = h("div", { class: "actdetails-body" });
  dettagli.append(corpoDettagli);
  testo.append(h("code", { class: "actcode", text: voce.id }));
  testo.append(
    document.createTextNode(
      voce.required_before ? ` prima di ${voce.required_before}` : " senza scadenza di gate"
    )
  );
  testo.append(h("span", {
    class: `actbadge ${voce.gate ? "gate" : "normal"}`,
    text: voce.gate ? `BLOCCA ${voce.required_before}` : "NON BLOCCA",
  }));
  const ultimaPresa = voce.last_claim_task
    ? ` · ultima presa: ${voce.last_claim_by || "titolare non dichiarato"} · ${voce.last_claim_task}`
    : "";
  if (voce.report_closed) {
    corpoDettagli.append(h("div", {
      class: "actclaim done",
      text: `Finito: ${voce.report_verdict || "esito chiuso"}${
        voce.report_attempt
          ? ` (attempt ${voce.report_attempt}${voce.report_phase ? `, fase ${voce.report_phase}` : ""})`
          : ""
      }${voce.report_author ? ` · ${voce.report_author}` : ""} · chiusura da registrare${ultimaPresa}`,
    }));
  } else if (voce.taken) {
    corpoDettagli.append(h("div", {
      class: "actclaim taken",
      text: `Presa in carico: ${voce.taken_by || "titolare non dichiarato"}${
        voce.taken_at ? ` dal ${voce.taken_at}` : ""
      }${voce.claim_task ? ` · ${voce.claim_task}` : ""}`,
    }));
  } else if (voce.dispatched) {
    corpoDettagli.append(h("div", {
      class: "actclaim dispatched",
      text: `Prompt consegnato${voce.dispatched_at ? ` ${voce.dispatched_at.slice(0, 16).replace("T", " ")}` : ""} · in attesa di presa in carico${
        voce.report_verdict
          ? ` · ultimo atto: ${voce.report_author ? `${voce.report_author} · ` : ""}${voce.report_verdict}${
              voce.report_attempt
                ? ` (attempt ${voce.report_attempt}${voce.report_phase ? `, fase ${voce.report_phase}` : ""})`
                : ""
            }`
          : ""
      }${ultimaPresa}`,
    }));
  } else if (voce.report_verdict) {
    corpoDettagli.append(h("div", {
      class: "actclaim report",
      text: `Ultimo atto: ${voce.report_author ? `${voce.report_author} · ` : ""}${voce.report_verdict}${
        voce.report_attempt
          ? ` (attempt ${voce.report_attempt}${voce.report_phase ? `, fase ${voce.report_phase}` : ""})`
          : ""
      } · nessuna presa viva${ultimaPresa}`,
    }));
  } else {
    corpoDettagli.append(h("div", {
      class: "actclaim untaken",
      text: "Presa in carico: NO · prompt non consegnato",
    }));
  }
  const stages = voce.stages || {};
  const stageLabels = {
    A: "Analisi",
    E: "Esecuzione",
    T: "Verifica indipendente",
    R: "Accettazione",
    OWNERS: "Riparazione dei proprietari",
    A2: "Design A2",
  };
  const strip = h("div", { class: "actstages", "aria-label": "Fasi della rifinitura" });
  ["A", "E", "T", "R"].forEach((chiave) => {
    strip.append(h("span", {
      class: `stage ${stages[chiave] || "missing"}`,
      text: chiave,
      title: `${chiave} · ${stageLabels[chiave]}: ${stages[chiave] || "mancante"}`,
    }));
  });
  if (voce.stage_known === false) {
    strip.append(h("span", {
      class: "stage-next unknown",
      text: "Fase non determinata dal report",
    }));
  } else if (voce.next_stage) {
    strip.append(h("span", {
      class: "stage-next",
      text: `Prossimo: ${voce.next_stage} · ${stageLabels[voce.next_stage] || ""}`,
    }));
  }
  corpoDettagli.append(strip);
  if ((voce.owners || []).length) {
    corpoDettagli.append(h("div", {
      class: "actmeta",
      text: `Unità proprietaria: ${voce.owners.join(", ")}`,
    }));
  }
  if (voce.branch) {
    corpoDettagli.append(h("div", {
      class: "actmeta",
      text: `Ramo: ${voce.branch} · worktree: ${voce.worktree || "—"}`,
    }));
  }
  if (voce.git_branch) {
    corpoDettagli.append(h("div", {
      class: "actmeta",
      text: `Ramo vivo: ${voce.git_branch} · atteso: ${voce.branch || "—"}${
        voce.branch_ready ? "" : " · non ancora allineato"
      }`,
    }));
  }
  if ((voce.path_drift || []).length) {
    corpoDettagli.append(h("div", {
      class: "actclaim untaken",
      text: `File fuori perimetro: ${voce.path_drift.join(", ")}`,
    }));
  }
  if (voce.report_next) {
    corpoDettagli.append(
      h("div", { class: "actmeta" }, [
        h("b", { text: "Prossimo atto dichiarato: " }),
        document.createTextNode(voce.report_next),
      ])
    );
  }
  const tasksNext = voce.report_next_tasks || [];
  const baseNext = String(voce.next_report || "").split("/").slice(-2, -1)[0];
  const taskNext =
    tasksNext.find((task) => String(task.id) === baseNext) || tasksNext[0];
  if (taskNext && taskNext.action) {
    const azione = String(taskNext.action);
    corpoDettagli.append(
      h("div", { class: "actmeta" }, [
        h("b", { text: `Mandato ${taskNext.id}: ` }),
        document.createTextNode(azione.length > 320 ? `${azione.slice(0, 319)}…` : azione),
      ])
    );
  }
  if (voce.sync_warning) {
    corpoDettagli.append(h("div", { class: "actclaim untaken", text: voce.sync_warning }));
  }
  corpoDettagli.append(
    h("div", {
      class: "actmeta",
      text: [voce.status, voce.domain, voce.owner].filter(Boolean).join(" · "),
    })
  );
  const sintesi = String(voce.what || "").trim();
  if (sintesi) {
    corpoDettagli.append(
      h("div", { class: "actmeta" }, [
        // È il testo che spiega PERCHÉ l'obbligo esiste (spesso una decisione vecchia): senza
        // etichetta si legge come se fosse l'istruzione di adesso, e sembra contraddire il mandato.
        h("b", { text: "Perché esiste (storico): " }),
        document.createTextNode(sintesi.length > 240 ? `${sintesi.slice(0, 239)}…` : sintesi),
      ])
    );
  }
  const esito = h("span", { class: "msg", role: "status", "aria-live": "polite" });
  const testoObbligo = () =>
    [
      voce.latest_note
        ? `NOTA CORRENTE DEL REGISTRO\n${voce.latest_note}`
        : "",
      voce.what
        ? `TESTO ORIGINARIO (storico; può essere superato dalla nota corrente)\n${voce.what}`
        : "",
      voce.note ? `NOTA STORICA\n${voce.note}` : "",
      voce.origin ? `ORIGINE\n${voce.origin}` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  const promptObbligo = () =>
    (rigorosa
      ? voce.next_prompt || voce.vibe_prompt
      : voce.vibe_prompt || voce.next_prompt) ||
    [
      `Lavora sull'obbligo ${voce.id}.`,
      voce.required_before
        ? `Scadenza di gate: ${voce.required_before}.`
        : "Nessuna scadenza di gate.",
      voce.what ? `Cosa dice il registro: ${voce.what}` : "",
      voce.report_next ? `Prossimo atto dichiarato: ${voce.report_next}` : "",
      taskNext && taskNext.action
        ? `Mandato dichiarato per ${taskNext.id}: ${taskNext.action}`
        : "",
      "Leggi gli esiti citati e verifica se l'obbligo è ancora aperto.",
      "Se è chiuso, deposita l'atto di chiusura con l'evidenza esatta (file, attempt, comando, esito).",
      "Se è aperto, esegui la prossima azione e dichiara cosa hai misurato. Non inventare.",
    ]
      .filter(Boolean)
      .join("\n") + "\n";
  const copia = h("button", {
    type: "button",
    class: "actbtn",
    text: "Copia prompt",
    title: "copia un'istruzione mirata per chiudere o verificare questo obbligo",
  });
  copia.addEventListener("click", async () => {
    const testoPrompt = promptObbligo();
    const copiato = await copiaTesto(testoPrompt);
    esito.className = `msg show ${copiato.ok ? "ok" : "err"}`;
    esito.textContent = copiato.ok
      ? "Prompt copiato."
      : "Copia non riuscita: apri «Leggi» e seleziona il testo.";
    if (!copiato.ok) {
      apriTesto(`${voce.id} — prompt di chiusura`, testoPrompt, {
        copia: true,
        seleziona: true,
        file: `obbligo-${voce.id}.md`,
      });
    } else {
      await annotaPromptConsegnato(voce.id);
      await load();
    }
  });
  const pending = voce.pending_refinement;
  let accettaRif = null;
  let pendingTestOk = true;
  if (pending) {
    const etichetta = pending.label || pending.phase;
    const prossima = voce.next_stage || "la fase successiva";
    const testPending = pending.test || {};
    const testOk = Boolean(
      testPending.not_applicable ||
      (testPending.command &&
        testPending.exit !== undefined &&
        testPending.exit !== null &&
        testPending.exit !== "" &&
        testPending.duration)
    );
    pendingTestOk = testOk;
    accettaRif = h("button", {
      type: "button",
      class: "actbtn",
      text: `Accetta ${etichetta} e apri ${prossima}`,
      title: `segna ${etichetta} accettata e lascia aperta ${prossima}`,
    });
    accettaRif.disabled = !testOk;
    if (!testOk) accettaRif.title = "scheda test incompleta: accettazione bloccata";
    accettaRif.addEventListener("click", async () => {
      accettaRif.disabled = true;
      esito.className = "msg show pending";
      esito.textContent = `accetto ${etichetta}…`;
      try {
        const risposta = await fetch("/api/refinement/accept", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            obligation: pending.id,
            phase: pending.phase,
            attempt: pending.attempt,
            report: pending.report,
            verdict: pending.verdict,
            author: pending.author,
            next: pending.next,
            next_report: pending.next_report,
          }),
        });
        const payload = await risposta.json();
        if (!risposta.ok) throw new Error(payload.error || `errore ${risposta.status}`);
        esito.className = "msg show ok";
        esito.textContent = `${etichetta} accettata. Prossimo atto: ${prossima}.`;
        setTimeout(load, 1500);
      } catch (error) {
        esito.className = "msg show err";
        esito.textContent = `non accettata: ${error.message}`;
        accettaRif.disabled = false;
      }
    });
  }
  const primary = h("div", { class: "actprimary" });
  if ((voce.conflicts || []).length) {
    primary.append(h("p", {
      class: "actparallel",
      text: `In attesa: condivide file con ${voce.conflicts.join(", ")}.`,
    }));
  } else if ((voce.parallel_with || []).length) {
    primary.append(h("p", {
      class: "actparallel",
      text: `In parallelo con ${voce.parallel_with.join(", ")}; non toccare i loro file.`,
    }));
  }
  if (voce.strict_required) {
    const riskLabels = {
      data: "dati",
      shared_files: "file condivisi",
      security: "sicurezza",
      migrations: "migrazioni",
      release: "release",
      configuration: "configurazione",
      provenance: "provenienza",
      dichiarato: "dichiarato",
    };
    primary.append(
      h("span", { class: "actbadge gate", text: "RIGOROSA" }),
      h("p", {
        class: "actparallel",
        text: `Perché: ${(voce.risk_flags || [])
          .map((flag) => riskLabels[flag] || flag)
          .join(", ")}.`,
      })
    );
  }
  const testText =
    voce.test && (voce.test.command || voce.test.exit != null)
      ? `Test: ${voce.test.command || "—"} · RC=${voce.test.exit ?? "—"} · ${
          voce.test.duration || "—"
        }`
      : "";
  const errorText =
    String(voce.report_handoff || "").trim() ||
    (Array.isArray(voce.errors)
      ? voce.errors
          .map((errore) => errore.what || errore.text || errore.id || String(errore))
          .join(" · ")
      : "");
  const reportLink = voce.report_path
    ? h("a", {
        class: "actbtn release",
        href: `/file?path=${encodeURIComponent(voce.report_path)}`,
        target: "_blank",
        rel: "noopener",
        text: "Vedi report",
      })
    : null;
  if (voce.report_closed) {
    primary.append(h("b", { text: "Fatto" }), reportLink);
  } else if (pending && accettaRif) {
    primary.append(
      h("b", { text: `Da accettare: ${pending.label}` }),
      accettaRif,
      pendingTestOk
        ? null
        : h("p", { text: "Manca la scheda test: l'accettazione è bloccata." }),
      testText ? h("p", { text: testText }) : null,
      reportLink
    );
  } else if (voce.stop_required) {
    primary.append(
      h("b", { text: "Serve una decisione" }),
      h("p", { text: voce.stop_reason || "Troppi tentativi falliti." }),
      errorText ? h("p", { text: errorText }) : null,
      testText ? h("p", { text: testText }) : null,
      h("button", {
        type: "button",
        class: "actbtn",
        text: "Apri Gestisci",
        onclick: () => apriRifinitura(voce),
      }),
      reportLink
    );
  } else if (
    /needs_changes|fail|open/i.test(String(voce.report_verdict || "")) ||
    Object.values(voce.stages || {}).includes("partial")
  ) {
    primary.append(h("b", { text: "Errori" }));
    const dettaglio = String(errorText || voce.report_verdict || "").trim();
    if (dettaglio) {
      primary.append(h("p", {
        text: dettaglio.length > 420 ? `${dettaglio.slice(0, 419)}…` : dettaglio,
      }));
    }
    primary.append(
      testText ? h("p", { text: testText }) : null,
      h("button", {
        type: "button",
        class: "actbtn",
        text: `Riprendi da ${voce.next_stage || "E"}`,
        onclick: () => copia.click(),
      }),
      reportLink
    );
  } else {
    primary.append(
      h("b", { text: `Da fare: ${voce.next_stage || "?"}` }),
      h("button", {
        type: "button",
        class: "actbtn",
        text: rigorosa ? "Copia mandato" : "Copia prompt",
        onclick: () => copia.click(),
      })
    );
  }
  testo.prepend(primary);
  testo.append(dettagli);
  const azioni = h("div", { class: "actactions" }, [
    h("button", {
      type: "button",
      class: "actbtn",
      text: "Gestisci",
      title: "fase, stato, report, presa e prossimo atto",
      onclick: () =>
        apriRifinitura(voce, { add: voce.stage_source !== "refinements.yaml" }),
    }),
    h("button", {
      type: "button",
      class: "actbtn release",
      text: "Leggi",
      title: "l'obbligo intero, come sta nel registro",
      onclick: () =>
        apriTesto(
          `${voce.id} — obbligo aperto`,
          testoObbligo(),
          { copia: true, file: `obbligo-${voce.id}.md` }
        ),
    }),
    copia,
    h("a", {
      class: "actbtn",
      href: "/file?path=state.yaml",
      target: "_blank",
      rel: "noopener",
      text: "Registro",
    }),
    voce.report_path
      ? h("a", {
          class: "actbtn",
          href: `/file?path=${encodeURIComponent(voce.report_path)}`,
          target: "_blank",
          rel: "noopener",
          text: "Ultimo report",
        })
      : null,
    esito,
  ]);
  riga.append(testo, azioni);
  return riga;
}

function owedGroup(voci) {
  return h("div", { class: "actbox" }, [
    h("p", { class: "actgroup accent" }, [
      h("b", { text: "Direzioni lasciate dai report" }),
      h("span", { class: "actcount", text: String(voci.length) }),
    ]),
    h("p", {
      class: "actmeta",
      text:
        "Non sono ordini: solo le righe con un pulsante «Prompt» hanno una fase da rilanciare. " +
        "Le altre sono il testimone di chi ha finito e vanno lette, non eseguite in serie.",
    }),
    ...voci.map(owedRow),
  ]);
}

function owedRow(voce) {
  const riga = h("div", { class: "actrow" });
  const testo = h("div", { class: "acttext" });
  const codici = voce.codes || [];
  testo.append(h("code", { class: "actcode", text: voce.from_phase }));
  testo.append(
    document.createTextNode(" — direzione lasciata nel report, non un ordine")
  );
  testo.append(
    h("div", {
      class: "actmeta",
      text: [
        voce.from_status,
        String(voce.when || "").slice(0, 16).replace("T", " "),
        voce.from_open ? "unità aperta" : "unità chiusa",
        voce.source,
      ]
        .filter(Boolean)
        .join(" · "),
    })
  );
  // Il TESTO è la direzione vera. La riga sintetica «il prossimo atto è X» faceva sembrare
  // un ordine ciò che è solo una frase del report, e i codici citati potevano essere già
  // accettati. Qui si legge cosa ha scritto chi ha finito; i pulsanti arrivano dopo.
  const direzione = String(voce.text || "").trim();
  if (direzione) {
    testo.append(
      h("div", {
        class: "actmeta",
        text: direzione.length > 420 ? `${direzione.slice(0, 419)}…` : direzione,
      })
    );
  }
  const azionabili = codici.filter(
    (codice) => !codice.live && !codice.done && codice.status !== "accepted"
  );
  testo.append(
    h("div", {
      class: "actmeta",
      text: azionabili.length
        ? `Fasi da rilanciare: ${azionabili.map((codice) => codice.code).join(", ")}`
        : "Nessuna fase da rilanciare: questa riga è una direzione da leggere, non un prompt.",
    })
  );
  riga.append(testo);
  const azioni = h("div", { class: "actactions" });
  codici.forEach((codice) => {
    // NIENTE PULSANTE PER UNA FASE GIÀ ACCETTATA. Misurato dall'utente il 2026-10-19 su
    // END03R: la riga nominava END03T, QA06T e QA06R, tutte accepted, e la pagina offriva
    // tre «Prompt»; il lavoro vero era un atto di ratifica, non tre nuovi tentativi.
    const etichetta = codice.live
      ? "in corso"
      : codice.done
        ? "consegnata"
        : codice.status === "accepted"
          ? "accettata"
          : codice.status || "da verificare";
    azioni.append(
      h("span", {
        class: "actbtn release taken",
        text: `${codice.code}: ${etichetta}`,
      })
    );
  });
  azionabili.forEach((codice) => azioni.append(owedPromptButton(codice.code)));
  azioni.append(
    h("button", {
      type: "button",
      class: "actbtn release",
      text: "Leggi",
      title: "la dichiarazione intera, come l'ha scritta chi ha finito",
      onclick: () =>
        apriTesto(`${voce.from_phase} — cosa c'è da fare dopo`, voce.text, {
          copia: true,
          file: `dichiarazione-${voce.from_phase}.md`,
        }),
    })
  );
  riga.append(azioni);
  return riga;
}

/* Il prompt di una fase nominata: si apre nel dialogo (che ha Copia e Salva come file), perché la
   fase può essere già accettata e non avere nessuna riga nella coda. */
function owedPromptButton(code, etichetta) {
  return h("button", {
    type: "button",
    class: "actbtn",
    text: etichetta || `Prompt ${code}`,
    title: `il prompt da incollare per far partire o rifare ${code} sui byte vivi`,
    onclick: async () => {
      try {
        const payload = await chiediPrompt(code);
        annotaPromptConsegnato(code);
        apriTesto(`${code} — il prompt`, payload.text, { copia: true, file: `prompt-${code}.md` });
      } catch (error) {
        apriTesto(`${code} — il prompt`, `non disponibile: ${error.message}`);
      }
    },
  });
}

/* QUANDO CONSEGNI UN PROMPT, LA PAGINA SE LO SEGNA.

   Perche'. Il registro sa solo quello che gli agenti DICHIARANO: finche' chi riceve un prompt non
   deposita la presa, la fase risulta libera — e «non l'ho ancora mandato» e «l'ho mandato e nessuno
   l'ha dichiarato» diventano la stessa cosa in pagina. Misurato il 2026-10-16: l'utente aveva mandato
   `NAV03T` e la pagina non lo mostrava in corso (registro pulito, nessuna presa), mentre `TODO03T`
   lo mostrava. Qui si deposita una RICEVUTA (un file in `inbox/`, non una scrittura nei registri):
   cosi' la riga puo' dire «consegnato alle 14:52, nessuna presa dichiarata» — e tu sai che c'e' un
   agente da controllare, non un lavoro da rifare. */
function annotaPromptConsegnato(code, verbo = "copiato") {
  if (!code) return Promise.resolve();
  const adesso = new Date().toISOString().slice(11, 16);
  return fetch("/api/inbox", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      phase: code,
      sender: "utente",
      kind: "prompt-consegnato",
      text: `Prompt di ${code} ${verbo} dalla pagina alle ${adesso} e consegnato a una chat. Nessuna presa dichiarata nel registro finché chi l'ha ricevuto non la deposita.`,
    }),
  }).catch(() => {});
}

function postaRow(voce) {
  const riga = h("div", { class: `actrow${voce.open ? " waiting" : ""}` });
  const testo = h("div", { class: "acttext" });
  testo.append(h("code", { class: "actcode", text: voce.phase || "(senza fase)" }));
  testo.append(
    document.createTextNode(
      ` ${[
        voce.kind,
        voce.sender,
        String(voce.when || "").slice(0, 16).replace("T", " "),
        voce.open ? "da lavorare" : "lavorata",
      ]
        .filter(Boolean)
        .join(" · ")}`
    )
  );
  testo.append(
    h("div", {
      class: "actmeta",
      text: `${voce.file} · ${voce.chars} caratteri${
        voce.worked_by ? ` · lavorata da ${voce.worked_by}` : ""
      }`,
    })
  );
  riga.append(testo);
  const azioni = h("div", { class: "actactions" });
  azioni.append(
    h("button", {
      type: "button",
      class: "actbtn",
      text: "Leggi",
      title: "il messaggio, intero",
      onclick: () =>
        apriTesto(`${voce.phase || voce.ricevuta} — messaggio in posta`, voce.text, {
          copia: true,
          file: `posta-${voce.ricevuta}.md`,
        }),
    })
  );
  riga.append(azioni);
  return riga;
}

/* Il deposito: incolla, premi, non ci pensi più. Il messaggio non passa dai registri, quindi
   questa è l'unica azione della pagina che non può far male a niente. */
function collegaModuloPosta() {
  const bottone = $("#inbox-salva");
  if (!bottone || bottone.dataset.pronto) return;
  bottone.dataset.pronto = "1";
  const esito = $("#inbox-esito");
  const dire = (tono, testo) => {
    esito.className = `msg show ${tono}`;
    esito.textContent = testo;
  };
  bottone.addEventListener("click", async () => {
    const campo = $("#inbox-text");
    const testo = campo.value.trim();
    if (!testo) {
      dire("err", "incolla il messaggio: una ricevuta vuota è peggio di nessuna ricevuta.");
      return;
    }
    bottone.disabled = true;
    dire("pending", "deposito…");
    try {
      const response = await fetch("/api/inbox", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: testo,
          phase: $("#inbox-phase").value.trim(),
          sender: "utente",
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `errore ${response.status}`);
      campo.value = "";
      $("#inbox-phase").value = "";
      dire("ok", `depositato: ${payload.file} (${payload.caratteri} caratteri, intero).`);
      await load();
    } catch (error) {
      dire("err", `non depositato: ${error.message}`);
    } finally {
      bottone.disabled = false;
    }
  });
}

let filtroTestimone = "aperte";
let cercaTestimone = "";

function renderTestimone(data) {
  const box = $("#testimone");
  const count = $("#testimone-count");
  if (!box || !count) return;
  const dichiarazioni = (data.handoff && data.handoff.declarations) || [];
  const lacune = (data.handoff && data.handoff.gaps) || [];
  count.textContent = `${dichiarazioni.length} dichiarate · ${lacune.length} senza direzione`;
  if (filtroTestimone === "lacune") {
    const aperte = lacune.filter((voce) => voce.unit_open);
    box.replaceChildren(
      h("p", { class: "actgroup bad" }, [
        h("b", { text: `Consegne senza direzione: ${lacune.length}` }),
        document.createTextNode(
          aperte.length
            ? ` — ${aperte.length} su unita' ancora aperte. Chi finisce deve lasciare cosa fare dopo: senza, il lavoro si ferma al primo che apre la pagina.`
            : " — tutte su unita' gia' chiuse."
        ),
      ]),
      ...(aperte.length ? aperte : lacune).map(handoffGapRow)
    );
    return;
  }
  const cerca = cercaTestimone.trim().toLowerCase();
  let voci = dichiarazioni;
  if (filtroTestimone === "aperte") voci = voci.filter((voce) => voce.unit_open);
  if (cerca) {
    voci = voci.filter(
      (voce) =>
        voce.phase.toLowerCase().includes(cerca) ||
        (voce.items || []).some((item) => item.text.toLowerCase().includes(cerca))
    );
  }
  count.textContent = `${voci.length} di ${dichiarazioni.length} dichiarazioni${
    lacune.length ? ` · ${lacune.length} senza direzione` : ""
  }`;
  box.replaceChildren(
    ...(voci.length
      ? voci.map(handoffRow)
      : [h("p", { class: "empty" }, [h("b", { text: "Nessuna dichiarazione con questo filtro. " })])])
  );
}

/* Una dichiarazione = una riga. Il testo sta chiuso: e' quello che ha scritto chi ha finito, e si
   apre solo quello che serve. */
function handoffGroup(dichiarazioni, lacune) {
  const aperte = lacune.filter((voce) => voce.unit_open);
  const head = h("p", { class: "actgroup accent" }, [
    h("b", { text: "Cosa c'e' da fare dopo" }),
    h("span", {
      class: "actcount",
      text: `${dichiarazioni.length} dichiarate${aperte.length ? ` · ${aperte.length} consegne senza direzione` : ""}`,
    }),
  ]);
  const voci = dichiarazioni.slice(0, 12).map(handoffRow);
  const resto = dichiarazioni.slice(12);
  if (resto.length) {
    voci.push(
      h("details", { class: "actbox" }, [
        h("summary", { class: "acthead", text: `le altre ${resto.length} dichiarazioni` }),
        ...resto.map(handoffRow),
      ])
    );
  }
  const corpo = [head, ...voci];
  if (lacune.length) {
    corpo.push(
      h("details", { class: "actbox" }, [
        h("summary", { class: "acthead" }, [
          h("b", { text: `Consegne senza direzione: ${lacune.length}` }),
          document.createTextNode(
            aperte.length
              ? ` — ${aperte.length} su unita' ancora aperte (${aperte.map((v) => v.phase).join(", ")}). Chi finisce deve lasciare cosa fare dopo: senza, il lavoro si ferma al primo che apre la pagina.`
              : " — tutte su unita' gia' chiuse."
          ),
        ]),
        ...(aperte.length ? aperte : lacune).slice(0, 12).map(handoffGapRow),
      ])
    );
  }
  return h("div", { class: "actbox" }, corpo);
}

function handoffRow(voce) {
  const riga = h("div", { class: "actrow handoff" });
  const testo = h("div", { class: "acttext" });
  testo.append(h("code", { class: "actcode", text: voce.phase }));
  testo.append(
    document.createTextNode(
      ` ${[voce.block, voce.status, voce.when, voce.unit_open ? "unita' aperta" : "unita' chiusa"]
        .filter(Boolean)
        .join(" · ")}`
    )
  );
  voce.items.forEach((item) => testo.append(h("div", { class: "actquote", text: item.text })));
  riga.append(testo);
  const azioni = h("div", { class: "actactions" });
  const apri = h("button", {
    type: "button",
    class: "actbtn release",
    text: "Apri il report",
    title: voce.source,
  });
  apri.addEventListener("click", () => openReportPath(`${voce.phase} — cosa c'e' da fare dopo`, voce.source));
  azioni.append(apri);
  riga.append(azioni);
  return riga;
}

/* La lacuna si puo' chiudere da qui: chi ha finito scrive cosa fare dopo in dieci secondi, senza
   aprire un YAML. La nota va nel registro, con la coda di sempre. */
function handoffGapRow(voce) {
  const riga = h("div", { class: "actrow waiting" });
  const testo = h("div", { class: "acttext" });
  testo.append(h("code", { class: "actcode", text: voce.phase }));
  testo.append(
    document.createTextNode(
      ` ${[voce.block, voce.status, voce.when, voce.unit_open ? "unita' aperta" : "unita' chiusa"]
        .filter(Boolean)
        .join(" · ")}`
    )
  );
  testo.append(h("div", { class: "actmeta", text: `consegna: ${voce.source} — nessuna direzione dichiarata` }));
  riga.append(testo);
  const message = h("span", { class: "msg", role: "status", "aria-live": "polite" });
  const campo = h("textarea", {
    class: "actnote",
    rows: "2",
    placeholder: "Cosa c'e' da fare dopo su questa fase…",
  });
  const salva = h("button", { type: "button", class: "actbtn", text: "Lascia le istruzioni" });
  salva.addEventListener("click", async () => {
    const note = campo.value.trim();
    if (!note) {
      message.className = "msg show err";
      message.textContent = "scrivi cosa fare dopo: senza testo non registro niente.";
      campo.focus();
      return;
    }
    salva.disabled = true;
    message.className = "msg show pending";
    message.textContent = "scrivo…";
    try {
      const response = await fetch("/api/handoff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: voce.phase, note }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `errore ${response.status}`);
      message.className = "msg show ok";
      message.textContent = `scritto in ${payload.applied}: adesso chi apre la pagina lo vede.`;
      setTimeout(load, 1600);
    } catch (error) {
      message.className = "msg show err";
      message.textContent = `non scritto: ${error.message}`;
      salva.disabled = false;
    }
  });
  const azioni = h("div", { class: "actactions" }, [salva]);
  const blocco = h("div", { class: "actnote-box" }, [campo]);
  riga.append(azioni, blocco, message);
  return riga;
}

function activationGroup(titolo, tono, voci, rilasciabili, apriPrompt = false) {
  const head = h("p", { class: `actgroup ${tono}` }, [
    h("b", { text: titolo }),
    h("span", { class: "actcount", text: String(voci.length) }),
  ]);
  return h("div", { class: "actbox" }, [
    head,
    // «In attesa di un esecutore» vuol dire che il prompt serve ADESSO: si carica e si apre da
    // solo, invece di stare dietro un pulsante. Chi legge quella riga si aspetta il prompt.
    ...voci.map((voce) => activationRow(voce, false, Boolean(rilasciabili), Boolean(rilasciabili) && apriPrompt)),
  ]);
}

function activationRow(voce, attesa, rilasciabile, apriPrompt) {
  const riga = h("div", { class: `actrow${attesa ? " waiting" : ""}` });
  // Il pulsante della coda nasce qui ma si aggancia DOPO, quando `azioni` esiste: metterlo dentro
  // il blocco qui sotto faceva esplodere il disegno («Cannot access 'azioni' before initialization»)
  // e la pagina restava ferma dalla coda in giù — segnalato dall'utente come «si è impallato».
  let copiaCoda = null;
  const testo = h("div", { class: "acttext" });
  testo.append(h("code", { class: "actcode", text: voce.phase }));
  testo.append(document.createTextNode(` ${voce.title || ""}`));
  testo.append(
    h("div", {
      class: "actmeta",
      text: [
        voce.block,
        voce.rework ? "respinta in verifica" : voce.status,
        (voce.waiting_on || []).length ? `attende ${voce.waiting_on.join(", ")}` : null,
        voce.order ? `ordine ${voce.order}` : null,
        voce.since ? `attivata ${voce.since}` : null,
      ]
        .filter(Boolean)
        .join(" · "),
    })
  );
  // LA MISURA DELLA RIPETIZIONE. Una fase respinta dieci volte, sempre per lo stesso motivo, non e'
  // la stessa cosa di una respinta ieri: li' un altro tentativo non e' la leva, e chi legge deve
  // saperlo PRIMA di premere «Attiva». I numeri vengono dai report, non da una stima.
  const misura = voce.misura;
  if (misura && misura.tentativi > 1) {
    testo.append(misuraRow(misura));
  }
  // IL MANDATO SCADUTO: l'ordine si dichiara superato al proprio interno, e consegnarlo di nuovo
  // brucia il turno di chi lo riceve. Attivare ne deposita uno nuovo.
  const traccia = rigaConsegna(voce.phase);
  if (traccia) testo.append(traccia);
  const mandato = voce.mandato;
  // «SI SBLOCCA IN UN MODO SOLO: LA FIRMA». Qui il prompt non basta, ed e' il difetto che l'utente
  // ha segnalato: non e' un lavoro da mandare a qualcuno, sono due condizioni da mettere a posto —
  // la coda applicata (senza, l'atto nasce su una base vecchia) e una firma che non abbia eseguito
  // quei byte. Se nel registro c'e' UNA firma sola, la seconda condizione oggi non e' soddisfatta da
  // nessuno che esista: e quello va detto, non lasciato scoprire al dodicesimo tentativo.
  if (misura && misura.solo_firma) {
    const inCoda = ((snapshot && snapshot.queue && snapshot.queue.per_fase_tutte) || {})[voce.phase] || 0;
    const firme = (snapshot && snapshot.signers) || { distinte: 0, elenco: [] };
    // Il comando copiato e' QUELLO INTERO, con la `cd` dentro: «applicalo dalla radice del progetto»
    // e' un'istruzione che pretende che tu sappia qual e' la radice — e l'utente non lo sa, ne' deve.
    const comando =
      ((snapshot && snapshot.queue && snapshot.queue.comandi) || {}).applica ||
      "python3 tools/registry_runner.py --once";
    copiaCoda = h("button", {
      type: "button",
      class: "actbtn release",
      text: "Copia il comando della coda",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(comando);
          message.className = "msg show ok";
          message.textContent = "copiato: incollalo nel terminale così com'è — contiene già la cartella del progetto.";
        } catch (error) {
          message.className = "msg show err";
          message.textContent = `non copiato (${error.message}): ${comando}`;
        }
      },
    });
    testo.append(
      h("div", { class: "actmeta" }, [
        h("b", { class: "warnnote", text: "perché non basta mandare un prompt: " }),
        document.createTextNode(
          (inCoda
            ? `${inCoda} richieste non applicate su questa fase — finché sono in coda si giudica una base vecchia. `
            : "la coda su questa fase è applicata. ") +
            (firme.distinte <= 1
              ? `Nel registro c'è una sola identità (${(firme.elenco[0] || {}).chi || "—"}): la condizione «chi accetta non ha eseguito quei byte» oggi non è soddisfatta.`
              : "L'atto va dato a una corsia che quei byte non li ha scritti.")
        ),
      ])
    );
  }
  if (mandato && mandato.scaduto) {
    // Due casi, e la differenza conta: un ordine dichiarato scaduto e un ordine GIA' ESEGUITO. Il
    // secondo e' quello che ha bloccato tutto il 2026-10-16: lo stesso mandato consegnato a cinque
    // attivazioni, mentre gli atti pubblicati dopo di lui lo avevano gia' consumato.
    const eseguito = (mandato.consumato_da || []).length;
    const atti = (mandato.consumato_da || [])
      .slice(-3)
      .map((nome) => nome.replace("attempt-", "").replace(".yaml", ""))
      .join(", ");
    testo.append(
      h("div", { class: "actmeta" }, [
        h("b", { class: "warnnote", text: eseguito ? "mandato già eseguito" : "mandato scaduto" }),
        document.createTextNode(
          eseguito
            ? ` — ${eseguito} atti lo hanno già consumato (attempt ${atti}). Riconsegnarlo manda qualcuno a rifare un lavoro su byte di prima: attivare deposita un ordine NUOVO, col prompt e le impronte di adesso.`
            : " — l'ordine si dichiara superato al proprio interno. Attivare deposita un ordine NUOVO, col prompt e le impronte di adesso."
        ),
      ])
    );
    if (mandato.consegnato_a > 1) {
      testo.append(
        h("div", {
          class: "actmeta",
          text: `questo mandato è già stato consegnato a ${mandato.consegnato_a} attivazioni.`,
        })
      );
    }
  }
  riga.append(testo);
  const message = h("span", { class: "msg", role: "status", "aria-live": "polite" });
  const azioni = h("div", { class: "actactions" });
  if (copiaCoda) azioni.append(copiaCoda);
  // Una fase gia' attivata serve a UNA cosa: dare il prompt a un esecutore. Quindi copia in un clic,
  // leggi nel dialogo, oppure togli la riserva. Il testo non sta in linea: era il muro.
  if (rilasciabile) {
    azioni.append(
      promptCopiaButton(voce.phase),
      promptSalvaButton(voce.phase),
      promptLeggiButton(voce.phase)
    );
  }
  azioni.append(
    rilasciabile
      ? activationButton(voce.phase, "release", "Rilascia", message, false)
      : activationButton(voce.phase, "activate", "Attiva", message, attesa)
  );
  // Sulla fase di ACCETTAZIONE c'e' anche il pulsante per accoglierla: e' la risposta a «dove accolgo
  // i cambiamenti», e prima non esisteva. Compare anche sulla fase RISERVATA (in attesa di un
  // esecutore): chi accetta e' il padrone, e la prenotazione non lo blocca.
  if (/R$/.test(voce.phase) || /acceptance|accettazione/i.test(String(voce.kind || ""))) {
    const precedente = fasePrecedente(voce.phase);
    if (precedente && precedente.delivered) {
      azioni.append(bottoneEsiti(precedente.id, `Esiti di ${precedente.suffix}`));
    }
    azioni.append(acceptButton(voce.phase, message));
  }
  riga.append(azioni, message);
  if (!rilasciabile) riga.append(activationPromptButton(voce.phase, Boolean(apriPrompt)));
  return riga;
}

/* Quante volte questa fase e' tornata indietro, e per cosa. Quando l'ostacolo ha lo stesso nome in
   tutte le prove, la riga lo dice con quelle parole: e' la differenza fra «rifai» e «non e' cosi'
   che si sblocca». Chi lo deve e' un campo del report, non una deduzione: se li' c'e' scritto
   l'utente, vuol dire che nessun altro tentativo lo chiude. */
function misuraRow(misura) {
  const primo = (misura.ricorrenti || [])[0];
  const riga = h("div", { class: "actmeta" }, [
    h("b", { text: `${misura.tentativi} tentativi · ${misura.respinte} respinte` }),
    document.createTextNode(
      misura.solo_firma
        ? ` · l'ostacolo che torna è la FIRMA, non il prodotto: ${primo ? primo.id : ""}`
        : primo
        ? ` · lo stesso ostacolo in ${primo.volte} su ${misura.tentativi}: ${primo.id}${
            primo.bloccante ? " (bloccante)" : ""
          }`
        : " · nessun ostacolo con lo stesso nome: ogni atto nomina punti nuovi"
    ),
  ]);
  const parti = [riga];
  if (primo && primo.chi) {
    const chi = primo.chi.length > 160 ? `${primo.chi.slice(0, 157)}…` : primo.chi;
    parti.push(h("div", { class: "actmeta", title: primo.chi, text: `chi lo deve: ${chi}` }));
  }
  if (misura.ripetuta) {
    parti.push(
      h("div", { class: "actmeta" }, [
        h("b", {
          class: "warnnote",
          text: misura.solo_firma
            ? "si sblocca in un modo solo: chi firma non deve aver eseguito quei byte"
            : "questo non si sblocca con un altro tentativo",
        }),
        document.createTextNode(
          misura.solo_firma
            ? " — non è un lavoro da rifare: è una condizione. Il prompt qui sotto va dato a una corsia che quei byte non li ha scritti."
            : " — l'ostacolo torna identico in ogni prova."
        ),
      ])
    );
  }
  return parti.length === 1 ? riga : h("div", {}, parti);
}

/* COPIARE UN TESTO, DAVVERO. `navigator.clipboard` e' comodo ma ha due condizioni che non si vedono:
   la pagina deve essere un contesto sicuro e la finestra deve avere il FUOCO — e dopo un `await` (la
   `fetch` del prompt) l'attivazione dell'utente puo' essere scaduta. Il risultato e' che il clic non
   copia e chi legge pensa che la pagina sia rotta. Qui: prima la Clipboard API, poi il ripiego
   classico (`textarea` + `execCommand`), e se anche quello fallisce si dice all'utente di selezionare
   il testo — il prompt nel dialogo gli resta davanti, selezionato. */
async function copiaTesto(testo) {
  const valore = String(testo || "");
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(valore);
      return { ok: true, come: "clipboard" };
    }
  } catch (errore) {
    // si prova l'altra strada
  }
  try {
    const area = document.createElement("textarea");
    area.value = valore;
    area.setAttribute("readonly", "readonly");
    area.style.position = "fixed";
    area.style.top = "-1000px";
    document.body.append(area);
    area.select();
    area.setSelectionRange(0, valore.length);
    const fatto = document.execCommand("copy");
    area.remove();
    if (fatto) return { ok: true, come: "execCommand" };
  } catch (errore) {
    // niente: si finisce sulla selezione
  }
  return { ok: false, come: "selezione" };
}

/* Il prompt di una fase: copiato in un clic, o letto nel dialogo. Le due funzioni chiedono il testo
   all'API solo quando servono, e non lo mettono mai in pagina. */
async function chiediPrompt(phase) {
  const response = await fetch(`/api/prompt?target=${encodeURIComponent(phase)}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `errore ${response.status}`);
  return payload;
}

function promptCopiaButton(phase) {
  const esito = h("span", { class: "msg", role: "status", "aria-live": "polite" });
  const bottone = h("button", { type: "button", class: "actbtn", text: "Copia il prompt" });
  bottone.addEventListener("click", async () => {
    bottone.disabled = true;
    esito.className = "msg show pending";
    esito.textContent = "preparo…";
    try {
      const payload = await chiediPrompt(phase);
      const copia = await copiaTesto(payload.text || "");
      esito.className = copia.ok ? "msg show ok" : "msg show err";
      esito.textContent = copia.ok
        ? `copiato (${(payload.text || "").length} caratteri, fonte: ${payload.source}). Incollalo come primo messaggio di una chat nuova.`
        : "NON copiato da solo: il prompt è qui sotto, selezionalo e premi Ctrl+C (Cmd+C).";
      if (!copia.ok) apriTesto(`${phase} — il prompt`, payload.text, { copia: true, seleziona: true, file: `prompt-${phase}.md` });
    } catch (error) {
      esito.className = "msg show err";
      esito.textContent = `non copiato: ${error.message}`;
    } finally {
      bottone.disabled = false;
    }
  });
  const scatola = h("span", { class: "actprompt-box" });
  scatola.append(bottone, esito);
  return scatola;
}

function promptLeggiButton(phase) {
  const bottone = h("button", { type: "button", class: "actbtn release", text: "Leggi" });
  bottone.addEventListener("click", async () => {
    bottone.disabled = true;
    try {
      const payload = await chiediPrompt(phase);
      apriTesto(`${phase} — il prompt`, payload.text, { copia: true, file: `prompt-${phase}.md` });
    } catch (error) {
      apriTesto(`${phase} — il prompt`, `non disponibile: ${error.message}`);
    } finally {
      bottone.disabled = false;
    }
  });
  return bottone;
}

/* «Salva come file» sulla riga: il prompt scende come .md senza aprire niente. Serve a portare il
   testo fuori dal browser intatto — se il file e' giusto e quello incollato no, il difetto e' nel
   posto che lo riceve, non nel prompt. */
function promptSalvaButton(phase) {
  const etichetta = "Salva come file";
  const bottone = h("button", { type: "button", class: "actbtn release", text: etichetta });
  const ripiglia = () => setTimeout(() => (bottone.textContent = etichetta), 2500);
  bottone.addEventListener("click", async () => {
    bottone.disabled = true;
    try {
      const payload = await chiediPrompt(phase);
      scaricaFile(payload.text || "", `prompt-${phase}.md`);
      bottone.textContent = "salvato";
    } catch (error) {
      bottone.textContent = "non salvato";
      bottone.title = error.message;
    } finally {
      ripiglia();
      bottone.disabled = false;
    }
  });
  return bottone;
}

/* Il file scende da un <a download> creato al volo: nessun dialogo, nessuna clipboard di mezzo. */
function scaricaFile(testo, nome) {
  const link = linkSalvaFile(testo, nome);
  link.hidden = true;
  document.body.append(link);
  link.click();
  setTimeout(() => link.remove(), 0);
}

/* Il prompt della fase, a richiesta: quello del quaderno se c'e' una sezione per quella fase,
   altrimenti composto dal registro (criteri di accettazione, perimetro, protocollo). */
function activationPromptButton(phase, apri) {
  const button = h("button", {
    type: "button",
    class: "actbtn release",
    text: "Prompt",
    title: "il testo da incollare in una chat per far partire questa fase",
  });
  const scatola = h("div", { class: "actprompt", hidden: true });
  let caricato = null;
  const mostra = async () => {
    scatola.hidden = false;
    button.textContent = "Chiudi il prompt";
    if (caricato) return;
    caricato = true;
    scatola.replaceChildren(h("p", { class: "actmeta", text: "compongo…" }));
    try {
      const response = await fetch(`/api/prompt?target=${encodeURIComponent(phase)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `errore ${response.status}`);
      const copia = h("button", { type: "button", class: "actbtn", text: "Copia il prompt" });
      const esito = h("span", { class: "msg", role: "status", "aria-live": "polite" });
      copia.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(payload.text);
          esito.className = "msg show ok";
          esito.textContent = "copiato: incollalo come primo messaggio di una chat nuova.";
        } catch (error) {
          esito.className = "msg show err";
          esito.textContent = `non copiato (${error.message}): seleziona il testo e copialo a mano.`;
        }
      });
      scatola.replaceChildren(
        h("p", { class: "actmeta", text: `fonte: ${payload.source}` }),
        h("pre", { class: "acttext-pre", text: payload.text }),
        h("div", { class: "actactions" }, [
          copia,
          linkSalvaFile(payload.text, `prompt-${phase}.md`),
          esito,
        ])
      );
    } catch (error) {
      caricato = null;
      scatola.replaceChildren(
        h("p", { class: "actmeta", text: `prompt non disponibile: ${error.message}` })
      );
    }
  };
  button.addEventListener("click", () => {
    if (!scatola.hidden) {
      scatola.hidden = true;
      button.textContent = "Prompt";
      return;
    }
    mostra();
  });
  const contenitore = h("span", { class: "actprompt-box" });
  contenitore.append(button, scatola);
  if (apri) setTimeout(mostra, 0);
  return contenitore;
}

/* DOVE SI ACCOGLIE UN CAMBIAMENTO. Fino a ieri: da nessuna parte — l'accettazione era un atto che
   scriveva un agente, e chi ha l'autorita' di firmare non ha un terminale. Qui il pulsante scrive
   l'ATTO firmato `utente` (una mano che quei byte non li ha scritti): report, puntatore e stato nel
   registro, sotto il lock. Il cancello decide se si puo': se la base non e' pronta, non firma e dice
   perche' — e l'atto dichiara cosa ha letto e cosa NON ha rieseguito. */
function acceptButton(phase, message, seServeRifai) {
  const bottone = h("button", {
    type: "button",
    class: "actbtn",
    text: "Accetta (firmato da te)",
    title:
      "scrive l'atto di accettazione firmato da te: dichiara cosa hai letto e che non hai rieseguito le prove",
  });
  bottone.addEventListener("click", async () => {
    bottone.disabled = true;
    message.className = "msg show pending";
    message.textContent = "controllo la base, poi firmo…";
    try {
      const risposta = await fetch("/api/accept", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phase }),
      });
      const payload = await risposta.json();
      if (!risposta.ok) throw new Error(payload.error || `errore ${risposta.status}`);
      message.className = "msg show ok";
      message.textContent = `ACCETTATA: atto ${payload.atto} (attempt ${payload.numero}), registro aggiornato. Firmato da te: l'atto dichiara che non hai rieseguito le prove.`;
      setTimeout(load, 1500);
    } catch (error) {
      message.className = "msg show err";
      message.textContent = `non accettata: ${error.message}`;
      if (/revisione giudicata|puntatore nomina/i.test(error.message)) {
        message.textContent += " — il lavoro va rifatto sui byte vivi: usa «Rifai (prompt)».";
        if (seServeRifai) seServeRifai();
      }
      bottone.disabled = false;
    }
  });
  // «Cos'è» accanto alla firma: cosa vuol dire accettare, e cosa dichiara «non rieseguito».
  return h("span", { class: "phasecell" }, [
    bottone,
    bottoneCosa("accettazione", () =>
      spiega(`Accettare ${phase}`, [
        "L'atto dichiara: <b>ho letto queste prove</b> (il report della verifica col suo verdetto, i log, le impronte) e <b>non ho rifatto le corse</b>. La misura del comportamento è della verifica: rifarla sarebbe la stessa misura due volte.",
        "Sul front-end: non ti è richiesto di andarci per firmare, e l'atto non dichiara che non ci sei andato — parla di cosa hai <b>rieseguito</b>, non di cosa hai guardato. Se ci vai e vuoi che conti, va scritto nell'atto come evidenza.",
        "Accettando ti prendi <b>l'evidenza di un altro</b>: se era parziale, il limite è tuo. Per questo l'atto nomina i residui e chi li deve.",
        "L'unica cosa che «non rieseguito» non deve mai voler dire è «nessuno ha misurato»: senza un report con casi e log non c'è niente da accettare.",
      ])
    ),
  ]);
}

function activationButton(phase, action, label, message, disabled) {
  const button = h("button", {
    type: "button",
    class: `actbtn ${action}`,
    text: label,
    disabled: Boolean(disabled),
    title: disabled
      ? "in attesa delle unita' a monte"
      : action === "release"
        ? "toglie la riserva: la fase torna disponibile, l'ordine resta sul disco"
        : "deposita l'ordine e riserva la fase nel registro",
  });
  button.addEventListener("click", async () => {
    button.disabled = true;
    message.className = "msg show pending";
    message.textContent = action === "release" ? "rilascio in corso…" : "attivazione in corso…";
    try {
      const response = await fetch("/api/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target: phase, action }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || `errore ${response.status}`);
      message.className = "msg show ok";
      if (action === "release") {
        message.textContent = "rilasciata: la fase è di nuovo disponibile, l'ordine resta su disco.";
      } else {
        // ATTIVARE NON AVVIA NESSUNO — e il passo dopo dev'essere a portata di mano, non raccontato.
        // Dopo l'ordine si apre il PROMPT col pulsante per copiarlo, e la riga dice le tre cose che
        // servono: dov'è l'ordine, che la fase è riservata, e che adesso il prompt va consegnato.
        message.textContent = `ORDINE DEPOSITATO: ${payload.order} — la fase è RISERVATA e non la sta facendo nessuno. Ecco il prompt: copialo e dallo a una corsia.`;
        try {
          const testo = await chiediPrompt(phase);
          apriTesto(`${phase} — il prompt da consegnare a una corsia`, testo.text, {
            copia: true,
            file: `prompt-${phase}.md`,
          });
        } catch (error) {
          message.textContent += ` (il prompt non si è aperto: ${error.message})`;
        }
      }
      setTimeout(load, 1600);
    } catch (error) {
      message.className = "msg show err";
      message.textContent = `non fatto: ${error.message}`;
      button.disabled = false;
    }
  });
  return button;
}

/* -------------------------------------------------------- percorso nel tempo */
/* Le date arrivano dal server e sono SEMPRE una misura: `published_at` scritta nell'artefatto,
   altrimenti l'mtime del puntatore, altrimenti niente. La barra non e' una previsione e non
   viene disegnata quando la data non c'e'. */
let timeline = null;
let mappaScelta = false;
const TIMELINE_STATE = {
  accettata: "accettata",
  in_corso: "in corso",
  respinta: "respinta",
  da_fare: "da fare",
};

async function loadTimeline() {
  const box = $("#gantt");
  if (!box) return;
  try {
    const response = await fetch("/api/timeline");
    if (!response.ok) throw new Error(`errore ${response.status}`);
    timeline = await response.json();
  } catch (error) {
    box.replaceChildren(
      h("p", { class: "empty" }, [
        h("b", { text: "Linea del tempo non leggibile. " }),
        document.createTextNode(`${error.message}. Il resto della pagina resta valido.`),
      ])
    );
    return;
  }
  renderTimelineNotes(timeline);
  renderMappa();
  renderGantt();
  renderBlocks(); // il pannello del blocco mostra anche i commit: si completa quando arrivano
  applyHash();
}

/* La pagina si riempie DOPO il caricamento: il salto all'ancora che fa il browser atterra su un
   documento ancora corto, e poi le sezioni sopra crescono e lo spingono via. Un link a
   `#timeline-section` o a un prompt finiva due schermate piu' in alto (misurato il 2026-10-15).
   Si riapplica UNA volta, appena la sezione che contiene il bersaglio e' disegnata. */
let hashApplied = false;
function applyHash() {
  if (hashApplied || !location.hash) return;
  const target = document.querySelector(location.hash);
  if (!target) return;
  hashApplied = true;
  target.scrollIntoView({ block: "start" });
}

function renderTimelineNotes(data) {
  const box = $("#timeline-notes");
  if (!box) return;
  const measured = data.measured || {};
  const giorni = (data.days || []).length;
  const senzaDate = !(data.measured || {}).dichiarata && !(data.measured || {}).mtime;
  const parts = [
    h("p", { class: "gmeta" }, [
      h("b", {
        text: senzaDate
          ? "Nessuna data ancora: le barre compaiono con la prima consegna"
          : giorni > 1
            ? `${data.from} → ${data.to}`
            : data.from,
      }),
      document.createTextNode(
        ` · ${giorni} ${giorni === 1 ? "giorno" : "giorni"} · date delle fasi: ${measured.dichiarata || 0} dichiarate dagli artefatti, ` +
          `${measured.mtime || 0} prese dall'mtime del puntatore, ${measured.senza_data || 0} senza data ` +
          "(fasi mai eseguite)"
      ),
    ]),
  ];

  const commits = data.commits || {};
  if (commits.available) {
    const last = commits.last || {};
    const details = h("details", {}, [
      h("summary", { text: `i ${commits.total} commit del repository` }),
      h(
        "ul",
        { class: "gcommits" },
        (commits.list || []).map((commit) =>
          h("li", {}, [
            h("span", { class: "sha", text: commit.sha }),
            h("span", { class: "when", text: String(commit.date).slice(0, 10) }),
            document.createTextNode(`${commit.subject} — ${commit.files} file`),
          ])
        )
      ),
    ]);
    const note = h("div", { class: "gnote" }, [
      h("p", {}, [
        h("b", { text: `Commit: ${commits.in_window} nella finestra disegnata. ` }),
        document.createTextNode(
          `L'ultimo del repository è ${last.sha}, del ${String(last.date).slice(0, 10)} («${last.subject}»): ` +
            `${commits.total} in tutto, e nessuno copre il lavoro di questi giorni. In albero adesso, ` +
            `nel workspace: ${commits.untracked} file non tracciati e ${commits.modified} modificati.`
        ),
      ]),
    ]);
    if (commits.tracked_pack_files === 0) {
      note.append(
        h("p", { class: "warnnote" }, [
          h("b", { text: "Il workspace non è tracciato: " }),
          document.createTextNode(
            "nessun file di questo workspace è dentro un commit, quindi la riga dei commit resta vuota per costruzione, non perché non si sia lavorato."
          ),
        ])
      );
    }
    note.append(details);
    parts.push(note);
  } else {
    parts.push(
      h("div", { class: "gnote" }, [
        h("b", { text: "Commit non leggibili: " }),
        document.createTextNode(commits.reason || "git non disponibile"),
      ])
    );
  }

  box.replaceChildren(...parts);
}

function slug(value) {
  return String(value || "x").replace(/[^a-z0-9]+/gi, "-");
}

function ganttHeader(days) {
  const totals = new Map();
  (timeline.commits && timeline.commits.by_day ? Object.entries(timeline.commits.by_day) : []).forEach(
    ([day, items]) => totals.set(day, (items || []).length)
  );
  const cells = days.map((day) => {
    const count = totals.get(day) || 0;
    return h("span", {
      class: `gday${day.today ? " today" : ""}${day.weekend ? " weekend" : ""}${count ? " has-commits" : ""}`,
      title: count ? `${day.date}: ${count} commit` : day.date,
      text: count ? `${day.label}•${count}` : day.label,
    });
  });
  return h("div", { class: "grow ghead" }, [
    h("div", { class: "gname", text: "blocco · unità" }),
    h("div", { class: "gtrack" }, [
      h("div", { class: "ggrid", style: `grid-template-columns:repeat(${days.length},1fr)` }, cells),
    ]),
    h("div", { class: "gbadges" }),
  ]);
}

function ganttTrack(node, dots) {
  const total = timeline.days.length || 1;
  const pieces = [
    h(
      "div",
      { class: "ggrid", style: `grid-template-columns:repeat(${total},1fr)` },
      timeline.days.map((day) => h("span", { class: day.today ? "today" : "" }))
    ),
  ];
  if (node.start !== null && node.start !== undefined) {
    const end = node.end === null || node.end === undefined ? node.start : node.end;
    pieces.push(
      h("div", {
        class: `gbar ${node.state || ""}`,
        style: `left:${(node.start / total) * 100}%;width:${((end - node.start + 1) / total) * 100}%`,
      })
    );
  } else {
    // Nessuna data non vuol dire «zero giorni»: vuol dire che nessun atto di quel nodo esiste
    // ancora. Si scrive, invece di disegnare una barra che non c'e'.
    pieces.push(h("span", { class: "gnodate", text: "nessuna data: non ancora iniziata" }));
  }
  (dots || []).forEach((dot) => {
    if (dot.day === null || dot.day === undefined) return;
    const mark = h("div", {
      class: `gdot ${dot.status} ${dot.dated}`,
      style: `left:${((dot.day + 0.5) / total) * 100}%`,
      title: `${dot.id} · ${dot.status} · ${dot.at || dot.date || "senza data"} (${dot.dated})`,
    });
    pieces.push(mark);
  });
  return h("div", { class: "gtrack" }, pieces);
}

function ganttChips(node, openDetail) {
  const chips = [
    h("span", { class: `chip stato ${node.state}`, text: TIMELINE_STATE[node.state] || node.state }),
    h("span", {
      class: `chip next${node.next ? "" : " none"}`,
      text: node.next ? node.next.label : "niente",
      title: node.next ? node.next.detail || "" : "",
    }),
  ];
  const yours = node.yours || [];
  if (yours.length) {
    const chip = h("button", {
      type: "button",
      class: "chip yours",
      text: `${yours.length} per te`,
      title: "cosa aspetta te su questo nodo",
    });
    chip.addEventListener("click", () => openDetail(true));
    chips.push(chip);
  } else {
    chips.push(h("span", { class: "chip yours none", text: "—" }));
  }
  return h("div", { class: "gbadges" }, chips);
}

function detailLine(label, text) {
  const line = h("div", { class: "dline" }, [h("b", { text: label })]);
  line.append(document.createTextNode(text));
  return line;
}

/* Una riga «per te», con il link al posto giusto. Il link serve anche a livello di blocco: l'unita'
   che aspetta qualcosa da te puo' essere fuori dal filtro corrente (e' il caso di QA06, accettata
   mentre il suo prompt §5 e' ancora da lanciare), e senza link quella richiesta resterebbe
   scritta e non raggiungibile. */
function yoursLine(item, showUnit) {
  const line = h("div", { class: "dline" }, [h("b", { text: "Per te: " })]);
  const label = `${showUnit && item.unit ? `${item.unit} · ` : ""}${item.kind} ${item.label}`;
  line.append(
    item.target
      ? h("a", { class: "dlink", href: item.target, text: label })
      : document.createTextNode(label)
  );
  line.append(document.createTextNode(` — ${item.detail}`));
  return line;
}

function unitDetail(unit, id) {
  const panel = h("div", { class: "gdetail", id, hidden: true });
  panel.append(
    unit.next
      ? detailLine("Da farsi: ", `${unit.next.label} — ${unit.next.detail}`)
      : detailLine("Da farsi: ", "niente, l'unità è accettata")
  );
  if (unit.waiting_on && unit.waiting_on.length) {
    panel.append(detailLine("Aspetta a monte: ", unit.waiting_on.join(", ")));
  }
  (unit.due || []).forEach((item) => {
    panel.append(detailLine("Obbligo aperto: ", `${item.label} — ${item.detail}`));
  });
  (unit.yours || []).forEach((item) => panel.append(yoursLine(item, false)));
  panel.append(
    h(
      "div",
      { class: "dphases" },
      unit.phases.map((fase) =>
        cellaFase(fase)
      )
    )
  );
  return panel;
}

function ganttUnit(unit) {
  const detailId = `gdetail-${slug(unit.id)}`;
  const row = h("div", { class: `grow gunit ${unit.state}`, "data-level": "2" });
  const name = h("div", { class: "gname" });
  const toggle = h("button", {
    type: "button",
    class: "gtoggle",
    "aria-expanded": "false",
    "aria-controls": detailId,
  });
  toggle.append(h("span", { class: "caret", "aria-hidden": "true" }));
  toggle.append(h("span", { class: "gtitle", text: unit.id }));
  if (unit.title) toggle.append(h("span", { class: "gsubtitle", text: unit.title }));
  const detail = unitDetail(unit, detailId);
  let open = false;
  const setOpen = (value) => {
    open = value;
    toggle.setAttribute("aria-expanded", String(open));
    detail.hidden = !open;
  };
  toggle.addEventListener("click", () => setOpen(!open));
  name.append(toggle);
  row.append(name, ganttTrack(unit, unit.phases), ganttChips(unit, setOpen));
  return [row, detail];
}

function ganttBlock(block, units) {
  const childrenId = `gchildren-${slug(block.domain)}`;
  const children = h("div", { class: "gchildren", id: childrenId, hidden: true });
  units.forEach((unit) => {
    ganttUnit(unit).forEach((node) => children.append(node));
  });
  const row = h("div", { class: `grow gblock ${block.state}`, "data-level": "1" });
  const toggle = h("button", {
    type: "button",
    class: "gtoggle",
    "aria-expanded": "false",
    "aria-controls": childrenId,
  });
  toggle.append(h("span", { class: "caret", "aria-hidden": "true" }));
  toggle.append(h("span", { class: "gtitle", text: block.domain }));
  toggle.append(h("span", { class: "tally", text: `${block.accepted}/${block.total} accettate` }));
  const detail = h("div", { class: "gdetail", hidden: true });
  if (block.next && block.next.label) {
    detail.append(detailLine("Da farsi: ", block.next.label));
  }
  (block.yours || []).forEach((item) => detail.append(yoursLine(item, true)));
  let open = false;
  const setOpen = (value) => {
    open = value;
    toggle.setAttribute("aria-expanded", String(open));
    children.hidden = !open;
    detail.hidden = !open;
  };
  toggle.addEventListener("click", () => setOpen(!open));
  row.append(
    h("div", { class: "gname" }, [toggle]),
    ganttTrack(block, []),
    ganttChips(block, setOpen)
  );
  return [row, detail, children];
}

function renderGantt() {
  const box = $("#gantt");
  const count = $("#timeline-count");
  if (!box) return;
  if (!timeline || !timeline.days || !timeline.days.length) {
    box.replaceChildren(h("p", { class: "empty" }, [h("b", { text: "Nessuna data da disegnare." })]));
    return;
  }
  const nodes = [ganttHeader(timeline.days)];
  let shown = 0;
  let blocks = 0;
  (timeline.blocks || []).forEach((block) => {
    const units = visibleUnits(block.units);
    if (!units.length) return;
    blocks += 1;
    shown += units.length;
    ganttBlock(block, units).forEach((node) => nodes.push(node));
  });
  box.replaceChildren(...nodes);
  if (count) {
    count.textContent = `${blocks} blocchi · ${shown} unità mostrate con questo filtro`;
  }
}

/* LA MAPPA DEL PERCORSO. Non è una barra: è il grafo delle dipendenze. Ogni colonna è un livello
   (una unità sta nella colonna dopo la più profonda di quelle che aspetta), ogni scheda è una unità,
   ogni freccia va da ciò che serve a ciò che lo usa. Mostra TUTTE le unità: le accettate servono a
   capire da dove arriva quella aperta, e il filtro «Aperte / Tutte / Con problemi» non la tocca. */
const SVG_NS = "http://www.w3.org/2000/svg";

function svgNode(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    node.setAttribute(key, value);
  }
  return node;
}

function renderMappa() {
  const scena = $("#mappa-scena");
  const meta = $("#mappa-meta");
  if (!scena || !timeline) return;
  // Su schermo stretto la mappa parte chiusa: aperta occuperebbe mezza pagina per mostrare due
  // colonne. La scelta dell'utente, una volta fatta, resta.
  const dettaglio = $("#mappa");
  if (dettaglio && !dettaglio.dataset.ascoltato) {
    dettaglio.dataset.ascoltato = "1";
    dettaglio.addEventListener("toggle", () => {
      mappaScelta = true;
    });
  }
  if (dettaglio && !mappaScelta) {
    dettaglio.open = !window.matchMedia("(max-width: 720px)").matches;
  }
  const unita = [];
  for (const blocco of timeline.blocks || []) {
    for (const unit of blocco.units || []) {
      unita.push(Object.assign({}, unit, { blocco: blocco.domain }));
    }
  }
  if (!unita.length) {
    scena.replaceChildren(h("p", { class: "empty", text: "Nessuna unità da disegnare." }));
    return;
  }
  const perId = new Map(unita.map((unit) => [unit.id, unit]));
  const profondita = new Map();
  const inCorso = new Set();
  const livelloDi = (id) => {
    if (profondita.has(id)) return profondita.get(id);
    if (inCorso.has(id)) return 0; // un ciclo non deve far esplodere il disegno
    inCorso.add(id);
    const deps = (perId.get(id).depends_on || []).filter((dep) => perId.has(dep));
    const valore = deps.length ? 1 + Math.max(...deps.map(livelloDi)) : 0;
    inCorso.delete(id);
    profondita.set(id, valore);
    return valore;
  };
  unita.forEach((unit) => livelloDi(unit.id));
  const livelli = [];
  for (const unit of unita) {
    const livello = profondita.get(unit.id);
    (livelli[livello] = livelli[livello] || []).push(unit);
  }
  livelli.forEach((colonna) =>
    colonna.sort(
      (a, b) => String(a.blocco).localeCompare(String(b.blocco)) || a.id.localeCompare(b.id)
    )
  );
  // Due passate di baricentro: dentro un livello, chi serve a un nodo in alto resta in alto.
  for (let giro = 0; giro < 2; giro += 1) {
    for (let indice = 1; indice < livelli.length; indice += 1) {
      const prima = new Map((livelli[indice - 1] || []).map((unit, riga) => [unit.id, riga]));
      const media = (unit) => {
        const righe = (unit.depends_on || [])
          .map((dep) => prima.get(dep))
          .filter((riga) => riga !== undefined);
        return righe.length ? righe.reduce((a, b) => a + b, 0) / righe.length : 999;
      };
      livelli[indice].sort((a, b) => media(a) - media(b) || a.id.localeCompare(b.id));
    }
  }

  const W = 170;
  const H = 54;
  const GX = 58;
  const GY = 12;
  const PAD = 22;
  const righe = Math.max(...livelli.map((colonna) => colonna.length));
  const larghezza = PAD * 2 + livelli.length * (W + GX) - GX;
  const altezza = PAD * 2 + righe * (H + GY) - GY;
  const pos = new Map();
  livelli.forEach((colonna, livello) => {
    colonna.forEach((unit, riga) =>
      // Allineati in alto, non centrati: il primo livello (la radice) deve stare nella prima
      // schermata, non a metà di una colonna vuota.
      pos.set(unit.id, { x: PAD + livello * (W + GX), y: PAD + riga * (H + GY) })
    );
  });

  const svg = svgNode("svg", {
    id: "mappa-svg",
    viewBox: `0 0 ${larghezza} ${altezza}`,
    width: larghezza,
    height: altezza,
    role: "group",
    "aria-label": "Mappa delle dipendenze: ogni scheda è una unità, ogni freccia va da ciò che serve a ciò che lo usa",
  });
  const defs = svgNode("defs", {});
  const punta = svgNode("marker", {
    id: "punta-freccia",
    viewBox: "0 0 8 8",
    refX: "7",
    refY: "4",
    markerWidth: "6",
    markerHeight: "6",
    orient: "auto-start-reverse",
  });
  punta.append(svgNode("path", { d: "M0 0 L8 4 L0 8 z", class: "punta" }));
  defs.append(punta);
  const stratoArchi = svgNode("g", {});
  const stratoNodi = svgNode("g", {});
  const archi = [];
  const nodi = [];

  for (const unit of unita) {
    for (const dep of unit.depends_on || []) {
      if (!perId.has(dep)) continue;
      const da = pos.get(dep);
      const a = pos.get(unit.id);
      const x1 = da.x + W;
      const y1 = da.y + H / 2;
      const x2 = a.x;
      const y2 = a.y + H / 2;
      const mezzo = (x1 + x2) / 2;
      const arco = svgNode("path", {
        d: `M${x1} ${y1} C ${mezzo} ${y1}, ${mezzo} ${y2}, ${x2} ${y2}`,
        class: `arco ${unit.accepted ? "chiuso" : "aperto"}`,
        "data-from": dep,
        "data-to": unit.id,
      });
      archi.push(arco);
      stratoArchi.append(arco);
    }
  }

  for (const unit of unita) {
    const punto = pos.get(unit.id);
    const gruppo = svgNode("g", {
      class: `nodo ${unit.state || "da_fare"}`,
      transform: `translate(${punto.x} ${punto.y})`,
      tabindex: "0",
      role: "button",
      "aria-label": `${unit.id} — ${unit.title || ""}: ${TIMELINE_STATE[unit.state] || unit.state}`,
      "data-id": unit.id,
    });
    const titolo = svgNode("title", {});
    titolo.textContent =
      `${unit.id} — ${unit.title || ""} (${TIMELINE_STATE[unit.state] || unit.state})` +
      ((unit.waiting_on || []).length ? `\nAspetta: ${unit.waiting_on.join(", ")}` : "");
    gruppo.append(titolo);
    gruppo.append(svgNode("rect", { width: W, height: H, rx: 10 }));
    const id = svgNode("text", { class: "nid", x: 12, y: 22 });
    id.textContent = unit.id;
    gruppo.append(id);
    const blocco = svgNode("text", { class: "nblocco", x: 12, y: 38 });
    blocco.textContent = String(unit.blocco || "").slice(0, 22);
    gruppo.append(blocco);
    (unit.phases || []).forEach((fase, indice) => {
      const cx = W - 56 + indice * 14;
      const cy = H - 14;
      const stato = String(fase.status || "pending");
      const segno =
        stato === "needs_changes" || stato === "failed"
          ? svgNode("rect", { x: cx - 3, y: cy - 3, width: 6, height: 6, class: `fase ${stato}` })
          : svgNode("circle", { cx, cy, r: 3.5, class: `fase ${stato}` });
      const nome = svgNode("title", {});
      nome.textContent = `${fase.id}: ${stato}`;
      segno.append(nome);
      gruppo.append(segno);
    });
    const evidenzia = (attivo) => {
      svg.classList.toggle("evidenzia", attivo);
      for (const arco of archi) {
        arco.classList.toggle(
          "toccato",
          attivo && (arco.dataset.from === unit.id || arco.dataset.to === unit.id)
        );
      }
    };
    gruppo.addEventListener("mouseenter", () => evidenzia(true));
    gruppo.addEventListener("mouseleave", () => evidenzia(false));
    gruppo.addEventListener("focus", () => evidenzia(true));
    gruppo.addEventListener("blur", () => evidenzia(false));
    gruppo.addEventListener("click", () => spiegaUnita(unit));
    gruppo.addEventListener("keydown", (evento) => {
      if (evento.key === "Enter" || evento.key === " ") {
        evento.preventDefault();
        spiegaUnita(unit);
      }
    });
    nodi.push(gruppo);
    stratoNodi.append(gruppo);
  }

  svg.append(defs, stratoArchi, stratoNodi);
  scena.replaceChildren(svg);
  if (meta) {
    meta.textContent = `${unita.length} unità · ${archi.length} dipendenze · tutte, senza filtro. La freccia va da ciò che serve a ciò che lo usa; scorri in orizzontale, e clicca una scheda per il dettaglio.`;
  }
}

/* ------------------------------------------------------------------ percorso */
function visibleUnits(units) {
  if (filter === "all") return units;
  if (filter === "issues") return units.filter(hasIssues);
  return units.filter(isOpen);
}

/* I blocchi sono sedici: impilati uno sotto l'altro si leggono solo scorrendo. Qui diventano
   schede — una riga di tab per scegliere il blocco, un pannello solo coi suoi particolari. La tab
   porta lo stato (stessa forma della legenda), il conto delle unità e quante cose aspettano te. */
const BLOCK_STATE = {
  accettata: "accettata",
  in_corso: "in corso",
  respinta: "respinta in verifica",
  da_fare: "da fare",
};

/* Stati che significano «qualcuno ci sta lavorando»: gli stessi che il registro considera vivi. */
const RUNNING_STATES = ["running", "active", "taken", "active_extension"];

function blockState(units) {
  if (units.some(hasIssues)) return "respinta";
  if (units.some((unit) => unit.phases.some((p) => RUNNING_STATES.includes(p.status)))) {
    return "in_corso";
  }
  if (units.length && units.every((unit) => unit.accepted)) return "accettata";
  return "da_fare";
}

function pathTabs() {
  const fromTimeline = new Map(((timeline && timeline.blocks) || []).map((block) => [block.domain, block]));
  return ((snapshot && snapshot.blocks) || []).map((block) => {
    const extra = fromTimeline.get(block.domain) || {};
    return {
      domain: block.domain,
      units: visibleUnits(block.units),
      accepted: block.units.filter((unit) => unit.accepted).length,
      total: block.units.length,
      state: blockState(block.units),
      yours: (extra.yours || []).length,
      next: extra.next ? extra.next.label : null,
      commits: extra.commits || [],
      pathsDeclared: extra.paths_declared || 0,
    };
  });
}

function renderBlocks() {
  const box = $("#blocks");
  if (!box) return;
  const tabs = pathTabs().filter((tab) => tab.units.length);
  $("#visible-count").textContent = `${tabs.reduce((n, tab) => n + tab.units.length, 0)} unità mostrate`;
  if (!tabs.length) {
    box.replaceChildren(
      h("p", { class: "empty" }, [
        h("b", { text: "Niente da mostrare con questo filtro. " }),
        document.createTextNode("Prova «Tutte»."),
      ])
    );
    return;
  }
  if (!tabs.some((tab) => tab.domain === selectedBlock)) selectedBlock = tabs[0].domain;
  const current = tabs.find((tab) => tab.domain === selectedBlock);
  const list = h("div", { class: "tabs", role: "tablist", "aria-label": "Blocchi del percorso" });
  tabs.forEach((tab) => list.append(tabButton(tab, tabs)));
  const panel = h("div", {
    class: "tabpanel",
    id: "block-panel",
    role: "tabpanel",
    "aria-labelledby": `tab-${slug(current.domain)}`,
    tabindex: "0",
  });
  panel.append(...panelContent(current));
  box.replaceChildren(list, panel);
}

function tabButton(tab, group) {
  const selected = tab.domain === selectedBlock;
  const button = h("button", {
    type: "button",
    class: "tab",
    role: "tab",
    id: `tab-${slug(tab.domain)}`,
    "aria-selected": String(selected),
    "aria-controls": "block-panel",
    tabindex: selected ? "0" : "-1",
  });
  button.append(h("span", { class: `tmark ${tab.state}`, "aria-hidden": "true" }));
  button.append(h("span", { class: "tlabel", text: tab.domain }));
  button.append(h("span", { class: "ttally", text: `${tab.accepted}/${tab.total}` }));
  if (tab.yours) {
    button.append(
      h("span", {
        class: "tdot",
        title: `${tab.yours} cose aspettano te in questo blocco`,
        text: String(tab.yours),
      })
    );
  }
  button.addEventListener("click", () => {
    selectedBlock = tab.domain;
    renderBlocks();
  });
  button.addEventListener("keydown", (event) => moveTab(event, tab.domain, group));
  return button;
}

function moveTab(event, domain, group) {
  const passi = { ArrowRight: 1, ArrowLeft: -1 };
  const index = group.findIndex((tab) => tab.domain === domain);
  let next = null;
  if (event.key in passi) next = (index + passi[event.key] + group.length) % group.length;
  else if (event.key === "Home") next = 0;
  else if (event.key === "End") next = group.length - 1;
  if (next === null) return;
  event.preventDefault();
  selectedBlock = group[next].domain;
  renderBlocks();
  const node = document.getElementById(`tab-${slug(selectedBlock)}`);
  if (node) node.focus();
}

function panelContent(tab) {
  const nodes = [];
  // Il «Cos'è» del BLOCCO: cosa materialmente raccoglie e quando si chiude.
  const cosaBlocco = bottoneCosa(`blocco ${tab.domain}`, () =>
    spiega(`Blocco ${tab.domain}`, [
      `Raccoglie le unità di <b>${tab.domain}</b>. Un blocco non si «esegue»: si chiude quando <b>tutte</b> le sue unità sono accettate.`,
      `Qui: <b>${tab.accepted} di ${tab.total}</b> unità accettate. Ogni unità ha un deliverable e criteri propri, e le sue quattro fasi (analisi, esecuzione, verifica, accettazione) vanno una alla volta.`,
      (tab.units || []).some((u) => (u.depends_on || []).length)
        ? "Alcune unità aspettano un'altra unità: l'attesa è dichiarata nei suoi prerequisiti, e finché non è accettata non si parte."
        : "Nessuna unità di questo blocco dichiara prerequisiti esterni: può procedere in parallelo con gli altri blocchi.",
    ])
  );
  nodes.push(
    h("div", { class: "phead" }, [
      h("span", { class: `chip stato ${tab.state}`, text: BLOCK_STATE[tab.state] }),
      h("span", {
        class: "pmeta",
        text: `${tab.accepted} di ${tab.total} unità accettate · ${tab.units.length} mostrate con il filtro corrente`,
      }),
      cosaBlocco,
    ])
  );
  if (tab.next) {
    const line = h("p", { class: "pnext" }, [h("b", { text: "Da farsi: " })]);
    line.append(document.createTextNode(tab.next));
    nodes.push(line);
  }
  const stalli = tab.units.filter(hasIssues);
  if (stalli.length) {
    const line = h("p", { class: "pnext" }, [h("b", { text: "Respinte in verifica: " })]);
    line.append(
      document.createTextNode(
        stalli
          .map((unit) => {
            const fasi = unit.phases.filter((p) => ["needs_changes", "failed"].includes(p.status));
            return `${fasi.map((p) => p.id).join(", ") || unit.id}`;
          })
          .join(" · ")
      )
    );
    nodes.push(line);
  }
  tab.units.forEach((unit) => nodes.push(unitRow(unit)));
  nodes.push(commitPanel(tab));
  return nodes;
}

/* I commit che toccano i path DICHIARATI dalle unità di questo blocco: il confronto è esatto,
   path per path, nessuna somiglianza. Se non ne tocca nessuno lo dice — «zero» qui è
   l'informazione, non l'assenza di informazione. */
function commitPanel(tab) {
  const holder = h("div", { class: "pcommits" });
  const facts = (timeline && timeline.commits) || null;
  if (!facts || !facts.available) {
    holder.append(
      h("p", { class: "pmeta" }, [
        h("b", { text: "Commit non leggibili: " }),
        document.createTextNode((facts && facts.reason) || "git non disponibile"),
      ])
    );
    return holder;
  }
  const intro = h("p", { class: "pmeta" }, [
    h("b", { text: `Commit che toccano questo blocco: ${tab.commits.length}. ` }),
  ]);
  intro.append(
    document.createTextNode(
      tab.commits.length
        ? `su ${tab.pathsDeclared} path dichiarati dalle sue unità`
        : `Nessuno degli ${facts.total} commit del repository tocca uno dei ${tab.pathsDeclared} path dichiarati dalle sue unità` +
            (facts.last
              ? `. L'ultimo commit è del ${String(facts.last.date).slice(0, 10)}, «${facts.last.subject}»`
              : "")
    )
  );
  holder.append(intro);
  if (tab.commits.length) {
    const list = h("ul", { class: "gcommits" });
    tab.commits.forEach((commit) => {
      const li = h("li", {});
      li.append(h("span", { class: "sha", text: commit.sha }));
      li.append(h("span", { class: "when", text: commit.day || "" }));
      li.append(document.createTextNode(`${commit.subject} — unità: ${commit.units.join(", ")}`));
      list.append(li);
    });
    holder.append(list);
  }
  return holder;
}

function unitRow(unit) {
  const stalled = unit.phases.filter((p) => ["needs_changes", "failed"].includes(p.status));
  return h("div", { class: `unit${unit.accepted ? " accepted" : ""}` }, [
    h("div", {}, [
      h("div", { class: "name" }, [
        document.createTextNode(`${unit.id} — ${unit.title || ""}`),
        bottoneCosa(`unità ${unit.id}`, () => spiegaUnita(unit)),
      ]),
      h("div", {
        class: "id",
        text: [
          (unit.requirements || []).join(", ") || "nessun requisito mappato",
          (unit.depends_on || []).length ? `dipende da ${unit.depends_on.join(", ")}` : null,
          unit.blocked
            ? `blocca ${unit.blocked} ${unit.blocked === 1 ? "unità aperta" : "unità aperte"}` +
              (unit.waiting_total > unit.blocked
                ? ` (su ${unit.waiting_total} che la dichiarano a monte)`
                : "")
            : null,
        ]
          .filter(Boolean)
          .join(" · "),
      }),
      unit.deliverable ? h("p", { class: "deliverable", text: unit.deliverable }) : null,
      stalled.length
        ? h(
            "div",
            { class: "intervene" },
            stalled.map((phase) => {
              const message = h("span", { class: "msg", role: "status", "aria-live": "polite" });
              // Se l'ordine c'e' gia', il pulsante non chiede di depositarlo di nuovo: prenota la
              // fase e riusa quell'ordine. Prima offriva un rilancio che il server rifiutava, e la
              // pagina rispondeva «Non depositato» senza dire cosa fare.
              const stato = phaseState(phase.id);
              const rilascio = stato.claim
                ? activationButton(phase.id, "release", "Rilascia la prenotazione", message, false)
                : stato.orders.length
                  ? activationButton(phase.id, "activate", "Prenota la fase", message, false)
                  : h("button", {
                      type: "button",
                      class: phase.while_unit_accepted ? "linkish" : "ghost",
                      text: phase.while_unit_accepted
                        ? "Prepara comunque il rilancio"
                        : "Prepara il rilancio",
                      onclick: () => draft(phase, rilascio, message),
                    });
              const acceptance = unit.phases.find(
                (p) => p.id === phase.while_unit_accepted
              );
              const actions = phase.while_unit_accepted
                ? [
                    h("button", {
                      type: "button",
                      class: "ghost",
                      text: `Leggi la nota di accettazione (${phase.while_unit_accepted})`,
                      onclick: () =>
                        openReportPath(
                          `${phase.while_unit_accepted} — nota di accettazione`,
                          acceptance ? acceptance.report : ""
                        ),
                    }),
                    rilascio,
                  ]
                : [rilascio];
              return h("div", { class: "stall" }, [
                h("p", { class: "why" }, [
                  h("b", {
                    text: `${phase.id} respinta in verifica${
                      phase.report_age ? ` (report di ${phase.report_age})` : ""
                    }: `,
                  }),
                  document.createTextNode(phase.why_stalled || "apri il report per i finding."),
                ]),
                phase.while_unit_accepted
                  ? h("p", { class: "incoherent" }, [
                      document.createTextNode(
                        `Voce incoerente nel registro: l'unità risulta già accettata da ${phase.while_unit_accepted}, quindi questa non è una fase aperta. Guarda la nota di accettazione prima di rilanciare qualcosa.`
                      ),
                    ])
                  : null,
                stato.claim
                  ? h("p", { class: "why" }, [
                      h("b", { text: "Prenotata, in attesa di un esecutore: " }),
                      document.createTextNode(
                        `ordine ${stato.orders[stato.orders.length - 1] || "—"}${
                          stato.claim.since ? ` · dal ${stato.claim.since}` : ""
                        }. Nessuno la sta eseguendo: chi la prende la porta a «taken» col proprio nome.`
                      ),
                    ])
                  : stato.orders.length
                    ? h("p", { class: "why" }, [
                        h("b", { text: "Ordine gia' depositato: " }),
                        document.createTextNode(
                          `${stato.orders[stato.orders.length - 1]} — «Prenota la fase» la riserva e riusa questo ordine, senza depositarne un secondo.`
                        ),
                      ])
                    : null,
                h("div", { class: "row" }, [...actions, message]),
              ]);
            })
          )
        : null,
    ]),
    h(
      "div",
      { class: "phases" },
      unit.phases.map((fase) =>
        cellaFase(fase)
      )
    ),
  ]);
}

/* Cosa consiste il lavoro di un'unità: la usano il «Cos'è» del Percorso e l'indice a destra. */
function spiegaUnita(unit) {
  spiega(`Unità ${unit.id} — ${unit.title || ""}`, [
    unit.deliverable
      ? `Il risultato atteso: <b>${unit.deliverable}</b>.`
      : "Il registro non dichiara un risultato atteso per questa unità: sta nei criteri.",
    "Le sue quattro fasi vanno <b>una alla volta</b>: l'analisi dichiara perimetro e casi, l'esecuzione scrive i byte, la verifica misura, l'accettazione giudica e chiude.",
    (unit.depends_on || []).length
      ? `Aspetta: <b>${(unit.depends_on || []).join(", ")}</b>. Finché quelle unità non sono accettate, questa non parte.`
      : "Nessun prerequisito esterno dichiarato: può procedere in parallelo.",
    ...unit.phases
      .filter((f) => f.status !== "accepted")
      .slice(0, 1)
      .map((f) => `Adesso il prossimo atto è <b>${f.id}</b> (${f.status}).`),
  ]);
}

/* Una fase, sempre la stessa forma: la usano il percorso e la linea del tempo. */
function phaseButton(phase) {
  // Se il registro e' in ritardo ma il file di consegna c'e', la pagina mostra QUELLO che ha
  // misurato: il file. Mai un indice vecchio al posto del fatto (2026-10-16: cinque fasi
  // consegnate su disco comparivano come `pending`, cioe' «da mandare» mentre il lavoro era fatto).
  const consegnata = phase.delivered && phase.status !== "accepted";
  const etichetta = consegnata
    ? `consegnata${phase.delivery_attempt ? ` (t${phase.delivery_attempt})` : ""}`
    : phase.status;
  const ritardo = phase.register_behind
    ? ` Il registro dice «${phase.status}${phase.attempt ? ` t${phase.attempt}` : ""}», il file dice t${phase.delivery_attempt}: indice in ritardo, non lavoro mancante.`
    : "";
  return h(
    "button",
    {
      type: "button",
      class: "phase",
      "data-status": consegnata ? "delivered" : phase.status,
      "data-report": phase.report || "",
      "data-delivered": phase.delivered ? "true" : "false",
      "aria-label": `${phase.id}, ${phase.kind || phase.title || ""}: ${etichetta}${
        phase.attempt ? `, tentativo ${phase.attempt}` : ""
      }. ${phase.report ? "Apri il report." : "Nessun report pubblicato."}${ritardo}`,
    },
    [
      h("span", { class: "dot", "aria-hidden": "true" }),
      h("span", { class: "step", text: phase.suffix }),
      document.createTextNode(etichetta),
      (phase.delivery_attempt || phase.attempt)
        ? h("span", { class: "when", text: `t${phase.delivery_attempt || phase.attempt}` })
        : null,
      phase.register_behind ? h("span", { class: "when", text: "indice in ritardo" }) : null,
    ]
  );
}

/* La cella di una fase: il suo stato, il «Cos'è» e — se un atto esiste — i suoi «Esiti».
   Una sola forma ovunque compaia una fase, cosi' il pulsante non va cercato in posti diversi. */
function cellaFase(fase) {
  return h("span", { class: "phasecell" }, [
    phaseButton(fase),
    bottoneCosa(`fase ${fase.id}`, () => spiegaFase(fase)),
    fase.delivered ? bottoneEsiti(fase.id) : null,
  ]);
}

/* La fase prima di questa nella stessa unita': per una `R` e' la verifica, cioe' l'evidenza. */
function fasePrecedente(phaseId) {
  for (const blocco of (snapshot && snapshot.blocks) || []) {
    for (const unita of blocco.units || []) {
      const fasi = unita.phases || [];
      const indice = fasi.findIndex((fase) => fase.id === phaseId);
      if (indice > 0) return fasi[indice - 1];
    }
  }
  return null;
}

/* Lo stato di attivazione di una fase, dal carico dello stato: serve a non offrire un pulsante che
   verrebbe rifiutato. Tre casi, tre pulsanti diversi — e nessuno dei tre e' un vicolo cieco:
   gia' prenotata (si rilascia), respinta con ordine pronto (si prenota e si usa quello),
   respinta senza ordine (si prepara l'ordine). */
function phaseState(phaseId) {
  const tutte = [...((snapshot && snapshot.activatable) || []), ...((snapshot && snapshot.activated) || [])];
  const voce = tutte.find((v) => v.phase === phaseId);
  if (!voce) return { orders: [], claim: null };
  const ordini = voce.orders || (voce.order ? [voce.order] : []);
  const prenotata = ["pre_registered", "ready"].includes(voce.status);
  return { orders: ordini, claim: prenotata ? voce : null };
}

async function draft(phase, button, message) {
  button.disabled = true;
  message.className = "msg show pending";
  message.textContent = "preparo l'ordine…";
  try {
    const response = await fetch("/api/dispatch-draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: phase.id }),
    });
    const payload = await response.json();
    if (!response.ok) {
      // Tre modi di non riuscire, e ognuno dice cosa fare. Prima qui c'era «Non depositato» e
      // basta: un vicolo cieco, e l'utente non poteva fare niente (segnalato il 2026-10-15).
      if (payload.code === "not_stalled") {
        message.className = "msg show err";
        message.textContent = `${payload.task_id} ora e' «${payload.current_status}» nel registro: non e' piu' una fase respinta, quindi non c'e' niente da rilanciare. Aggiorno la pagina.`;
        setTimeout(load, 1500);
        return;
      }
      if (/ordine aperto/i.test(payload.error || "")) {
        const file = (payload.error.match(/[\w.\-T]+-[\w.\-]+-relaunch\.yaml/) || [])[0] || "in dispatch-queue/";
        message.className = "msg show err";
        message.textContent = `L'ordine per ${phase.id} esiste GIA': ${file}. Un ordine per fase, finche' quello non e' chiuso — non ne deposito un secondo. Per farla partire adesso usa «Attiva» in «Cosa puoi attivare»: prenota la fase e riusa questo ordine.`;
        return;
      }
      throw new Error(payload.error || `errore ${response.status}`);
    }
    message.className = "msg show ok";
    message.textContent = `Ordine depositato in ${payload.file}: chi riprende la fase lo trova su disco, con l'esito che l'ha respinta e la revisione congelata.`;
  } catch (error) {
    message.className = "msg show err";
    message.textContent = `Non depositato: ${error.message}. Se il problema resta, la fase si puo' attivare da «Cosa puoi attivare» qui in alto.`;
  } finally {
    button.disabled = false;
  }
}

/* ------------------------------------------------------------------ report */
async function openReportPath(label, path) {
  if (!path) return;
  const dialog = $("#report-dialog");
  $("#report-title").textContent = label;
  $("#report-body").textContent = "caricamento…";
  if (!dialog.open) dialog.showModal();
  const response = await fetch(`/file?path=${encodeURIComponent(path)}`);
  $("#report-body").textContent = response.ok ? await response.text() : "report non leggibile.";
}

function openReport(node) {
  return openReportPath(node.getAttribute("aria-label").split(".")[0], node.dataset.report);
}

document.addEventListener("click", (event) => {
  const phase = event.target.closest(".phase");
  if (phase) openReport(phase);
});

/* Un link «per te» porta a una domanda o a un prompt: il salto lo fa il browser, il FUOCO no.
   Senza questo, dopo il clic la tastiera riparte da capo pagina e chi non usa il mouse non sa
   dove e' atterrato. Il bersaglio diventa focalizzabile solo per il tempo del salto. */
document.addEventListener("click", (event) => {
  const link = event.target.closest("a.dlink");
  if (!link) return;
  const target = document.querySelector(link.getAttribute("href") || "");
  if (!target) return;
  target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
});

document.querySelectorAll('input[name="filter"]').forEach((input) => {
  input.addEventListener("change", () => {
    filter = input.value;
    renderBlocks();
    renderGantt();
  });
});

document.querySelectorAll('input[name="testimone"]').forEach((input) => {
  input.addEventListener("change", () => {
    filtroTestimone = input.value;
    renderTestimone(snapshot || {});
  });
});

const campoCerca = $("#testimone-cerca");
if (campoCerca) {
  campoCerca.addEventListener("input", () => {
    cercaTestimone = campoCerca.value;
    renderTestimone(snapshot || {});
  });
}

const nuovoRegistro = $("#nuovo-registro");
if (nuovoRegistro) nuovoRegistro.addEventListener("click", load);

/* La casella del logo: il file in review/brand/ vince, poi il simbolo ufficiale, poi il
   monogramma. Il fallback non e' un errore da nascondere: e' uno stato della casella. */
function initLogo() {
  const slot = $("#logo");
  if (!slot) return;
  const marks = [...slot.querySelectorAll("img")];
  let caduti = 0;
  marks.forEach((mark) => {
    // Le immagini possono essere GIA' caricate quando questo codice gira (succede con la cache
    // calda): in quel caso l'evento `load` non arriva piu' e il marchio resterebbe monogramma.
    // Misurato il 2026-10-15: primo caricamento col gufo, secondo col monogramma.
    if (mark.complete && mark.naturalWidth > 0) {
      slot.classList.add("has-logo");
      return;
    }
    mark.addEventListener("load", () => slot.classList.add("has-logo"));
    mark.addEventListener("error", () => {
      caduti += 1;
      if (caduti === marks.length) slot.classList.remove("has-logo");
    });
  });
}

/* L'header resta appiccicato: la sua altezza cambia con la larghezza, quindi si MISURA invece di
   indovinarla, e i salti usano quella misura per non finire sotto la barra. */
function initHeaderHeight() {
  const header = document.querySelector(".top");
  if (!header) return;
  const misura = () =>
    document.documentElement.style.setProperty("--top-h", `${Math.round(header.offsetHeight)}px`);
  misura();
  if (window.ResizeObserver) new ResizeObserver(misura).observe(header);
  window.addEventListener("resize", misura);
}

/* ---------------------------------------------------------------- il glossario e «Cos'è» */
/* Le parole di questo progetto non si indovinano: presa, ordine, riserva, «non rieseguito». Finora
   stavano in un documento; qui stanno accanto alla pagina, e ogni blocco/unità/fase ha il suo
   «Cos'è» che dice cosa si fa MATERIALMENTE. */
const SPIEGAZIONI_FASE = {
  analisi: [
    "Legge il problema e decide cosa deve esistere: dichiara il <b>perimetro</b> (i path che l'esecuzione toccherà), deriva i <b>casi di prova PRIMA</b> di vedere l'esecuzione, e scrive le decisioni con il loro costo.",
    "Consegna: il report dell'atto, il puntatore e il <b>next</b> (cosa resta da fare). Non scrive prodotto.",
  ],
  esecuzione: [
    "Scrive i <b>byte del prodotto</b>, solo nei path dichiarati dal design. Niente lavoro che i criteri non chiedono.",
    "Consegna: report + puntatore + next. Non dichiara sé stessa accettata.",
  ],
  "verifica indipendente": [
    "Esegue i casi derivati dal design sui <b>byte vivi</b>: una corsa autorevole, impronte prima e dopo, e dichiara cosa NON ha coperto.",
    "È l'unica fase che <b>misura</b>. Non corregge il prodotto: il rosso torna a chi ha scritto.",
  ],
  accettazione: [
    "Legge i criteri e i byte, e <b>giudica</b>: accettato, accettato con limiti, respinto. Dichiara i residui e chi li deve.",
    "Non riesegue le batterie: la misura è della verifica. La firma è di chi <b>non ha eseguito</b> quei byte.",
  ],
};

const GLOSSARIO = [
  ["Presa", "La dichiarazione che una corsia sta lavorando su una fase: compare nel registro con nome e ora. Finché è viva, nessun altro deve toccare quei byte."],
  ["Ordine", "Il file in `dispatch-queue/` che dice cosa fare e con quale prompt, con le impronte della revisione al momento dell'attivazione. Non avvia nessuno: è una promessa in attesa di un esecutore."],
  ["Riservata", "Una fase con un ordine depositato e <b>nessun titolare</b>. Non è «in corso»: nessuno ci sta lavorando. Si sblocca dando il prompt a una corsia, o annullando la riserva."],
  ["In corso", "Una fase con una <b>presa viva</b>: qualcuno l'ha dichiarata sua. La pagina mostra da quante ore, e segnala le prese che sembrano morte."],
  ["Rilascio", "La chiusura della presa, alla fine del lavoro. Senza, la fase resta «in corso» anche se il report è pubblicato."],
  ["A · E · T · R", "Le quattro fasi di un'unità, <b>in quest'ordine</b>: analisi, esecuzione, verifica indipendente, accettazione. Una alla volta: ognuna misura l'output della precedente."],
  ["needs_changes", "Verdetto di una verifica o di un'accettazione che respinge: il lavoro torna a chi esegue, con i finding misurati."],
  ["Consegnata", "Il report esiste (verdetto positivo) ma il registro non l'ha ancora accettata. Il passo dopo è l'accettazione, non un altro prompt."],
  ["Non rieseguito", "Cosa l'atto NON ha rifatto, dichiarato invece di lasciarlo intendere. Per un'accettazione significa: «non ho rimisurato; ho letto le prove della verifica». Non significa «non ho guardato»."],
  ["Accettazione (R)", "L'atto che chiude l'unità: si leggono criteri e byte, si giudica, si dichiarano limiti e residui. La firma deve essere di chi non ha eseguito quei byte."],
  ["Coda dei registri", "Le richieste degli agenti non ancora applicate al registro. Se è piena, la pagina mostra uno stato vecchio: si applica col pulsante, che fa prima una copia."],
  ["Prompt consegnato", "La traccia che un prompt è stato copiato e dato a una chat. Se dopo non compare una presa, il registro non sa che qualcuno ci sta lavorando."],
  ["Testimone", "Il `next` del report: cosa resta da fare dopo, scritto da chi ha finito. È l'unico canale per la direzione; una chat non è un archivio."],
];

function spiega(titolo, paragrafi) {
  const dialog = $("#spiega-dialog");
  $("#spiega-title").textContent = titolo;
  $("#spiega-body").replaceChildren(
    ...[].concat(paragrafi).map((paragrafo) =>
      typeof paragrafo === "string"
        ? h("p", { html: paragrafo })
        : paragrafo
    )
  );
  if (!dialog.open) dialog.showModal();
}

function bottoneCosa(etichetta, apri) {
  return h("button", {
    type: "button",
    class: "cosa",
    text: "Cos'è",
    title: etichetta,
    onclick: apri,
  });
}

/* «Esiti»: i punti di un atto — criteri, casi, finding, limiti — letti dal report e messi in fila.
   Serve prima di firmare: il verdetto da solo dice «pass», non dice cosa e' rimasto scoperto. */
const ETICHETTE_ESITO = {
  pass: "ok",
  covered: "coperto",
  covered_with_declared_residual: "coperto con residuo",
  pass_with_declared_residual: "ok con residuo",
  pass_with_declared_residuals: "ok con residuo",
  not_covered: "non coperto",
  not_measured: "non misurato",
  declared_divergence: "divergenza dichiarata",
  needs_changes: "da rifare",
  blocked_verification: "bloccato",
  missing: "manca",
  satisfied_on_current_bytes: "soddisfatto",
  ready_for_handoff: "pronto per l'atto successivo",
  ready_for_execution: "pronto per l'esecuzione",
  ready_for_independent_verification: "pronto per la verifica",
  pass_with_declared_limits: "ok con limiti",
  accept_unit: "accettato",
  accepted: "accettato",
};

function tonoEsito(esito) {
  const valore = String(esito || "").toLowerCase();
  if (!valore) return "";
  if (/fail|needs_changes|blocked|blocking|refused/.test(valore)) return "bad";
  if (/not_covered|not_measured|divergen|partial|missing/.test(valore)) return "warn";
  if (/residu|limit|declared/.test(valore)) return "warn";
  if (/pass|covered|accept|done|ok|ready_for|satisfied/.test(valore)) return "ok";
  return "";
}

function etichettaEsito(esito) {
  const valore = String(esito || "");
  const noto = ETICHETTE_ESITO[valore.toLowerCase()];
  if (noto) return noto;
  const pulito = valore.replace(/_/g, " ");
  return pulito.length > 34 ? `${pulito.slice(0, 34).replace(/\s+\S*$/, "")}…` : pulito || "—";
}

function apriEsiti(dati) {
  const punti = (dati.sezioni || []).flatMap((sezione) => sezione.punti || []);
  const daGuardare = punti.filter((punto) => tonoEsito(punto.esito) !== "ok" && punto.esito).length;
  const nodi = [
    h("p", { class: "esiti-sommario" }, [
      h("span", {
        class: `esiti-esito ${tonoEsito(dati.verdict)}`,
        text: etichettaEsito(dati.verdict) || "senza verdetto",
      }),
      document.createTextNode(
        punti.length
          ? ` ${punti.length} punti${daGuardare ? ` · ${daGuardare} da guardare` : " · tutti ok"}${
              dati.attempt ? ` · tentativo ${dati.attempt}` : ""
            }`
          : " nessun punto leggibile nel report"
      ),
    ]),
  ];
  for (const sezione of dati.sezioni || []) {
    nodi.push(h("h4", { class: "esiti-titolo", text: sezione.titolo }));
    nodi.push(
      h(
        "ul",
        { class: "esiti-lista" },
        (sezione.punti || []).map((punto) =>
          h("li", {}, [
            punto.id ? h("code", { class: "esiti-id", text: punto.id }) : null,
            h("span", { class: "esiti-testo", text: punto.testo || "" }),
            punto.esito
              ? h("span", {
                  class: `esiti-esito ${tonoEsito(punto.esito)}`,
                  text: etichettaEsito(punto.esito),
                })
              : null,
          ])
        )
      )
    );
  }
  if (!punti.length) {
    nodi.push(
      h("p", {
        text: "Il report non ha liste di punti leggibili (criteri, casi, finding, limiti): aprilo intero prima di firmare.",
      })
    );
  }
  nodi.push(h("p", { class: "esiti-fonte", text: `Report: ${dati.report || "—"}` }));
  spiega(
    `Esiti di ${dati.phase || "questa fase"} — ${etichettaEsito(dati.verdict) || "senza verdetto"}`,
    nodi
  );
}

function bottoneEsiti(fase, etichetta) {
  const bottone = h("button", {
    type: "button",
    class: "cosa",
    text: etichetta || "Esiti",
    title: `gli esiti in punti di ${fase}: criteri, casi, finding e limiti`,
  });
  bottone.addEventListener("click", async () => {
    bottone.disabled = true;
    try {
      const risposta = await fetch(`/api/esiti?phase=${encodeURIComponent(fase)}`);
      const dati = await risposta.json();
      if (!risposta.ok) throw new Error(dati.error || `errore ${risposta.status}`);
      apriEsiti(dati);
    } catch (errore) {
      spiega(`Esiti di ${fase}`, [`Non riesco a leggere il report: ${errore.message}.`]);
    } finally {
      bottone.disabled = false;
    }
  });
  return bottone;
}

function renderGlossario() {
  const box = $("#glossario-lista");
  if (!box) return;
  box.replaceChildren(
    ...GLOSSARIO.map(([voce, testo]) =>
      h("details", {}, [
        h("summary", { text: voce }),
        h("p", { html: testo }),
      ])
    )
  );
  const chiudi = $("#spiega-chiudi");
  if (chiudi) chiudi.addEventListener("click", () => $("#spiega-dialog").close());
  const dialog = $("#spiega-dialog");
  if (dialog) {
    dialog.addEventListener("click", (evento) => {
      if (evento.target === dialog) dialog.close();
    });
  }
}

/* La pagina «Recap»: lo stesso elenco del dialogo, ma leggibile e ricaricabile. */
let recapPayload = null;

async function promptPerVoce(voce) {
  const titolo = voce.titolo || "";
  const codice = (titolo.match(/^([A-Z][A-Z0-9-]{2,})\b/) || [])[1];
  if (codice && !titolo.startsWith("Obbligo ")) {
    try {
      const payload = await chiediPrompt(codice);
      return payload.text || "";
    } catch (error) {
      // Un codice che non è una fase (o un registro momentaneamente illeggibile) non deve
      // lasciare il pulsante muto: si usa l'istruzione mirata costruita qui sotto.
    }
  }
  return [
    `Lavora su: ${titolo}.`,
    voce.badge ? `Priorità: ${voce.badge}.` : "",
    voce.riassunto ? `Problema: ${voce.riassunto}` : "",
    voce.stato ? `Stato: ${voce.stato}` : "",
    voce.dettaglio ? `Dettaglio: ${voce.dettaglio}` : "",
    voce.fonte ? `Fonte: ${voce.fonte}` : "",
    "Leggi gli esiti citati e verifica se la voce è ancora aperta.",
    "Se è chiusa, deposita l'atto di chiusura con l'evidenza esatta (file, attempt, comando, esito).",
    "Se è aperta, esegui la prossima azione e dichiara cosa hai misurato. Non inventare voci o esiti.",
  ].filter(Boolean).join("\n") + "\n";
}

function renderRecapPage(payload) {
  const box = $("#recap-page");
  if (!box) return;
  const voci = Object.values(payload.counts || {}).reduce(
    (totale, numero) => totale + Number(numero || 0),
    0
  );
  const count = $("#recap-count");
  if (count) {
    const etichette = {
      bloccanti: "bloccano la chiusura",
      altri_aperti: "aperti non bloccanti",
      in_corso: "in corso",
      attesa_te: "aspettano te",
      amministrazione: "amministrazione",
      da_fare: "da fare",
      esiti: "esiti",
    };
    const parti = Object.entries(payload.counts || {})
      .filter(([, numero]) => Number(numero) > 0)
      .map(([chiave, numero]) => `${numero} ${etichette[chiave] || chiave}`);
    count.textContent = parti.length ? parti.join(" · ") : `${voci} voci`;
  }
  const generated = $("#generated");
  if (generated) {
    generated.textContent = `recap del ${payload.generated || "adesso"} · registri ed esiti del progetto`;
  }
  const parti = [];
  if (payload.complete) {
    parti.push(h("p", { class: "hint" }, "Nessuna voce aperta: i registri e gli esiti non mostrano sospesi."));
  }
  (payload.groups || []).forEach((gruppo) => {
    const numero = (gruppo.voci || []).length + Number(gruppo.tagliate || 0);
    parti.push(h("h3", { class: "recap-gruppo", text: `${gruppo.etichetta} (${numero})` }));
    const lista = h("div", { class: "recap-lista" });
    (gruppo.voci || []).forEach((voce) => {
      const azioni = h("div", { class: "recap-azioni" });
      const copia = h("button", {
        type: "button",
        class: "ghost",
        text: "Copia prompt",
        title: "copia un'istruzione mirata per questa voce",
      });
      copia.addEventListener("click", async () => {
        const prompt = await promptPerVoce(voce);
        const esito = await copiaTesto(prompt);
        const messaggio = $("#recap-esito");
        if (messaggio) {
          messaggio.className = `msg show ${esito.ok ? "ok" : "err"}`;
          messaggio.textContent = esito.ok
            ? "Prompt della voce copiato."
            : "Copia non riuscita: apri «Dettagli» e seleziona il testo.";
        }
      });
      azioni.append(copia);
      if (voce.fonte === "registro") {
        azioni.append(h("a", {
          class: "ghost",
          href: "/file?path=state.yaml",
          target: "_blank",
          rel: "noopener",
          text: "Apri il registro",
        }));
      }
      if (voce.fonte === "inbox" && voce.ref) {
        const archivia = h("button", {
          type: "button",
          class: "ghost",
          text: "Archivia",
          title: "chiude la ricevuta della posta senza toccare il testo del messaggio",
        });
        archivia.addEventListener("click", async () => {
          const nota = window.prompt(
            "Nota di chiusura",
            "Messaggio di direzione: nessuna azione richiesta."
          );
          if (nota === null) return;
          archivia.disabled = true;
          try {
            const response = await fetch("/api/inbox/close", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ ricevuta: voce.ref, nota }),
            });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
            const messaggio = $("#recap-esito");
            if (messaggio) {
              messaggio.className = "msg show ok";
              messaggio.textContent = "Ricevuta archiviata.";
            }
            await loadRecapPage();
          } catch (error) {
            const messaggio = $("#recap-esito");
            if (messaggio) {
              messaggio.className = "msg show err";
              messaggio.textContent = `Archiviazione non riuscita: ${error.message}`;
            }
          } finally {
            archivia.disabled = false;
          }
        });
        azioni.append(archivia);
      }
      if (voce.fonte && /^(reports|docs|inbox|pending-transitions)\//.test(voce.fonte)) {
        azioni.append(h("a", {
          class: "ghost",
          href: `/file?path=${encodeURIComponent(voce.fonte)}`,
          target: "_blank",
          rel: "noopener",
          text: "Apri la fonte",
        }));
      }
      const dettaglio = voce.dettaglio
        ? voce.dettaglio.length > 180
          ? h("details", { class: "recap-dettagli" }, [
              h("summary", { text: "Dettagli" }),
              h("p", { text: voce.dettaglio }),
            ])
          : h("p", { text: voce.dettaglio })
        : null;
      lista.append(
        h("article", { class: "recap-voce" }, [
          voce.badge ? h("span", { class: "recap-badge", text: voce.badge }) : null,
          h("b", { text: voce.titolo }),
          voce.riassunto
            ? h("p", { class: "recap-riassunto", text: voce.riassunto })
            : null,
          voce.stato && voce.stato !== voce.riassunto
            && /(APERTO|MANCA|RESTA|FIX|ACCETTATO|CHIUS|DOVUT)/i.test(voce.stato)
            ? h("p", { class: "recap-stato", text: `Stato: ${voce.stato}` })
            : null,
          dettaglio,
          voce.fonte ? h("small", { text: `Fonte: ${voce.fonte}` }) : null,
          azioni,
        ].filter(Boolean))
      );
    });
    if (gruppo.tagliate) {
      lista.append(h("p", { class: "hint", text: `… e altre ${gruppo.tagliate} voci non elencate.` }));
    }
    parti.push(lista);
  });
  box.setAttribute("aria-busy", "false");
  box.replaceChildren(...parti);
}

async function loadRecapPage() {
  const box = $("#recap-page");
  if (!box) return;
  box.setAttribute("aria-busy", "true");
  box.replaceChildren(h("p", { class: "hint", text: "Leggo i registri e gli esiti…" }));
  try {
    const response = await fetch("/api/recap");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    recapPayload = payload;
    renderRecapPage(payload);
  } catch (error) {
    box.setAttribute("aria-busy", "false");
    box.replaceChildren(h("p", { class: "hint", text: `Recap non disponibile: ${error.message}` }));
  }
}

function initRecapPage() {
  const copia = $("#recap-copia");
  const ricarica = $("#recap-ricarica");
  if (copia) {
    copia.addEventListener("click", async () => {
      if (!recapPayload) await loadRecapPage();
      if (!recapPayload) return;
      const esito = await copiaTesto(recapPayload.prompt || "");
      const messaggio = $("#recap-esito");
      if (messaggio) {
        messaggio.className = `msg show ${esito.ok ? "ok" : "err"}`;
        messaggio.textContent = esito.ok
          ? "Prompt copiato: incollalo come primo messaggio di una chat nuova."
          : "Copia non riuscita: apri il recap dal pulsante in alto e seleziona il testo.";
      }
    });
  }
  if (ricarica) ricarica.addEventListener("click", () => loadRecapPage());
}

/* La rifinitura finale: un'insegna in «Adesso», non una pagina separata. */
function renderFinishing(data) {
  const banner = $("#finishing-banner");
  if (!banner) return;
  const s = data.summary || {};
  const gate = Number(s.open_gate_obligations || 0);
  const altri = Math.max(0, Number(s.open_obligations || 0) - gate);
  const ratifiche = Number(s.open_independence_debts || 0);
  const posta = Number((data.inbox || {}).non_lavorate || 0);
  const rifiniture = gate + altri + ratifiche + posta;
  const concluso = Number(s.open_units || 0) === 0;
  const items = data.obligations || [];
  const prese = items.filter((voce) => voce.taken).length;
  const consegnati = items.filter((voce) => voce.dispatched).length;
  const finiti = items.filter((voce) => voce.report_closed).length;
  banner.hidden = !concluso;
  const headerButton = $("#recap-sospesi");
  if (headerButton) headerButton.hidden = !concluso;
  if (!concluso) return;
  const kicker = banner.querySelector(".finishing-kicker");
  const title = $("#finishing-title");
  const summary = $("#finishing-summary");
  if (kicker) kicker.textContent = rifiniture ? "Rifinitura finale" : "Lavoro concluso";
  if (title) title.textContent = rifiniture ? "Lavoro principale concluso" : "Lavoro concluso";
  if (summary) {
    const parti = [];
    if (gate) {
      parti.push(`${gate} ${gate === 1 ? "punto blocca" : "punti bloccano"} la chiusura`);
    }
    if (altri) {
      parti.push(`${altri} ${altri === 1 ? "punto aperto" : "punti aperti"} non bloccanti`);
    }
    if (ratifiche) {
      parti.push(`${ratifiche} ${ratifiche === 1 ? "ratifica mancante" : "ratifiche mancanti"}`);
    }
    if (posta) {
      parti.push(`${posta} ${posta === 1 ? "ricevuta" : "ricevute"} da archiviare`);
    }
    const presa = items.length
      ? ` Prese in carico: ${prese} di ${items.length}; prompt consegnati: ${consegnati} di ${items.length}${
          finiti ? `; finiti da registrare: ${finiti} di ${items.length}` : ""
        }.`
      : "";
    summary.textContent = (parti.length
      ? `Tutte le ${s.units || 0} unità e le fasi sono accettate. Restano ${parti.join(", ")}.`
      : `Tutte le ${s.units || 0} unità e le fasi sono accettate; non risultano rifiniture aperte.`) + presa;
  }
}

function initFinishing() {
  const prompt = $("#finishing-prompt");
  const scroll = $("#finishing-scroll");
  if (prompt) {
    prompt.addEventListener("click", async () => {
      prompt.disabled = true;
      const esito = $("#finishing-esito");
      if (esito) {
        esito.className = "msg show pending";
        esito.textContent = "preparo…";
      }
      try {
        const response = await fetch("/api/state");
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        const rifiniture = payload.obligations || [];
        const testo = [
          "Rifiniture finali del workspace. Ogni voce ha la sua fase A/E/T/R e il suo prossimo atto.",
          ...rifiniture.map(
            (voce) => {
              const testoVoce =
                strictMode || voce.strict_required
                  ? voce.next_prompt
                  : voce.vibe_prompt || voce.next_prompt;
              return `## ${voce.id}\n${testoVoce || ""}`.trim();
            }
          ),
        ].join("\n\n") + "\n";
        const copiato = await copiaTesto(testo);
        if (esito) {
          esito.className = `msg show ${copiato.ok ? "ok" : "err"}`;
          esito.textContent = copiato.ok
            ? "Prompt delle rifiniture copiato."
            : "Copia non riuscita: apri il testo e selezionalo.";
        }
        if (!copiato.ok) {
          apriTesto("Rifiniture finali — prompt", testo, {
            copia: true,
            seleziona: true,
            file: "rifiniture-finali.md",
          });
        } else {
          const daSegnare = ((snapshot && snapshot.obligations) || []).filter(
            (voce) => voce.gate && !voce.taken
          );
          await Promise.all(daSegnare.map((voce) => annotaPromptConsegnato(voce.id)));
          await load();
        }
      } catch (error) {
        if (esito) {
          esito.className = "msg show err";
          esito.textContent = `Prompt non disponibile: ${error.message}`;
        }
      } finally {
        prompt.disabled = false;
      }
    });
  }
  if (scroll) {
    scroll.addEventListener("click", () => {
      $("#rifiniture")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }
  const markSent = $("#finishing-mark-sent");
  if (markSent) {
    markSent.addEventListener("click", async () => {
      const daSegnare = ((snapshot && snapshot.obligations) || []).filter(
        (voce) => !voce.taken && !voce.dispatched
      );
      const esito = $("#finishing-esito");
      if (!daSegnare.length) {
        if (esito) {
          esito.className = "msg show ok";
          esito.textContent = "Tutte le rifiniture risultano già consegnate o prese in carico.";
        }
        return;
      }
      markSent.disabled = true;
      try {
        await Promise.all(
          daSegnare.map((voce) =>
            annotaPromptConsegnato(voce.id, "segnato come consegnato")
          )
        );
        if (esito) {
          esito.className = "msg show ok";
          esito.textContent = `${daSegnare.length} rifiniture segnate come consegnate.`;
        }
        await load();
      } finally {
        markSent.disabled = false;
      }
    });
  }
}

/* «Rifiniture»: porta all'insegna in «Adesso»; non apre una pagina separata. */
function initRecap() {
  const button = $("#recap-sospesi");
  if (!button) return;
  button.addEventListener("click", () => {
    if (paginaCorrente() !== "adesso") {
      window.location.href = "/";
      return;
    }
    const banner = $("#finishing-banner");
    if (!banner || banner.hidden) return;
    banner.scrollIntoView({ behavior: "smooth", block: "start" });
    $("#finishing-title")?.focus({ preventScroll: true });
  });
}

/* Il tutorial: un solo pannello, con l'indice che porta alle sezioni. Si apre sopra la pagina e non
   la sostituisce, perche' le parole del tutorial servono mentre si guarda la pagina. */
function initTutorial() {
  const dialog = $("#tutorial-dialog");
  const apri = $("#tutorial");
  if (!dialog || !apri) return;
  apri.addEventListener("click", () => dialog.showModal());
  const chiudi = $("#tutorial-chiudi");
  if (chiudi) chiudi.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (evento) => {
    if (evento.target === dialog) dialog.close();
  });
  dialog.querySelectorAll('a[href^="#tut-"]').forEach((link) => {
    link.addEventListener("click", (evento) => {
      evento.preventDefault();
      const target = document.querySelector(link.getAttribute("href"));
      if (!target) return;
      const ridotto = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      target.scrollIntoView({ block: "start", behavior: ridotto ? "auto" : "smooth" });
    });
  });
}

/* L'INDICE DEL LAVORO, a destra: blocchi che si aprono sulle loro unità. Ogni unità dice in una riga
   di cosa consiste (il risultato atteso o il titolo) e a che punto è; aprendola si legge il mestiere
   delle sue fasi, i prerequisiti e il prossimo atto. È la mappa, simmetrica al vocabolario. */
function renderIndice(data) {
  const box = $("#indice-lista");
  if (!box) return;
  const blocchi = data.blocks || [];
  if (!blocchi.length) {
    box.replaceChildren(h("p", { class: "vuoto", text: "Nessun blocco nel registro." }));
    return;
  }
  box.replaceChildren(
    ...blocchi.map((blocco) => {
      const unita = blocco.units || [];
      const accettate = unita.filter((u) => u.accepted).length;
      return h("details", {}, [
        h("summary", {}, [
          h("span", { text: blocco.domain }),
          h("span", { class: "conteggio", text: `${accettate}/${unita.length} accettate` }),
        ]),
        h(
          "ul",
          {},
          unita.map((unita) => {
            const prossima = (unita.phases || []).find((f) => f.status !== "accepted");
            const stato = unita.accepted
              ? "accettata"
              : prossima
                ? `prossimo: ${prossima.id} · ${prossima.status}`
                : "senza fasi";
            return h("li", {}, [
              h(
                "button",
                {
                  type: "button",
                  class: "unita",
                  "data-fatto": unita.accepted ? "si" : "no",
                  title: "che cosa consiste questo lavoro",
                  onclick: () => spiegaUnita(unita),
                },
                [
                  h("b", { text: unita.id }),
                  document.createTextNode(` — ${unita.title || ""}`),
                  h("span", { class: "stato", text: stato }),
                ]
              ),
            ]);
          })
        ),
      ]);
    })
  );
}

/* Il «Cos'è» di una fase: la spiegazione del suo mestiere, più lo stato di QUESTA fase. */
function spiegaFase(phase) {
  const chiave = String(phase.kind || "").toLowerCase();
  const base = SPIEGAZIONI_FASE[chiave] || [
    "Questa fase non ha un mestiere dichiarato nel registro: leggi il titolo e i criteri dell'unità.",
  ];
  const stato = [
    `Stato: <b>${phase.status}</b>`,
    phase.delivered ? `consegna su disco: ${phase.delivery_path || "sì"}` : null,
    phase.register_behind ? "il registro è in ritardo rispetto al file" : null,
  ]
    .filter(Boolean)
    .join(" · ");
  spiega(`${phase.id} — ${phase.title || phase.kind || "fase"}`, [...base, stato]);
}

let worklogData = null;
const WORKLOG_KIND = {
  analysis: "Analisi",
  implementation: "Esecuzione",
  independent_verification: "Verifica",
  functional_acceptance: "Accettazione",
};
const WORKLOG_STATUS = {
  accepted: "accettata",
  pending: "da fare",
  ready: "pronta",
  taken: "in corso",
  running: "in corso",
  needs_changes: "respinta",
  failed: "fallita",
  blocked_dependency: "bloccata",
  blocked_verification: "bloccata",
  waiting_on_user: "in attesa",
};

function worklogStrip(stages, nextStage) {
  const strip = h("div", { class: "actstages" });
  ["A", "E", "T", "R"].forEach((chiave) => {
    strip.append(h("span", {
      class: `stage ${stages[chiave] || "missing"}`,
      text: chiave,
    }));
  });
  if (nextStage) {
    strip.append(h("span", { class: "stage-next", text: `Prossimo: ${nextStage}` }));
  }
  return strip;
}

function worklogMatches(testo, query) {
  return !query || String(testo || "").toLowerCase().includes(query);
}

function renderWorklogSummary() {
  const s = worklogData.summary || {};
  const box = $("#worklog-summary");
  if (box) {
    const stats = [
      [`${s.accepted_units}/${s.units}`, "Unità accettate"],
      [`${s.accepted_phases}/${s.phases}`, "Fasi accettate"],
      [s.reports, "Report"],
      [s.attempts, "Tentativi registrati"],
      [`${s.closed_refinements}/${s.refinements}`, "Rifiniture chiuse"],
      [s.first_published ? String(s.first_published).slice(0, 10) : "—", "Primo report"],
      [s.last_published ? String(s.last_published).slice(0, 10) : "—", "Ultimo report"],
    ];
    box.replaceChildren(
      ...stats.map(([valore, etichetta]) =>
        h("div", { class: "worklog-stat" }, [
          h("b", { text: String(valore) }),
          h("span", { text: etichetta }),
        ])
      )
    );
  }
  const count = $("#worklog-count");
  if (count) {
    count.textContent = `${s.accepted_units}/${s.units} unità · ${s.accepted_phases}/${s.phases} fasi`;
  }
}

function renderWorklog() {
  const box = $("#worklog");
  if (!box || !worklogData) return;
  const query = String($("#worklog-search")?.value || "").trim().toLowerCase();
  const dominio = String($("#worklog-domain")?.value || "");
  const mostraAperti = Boolean($("#worklog-open")?.checked);
  const parti = [];
  for (const blocco of worklogData.blocks || []) {
    if (dominio && blocco.domain !== dominio) continue;
    const unita = [];
    for (const unit of blocco.units || []) {
      const fasi = (unit.phases || []).filter((fase) => {
        if (!mostraAperti && fase.status !== "accepted") return false;
        return worklogMatches(
          [
            unit.id,
            unit.title,
            fase.id,
            fase.kind,
            fase.verdict,
            fase.author,
            fase.report,
          ].join(" "),
          query
        );
      });
      if (fasi.length) unita.push({ unit, fasi });
    }
    if (!unita.length) continue;
    parti.push(h("h3", { class: "worklog-block", text: blocco.domain }));
    for (const { unit, fasi } of unita) {
      const details = h("details", { class: "worklog-unit" });
      details.append(
        h("summary", {}, [
          h("b", { text: unit.id }),
          h("span", { text: ` — ${unit.title || ""}` }),
          h("span", {
            class: "count",
            text: `${fasi.length}/${(unit.phases || []).length} fasi`,
          }),
        ])
      );
      const table = h("table", {}, [
        h("thead", {}, [
          h("tr", {}, ["Fase", "Tipo", "Attempt", "Verdetto", "Autore", "Data", "Report"].map((testo) =>
            h("th", { text: testo })
          )),
        ]),
      ]);
      const corpo = h("tbody");
      for (const fase of fasi) {
        const link = fase.report
          ? h("a", {
              class: "worklog-report",
              href: `/file?path=${encodeURIComponent(fase.report)}`,
              target: "_blank",
              rel: "noopener",
              text: "Apri",
            })
          : document.createTextNode("—");
        corpo.append(
          h("tr", {}, [
            h("td", {}, [h("code", { text: fase.id })]),
            h("td", { text: WORKLOG_KIND[fase.kind] || fase.kind || "" }),
            h("td", { text: fase.attempt || fase.report_attempt || "" }),
            h("td", { text: fase.verdict || WORKLOG_STATUS[fase.status] || fase.status || "" }),
            h("td", { text: fase.author || "" }),
            h("td", { text: String(fase.published_at || "").slice(0, 16).replace("T", " ") }),
            h("td", {}, [link]),
          ])
        );
      }
      table.append(corpo);
      details.append(table);
      parti.push(details);
    }
  }
  if ((worklogData.refinements || []).length) {
    parti.push(h("h3", { class: "worklog-block", text: "Rifiniture" }));
    for (const voce of worklogData.refinements) {
      const card = h("article", { class: "worklog-refinement" });
      card.append(h("b", { text: `${voce.id}${voce.closed ? " · chiusa" : ""}` }));
      if (voce.title) card.append(h("p", { class: "hint", text: voce.title }));
      if ((voce.owners || []).length) {
        card.append(h("small", {
          text: `Unità proprietaria: ${voce.owners.join(", ")}`,
        }));
      }
      card.append(worklogStrip(voce.stages || {}, voce.next));
      if (voce.claim && voce.claim.taken_by) {
        card.append(
          h("small", {
            text: `Presa: ${voce.claim.taken_by} · ${voce.claim.task || ""} · ${voce.claim.status || ""}`,
          })
        );
      }
      if (voce.next_report) {
        card.append(
          h("a", {
            class: "worklog-report",
            href: `/file?path=${encodeURIComponent(voce.next_report)}`,
            target: "_blank",
            rel: "noopener",
            text: "Prossimo report",
          })
        );
      }
      card.append(
        h("button", {
          type: "button",
          class: "ghost",
          text: "Gestisci",
          onclick: () =>
            apriRifinitura({
              id: voce.id,
              title: voce.title,
              next_stage: voce.next,
              stages: voce.stages,
              last_claim_by: voce.claim?.taken_by,
              last_claim_task: voce.claim?.task,
              next_report: voce.next_report,
            }),
        })
      );
      parti.push(card);
    }
  }
  if (!parti.length) {
    parti.push(h("p", { class: "hint", text: "Nessun lavoro corrisponde ai filtri." }));
  }
  box.setAttribute("aria-busy", "false");
  box.replaceChildren(...parti);
}

async function loadWorklog() {
  const box = $("#worklog");
  if (!box) return;
  box.setAttribute("aria-busy", "true");
  box.replaceChildren(h("p", { class: "hint", text: "Leggo i registri…" }));
  try {
    const response = await fetch("/api/svolto");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    worklogData = payload;
    const generated = $("#generated");
    if (generated) {
      generated.textContent = `lavoro svolto del ${payload.generated} · dati letti dai registri`;
    }
    const select = $("#worklog-domain");
    if (select) {
      const corrente = select.value;
      select.replaceChildren(h("option", { value: "", text: "Tutti i blocchi" }));
      (payload.blocks || []).forEach((blocco) => {
        select.append(h("option", { value: blocco.domain, text: blocco.domain }));
      });
      select.value = corrente;
    }
    renderWorklogSummary();
    renderWorklog();
  } catch (error) {
    box.setAttribute("aria-busy", "false");
    box.replaceChildren(h("p", { class: "hint", text: `Lavoro svolto non disponibile: ${error.message}` }));
  }
}

function initWorklog() {
  $("#worklog-search")?.addEventListener("input", renderWorklog);
  $("#worklog-domain")?.addEventListener("change", renderWorklog);
  $("#worklog-open")?.addEventListener("change", renderWorklog);
  $("#worklog-expand")?.addEventListener("click", () => {
    document.querySelectorAll(".worklog-unit").forEach((node) => (node.open = true));
  });
  $("#worklog-collapse")?.addEventListener("click", () => {
    document.querySelectorAll(".worklog-unit").forEach((node) => (node.open = false));
  });
}

let refinementCorrente = null;

function refinementReload() {
  if (paginaCorrente() === "svolto") loadWorklog();
  else load();
}

function apriRifinitura(voce, { add = false } = {}) {
  const dialog = $("#refinement-dialog");
  if (!dialog) return;
  refinementCorrente = voce || null;
  $("#ref-action").value = add ? "add" : "update";
  $("#ref-obligation").value = voce?.id || "";
  $("#ref-title").value = voce?.title || "";
  const fase = voce?.next_stage || (add ? "A" : "");
  $("#ref-phase").value = ["A", "E", "T", "R"].includes(fase) ? fase : "";
  const statoFase = voce?.stages?.[fase];
  $("#ref-status").value =
    statoFase === "done" ? "accepted" : statoFase === "partial" ? "partial" : statoFase === "in_progress" ? "in_progress" : "";
  $("#ref-attempt").value = voce?.report_attempt || "";
  $("#ref-report").value = voce?.report_path || "";
  $("#ref-verdict").value = voce?.report_verdict || "";
  $("#ref-author").value = voce?.report_author || "";
  $("#ref-next").value = voce?.report_next || "";
  $("#ref-next-report").value = voce?.next_report || "";
  $("#ref-test-command").value = voce?.test?.command || "";
  $("#ref-test-exit").value = voce?.test?.exit || "";
  $("#ref-test-duration").value = voce?.test?.duration || "";
  $("#ref-branch").value = voce?.branch || "";
  $("#ref-worktree").value = voce?.worktree || "";
  $("#ref-strict").checked = Boolean(voce?.strict || voce?.strict_required);
  $("#ref-risk").value = (voce?.risk || []).join(", ");
  $("#ref-errors").value = Array.isArray(voce?.errors) ? voce.errors.join("; ") : "";
  $("#ref-claim-by").value = voce?.last_claim_by || "";
  $("#ref-claim-task").value = voce?.last_claim_task || "";
  $("#ref-esito").textContent = "";
  dialog.showModal();
  $("#ref-obligation").focus({ preventScroll: true });
}

async function inviaRifinitura(action) {
  const obligation = $("#ref-obligation").value.trim();
  const esito = $("#ref-esito");
  if (!obligation) {
    esito.className = "msg show err";
    esito.textContent = "serve l'obbligo";
    return;
  }
  const payload = {
    action,
    obligation,
    title: $("#ref-title").value.trim() || null,
    phase: $("#ref-phase").value || null,
    status: $("#ref-status").value || null,
    attempt: $("#ref-attempt").value || null,
    report: $("#ref-report").value.trim() || null,
    verdict: $("#ref-verdict").value.trim() || null,
    author: $("#ref-author").value.trim() || null,
    test_command: $("#ref-test-command").value.trim() || null,
    test_exit: $("#ref-test-exit").value.trim() || null,
    test_duration: $("#ref-test-duration").value.trim() || null,
    errors: $("#ref-errors").value.trim() || null,
    branch: $("#ref-branch").value.trim() || null,
    worktree: $("#ref-worktree").value.trim() || null,
    strict: $("#ref-strict").checked,
    risk: $("#ref-risk").value.trim() || null,
    claim_by: $("#ref-claim-by").value.trim() || null,
    claim_task: $("#ref-claim-task").value.trim() || null,
    next: $("#ref-next").value.trim() || null,
    next_report: $("#ref-next-report").value.trim() || null,
  };
  if (action === "claim" && !payload.claim_by) {
    esito.className = "msg show err";
    esito.textContent = "scrivi chi prende in carico";
    return;
  }
  const pulsante = $("#refinement-form button[type=submit]");
  if (pulsante) pulsante.disabled = true;
  try {
    const response = await fetch("/api/refinement", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const risposta = await response.json();
    if (!response.ok) throw new Error(risposta.error || `HTTP ${response.status}`);
    $("#refinement-dialog").close();
    refinementReload();
  } catch (error) {
    esito.className = "msg show err";
    esito.textContent = `Non salvato: ${error.message}`;
  } finally {
    if (pulsante) pulsante.disabled = false;
  }
}

function initRifinitura() {
  $("#refinement-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    inviaRifinitura($("#ref-action").value || "update");
  });
  $("#ref-claim")?.addEventListener("click", () => inviaRifinitura("claim"));
  $("#ref-release")?.addEventListener("click", () => inviaRifinitura("release"));
  $("#ref-add")?.addEventListener("click", () => {
    $("#ref-action").value = "add";
    $("#ref-obligation").value = "";
    $("#ref-title").value = "";
    $("#ref-phase").value = "A";
    $("#ref-status").value = "pending";
    $("#ref-test-command").value = "";
    $("#ref-test-exit").value = "";
    $("#ref-test-duration").value = "";
    $("#ref-branch").value = "";
    $("#ref-worktree").value = "";
    $("#ref-strict").checked = false;
    $("#ref-risk").value = "";
    $("#ref-errors").value = "";
    $("#ref-obligation").focus();
  });
}

initLogo();
initRecap();
initFinishing();
initWorklog();
initRifinitura();
renderGlossario();
initTutorial();
initHeaderHeight();
preparaScheda();
loadConfig();
if (paginaCorrente() === "svolto") {
  mostraPagina();
  loadWorklog();
} else {
  load();
}

/* Il registro viene letto a OGNI richiesta (il server lo rilegge quando cambia il tempo di
   modifica), ma questa pagina e' un'istantanea: senza ricaricarla, i numeri restano quelli del
   momento in cui l'hai aperta. Per questo si ricarica da sola — e non mentre stai scrivendo in un
   campo, ne' con un dialogo aperto, per non cancellarti quello che stai facendo. */
const INTERVALLO = 30000;
setInterval(() => {
  const campo = document.activeElement;
  const staScrivendo = campo && ["INPUT", "TEXTAREA"].includes(campo.tagName);
  // Nessun ricarico mentre un dialogo è aperto: né il report, né il tutorial, né una spiegazione.
  if (staScrivendo || document.querySelector("dialog[open]")) return;
  load();
}, INTERVALLO);

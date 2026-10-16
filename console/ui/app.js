/* Il coordinatore: la pagina che legge i registri di un workspace e mostra dove sta il lavoro.
   Sola lettura tranne il submit di una risposta, che passa dal server e quindi dal lock. */

const $ = (sel) => document.querySelector(sel);
/* Una fase e' aperta quando NON e' accettata. Elencare gli stati aperti uno per uno sembrava piu'
   preciso ed era piu' fragile: bastava che un progetto usasse `ready`, `blocked_dependency` o una
   parola sua — tutti stati legittimi del registro — e l'unita' spariva dalla vista «Aperte».
   L'unica cosa che il coordinatore deve sapere e' quale stato CHIUDE: `accepted`. */
const CLOSED_STATES = ["accepted"];
let snapshot = null;
let filter = "open";
let loadedAt = 0;
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
  render(snapshot);
}

function render(data) {
  const s = data.summary;
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
  box.replaceChildren(
    h(
      "ul",
      { class: "claims" },
      claims.map((claim) =>
        h("li", {}, [
          h("span", { class: "id" }, [
            document.createTextNode(claim.task_id || ""),
            claim.phase ? h("span", { class: "phase", text: ` · ${claim.phase}` }) : null,
          ]),
          h("span", { class: "who", title: claim.owner || "", text: claim.owner || "" }),
          h("span", { class: "when", text: claim.taken_at || "" }),
        ])
      )
    )
  );
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
    (data.owed || []).length +
    (data.activatable || []).filter(
      (voce) => !voce.altrove && !(voce.waiting_on || []).length
    ).length +
    (data.activated || []).filter((voce) => ["pre_registered", "ready"].includes(voce.status))
      .length;
  return {
    oggi: { numero: coda, tono: "bad", cosa: "da mandare" },
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
        await navigator.clipboard.writeText(testo || "");
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
function rigaConsegna(code) {
  const traccia = consegnaDiFase(code);
  if (!traccia) return null;
  const inCorso = ((snapshot && snapshot.claims) || []).some((voce) => voce.task_id === code);
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
  const aperte = (data.activatable || []).filter((voce) => !(voce.waiting_on || []).length);
  const attivate = (data.activated || []).filter((voce) =>
    ["pre_registered", "ready"].includes(voce.status)
  );

  // Da mandare: gli atti che il registro dichiara e che nessuno ha ancora preso ne' consegnato,
  // piu' le fasi libere. Un codice, una riga; se lo stesso codice arriva da due dichiarazioni vince
  // la piu' recente.
  const visti = new Set();
  const coda = [];
  (data.owed || []).forEach((voce) => {
    (voce.codes || []).forEach((codice) => {
      if (codice.live || codice.done || visti.has(codice.code)) return;
      visti.add(codice.code);
      coda.push({
        code: codice.code,
        status: codice.status,
        da: voce.from_phase,
        perche: voce.text,
        quando: voce.when,
        fase: null,
      });
    });
  });
  aperte.forEach((voce) => {
    if (visti.has(voce.phase)) return;
    visti.add(voce.phase);
    coda.push({ code: voce.phase, da: null, perche: "", quando: "", fase: voce });
  });

  const inCorso = (data.claims || []).filter((voce) => voce.status === "taken");
  count.textContent = [
    coda.length ? `${coda.length} da mandare` : "niente da mandare",
    attivate.length ? `${attivate.length} riservate` : null,
    inCorso.length ? `${inCorso.length} in corso` : null,
  ]
    .filter(Boolean)
    .join(" \u00b7 ");
  const suggerimento = $("#activation-hint");
  if (suggerimento) {
    suggerimento.replaceChildren(
      document.createTextNode(
        coda.length
          ? "Una riga, un'azione: premi il pulsante e incolla il prompt in una chat. Non avvia nessun agente \u2014 la presa la dichiara chi lo riceve."
          : "Niente da mandare: il lavoro e' in mano a qualcuno (vedi \u00abIn corso adesso\u00bb) o aspetta la tua firma."
      )
    );
  }

  if (!coda.length) {
    box.replaceChildren(
      h("p", { class: "empty" }, [
        h("b", { text: "Niente da mandare. " }),
        document.createTextNode(
          inCorso.length
            ? `${inCorso.length} fasi sono in mano a qualcuno adesso: quando consegnano, la prossima riga compare qui.`
            : "Tutto quello che il registro dichiara e' preso, consegnato o in attesa della tua firma."
        ),
      ])
    );
    return;
  }

  const parti = [h("div", { class: "actbox" }, coda.slice(0, 12).map(codaRow))];
  if (coda.length > 12) {
    parti.push(
      h("p", {
        class: "actmeta",
        text: `e altre ${coda.length - 12} righe: premi \u00abRicarica\u00bb quando hai mandato queste.`,
      })
    );
  }
  // LE RISERVATE: l'ordine c'e', manca chi lo prende. Ci hai gia' messo l'ordine, quindi non sono
  // «da mandare» \u2014 ma sono le uniche righe dove resta un gesto: il prompt, o togliere la riserva.
  if (attivate.length) {
    parti.push(
      h("div", { class: "actbox" }, [
        h("p", { class: "actgroup warn" }, [
          h("b", { text: "Riservate: nessuno le sta facendo" }),
          h("span", { class: "actcount", text: String(attivate.length) }),
        ]),
        ...attivate.map(riservataRow),
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
  const traccia = rigaConsegna(voce.code);
  if (traccia) testo.append(traccia);
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
  if (voce.fase && (voce.fase.misura || {}).solo_firma) {
    azioni.append(acceptButton(voce.code, message));
  } else if (voce.fase) {
    azioni.append(attivaEConsegna(voce.code, message));
  } else {
    // La fase NON è attivabile: quasi sempre perché è GIÀ ACCETTATA, e l'atto dovuto è un tentativo
    // NUOVO su di lei (il copy da rientrare, la verifica da rifare). Attivarla non si può e non
    // serve: si copia il prompt e lo si dà a una corsia. Era l'errore che ha prodotto «fase non
    // attivabile o inesistente: NAV03E» su un clic perfettamente legittimo.
    azioni.append(copiaPromptButton(voce.code, message));
  }
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
      let copiato = true;
      try {
        await navigator.clipboard.writeText(testo.text || "");
      } catch (erroreCopia) {
        copiato = false;
      }
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
      await navigator.clipboard.writeText(testo.text || "");
      annotaPromptConsegnato(phase);
      message.className = "msg show ok";
      message.textContent = `fatto: ordine in ${payload.order}, fase riservata, prompt COPIATO (${(testo.text || "").length} caratteri). Incollalo in una chat.`;
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
function owedGroup(voci) {
  return h("div", { class: "actbox" }, [
    h("p", { class: "actgroup accent" }, [
      h("b", { text: "Quello che il registro dice che è dovuto" }),
      h("span", { class: "actcount", text: String(voci.length) }),
    ]),
    ...voci.map(owedRow),
  ]);
}

function owedRow(voce) {
  const riga = h("div", { class: "actrow" });
  const testo = h("div", { class: "acttext" });
  const codici = (voce.codes || []).slice(0, 3);
  testo.append(h("code", { class: "actcode", text: voce.from_phase }));
  testo.append(
    document.createTextNode(
      ` dice che il prossimo atto è ${codici
        .map((c) => `${c.code} (${c.status}${c.attempt ? `, attempt ${c.attempt}` : ""})`)
        .join(" e ")}`
    )
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
  riga.append(testo);
  const tracce = codici.map((codice) => rigaConsegna(codice.code)).filter(Boolean);
  tracce.forEach((t) => testo.append(t));
  const azioni = h("div", { class: "actactions" });
  codici.forEach((codice) => {
    // Una cosa già presa non si manda una seconda volta: al posto del pulsante c'e' la misura —
    // qualcuno la sta facendo adesso, e la scheda «In corso adesso» lo dice per esteso.
    azioni.append(
      codice.live
        ? h("span", { class: "actbtn release taken", text: `${codice.code}: in corso` })
        : codice.done
          ? h("span", { class: "actbtn release taken", text: `${codice.code}: consegnata` })
          : owedPromptButton(codice.code)
    );
  });
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
function owedPromptButton(code) {
  return h("button", {
    type: "button",
    class: "actbtn",
    text: `Prompt ${code}`,
    title: `il prompt da incollare per far partire/rifare ${code}`,
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
function annotaPromptConsegnato(code) {
  if (!code) return;
  const adesso = new Date().toISOString().slice(11, 16);
  fetch("/api/inbox", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      phase: code,
      sender: "utente",
      kind: "prompt-consegnato",
      text: `Prompt di ${code} copiato dalla pagina alle ${adesso} e consegnato a una chat. Nessuna presa dichiarata nel registro finché chi l'ha ricevuto non la deposita.`,
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
      await navigator.clipboard.writeText(payload.text || "");
      esito.className = "msg show ok";
      esito.textContent = `copiato (${(payload.text || "").length} caratteri, fonte: ${payload.source}). Incollalo come primo messaggio di una chat nuova.`;
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
function acceptButton(phase, message) {
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
      bottone.disabled = false;
    }
  });
  return bottone;
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
  panel.append(h("div", { class: "dphases" }, unit.phases.map(phaseButton)));
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
  nodes.push(
    h("div", { class: "phead" }, [
      h("span", { class: `chip stato ${tab.state}`, text: BLOCK_STATE[tab.state] }),
      h("span", {
        class: "pmeta",
        text: `${tab.accepted} di ${tab.total} unità accettate · ${tab.units.length} mostrate con il filtro corrente`,
      }),
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
      h("div", { class: "name", text: `${unit.id} — ${unit.title || ""}` }),
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
    h("div", { class: "phases" }, unit.phases.map(phaseButton)),
  ]);
}

/* Una fase, sempre la stessa forma: la usano il percorso e la linea del tempo. */
function phaseButton(phase) {
  return h(
    "button",
    {
      type: "button",
      class: "phase",
      "data-status": phase.status,
      "data-report": phase.report || "",
      "aria-label": `${phase.id}, ${phase.kind || phase.title || ""}: ${phase.status}${
        phase.attempt ? `, tentativo ${phase.attempt}` : ""
      }. ${phase.report ? "Apri il report." : "Nessun report pubblicato."}`,
    },
    [
      h("span", { class: "dot", "aria-hidden": "true" }),
      h("span", { class: "step", text: phase.suffix }),
      document.createTextNode(phase.status),
      phase.attempt ? h("span", { class: "when", text: `t${phase.attempt}` }) : null,
    ]
  );
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

$("#refresh").addEventListener("click", load);

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

initLogo();
initHeaderHeight();
preparaScheda();
loadConfig();
load();

/* Il registro viene letto a OGNI richiesta (il server lo rilegge quando cambia il tempo di
   modifica), ma questa pagina e' un'istantanea: senza ricaricarla, i numeri restano quelli del
   momento in cui l'hai aperta. Per questo si ricarica da sola — e non mentre stai scrivendo in un
   campo, ne' con un dialogo aperto, per non cancellarti quello che stai facendo. */
const INTERVALLO = 30000;
setInterval(() => {
  const campo = document.activeElement;
  const staScrivendo = campo && ["INPUT", "TEXTAREA"].includes(campo.tagName);
  const dialogo = document.getElementById("report-dialog");
  if (staScrivendo || (dialogo && dialogo.open)) return;
  load();
}, INTERVALLO);

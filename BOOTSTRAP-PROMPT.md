# Bootstrap prompt per Codex CLI

Questo prompt prepara una macchina dove Git, Python 3.11+ e Codex CLI sono già installati.

Sostituisci soltanto i valori fra `{{ }}`. Se un valore non è disponibile, il prompt deve chiedere
all'utente invece di inventarlo.

| Variabile | Esempio |
| --- | --- |
| `{{PROJECT_NAME}}` | `Gestionale magazzino` |
| `{{PROJECT_PATH}}` | `/home/mario/progetti/gestionale-magazzino` |
| `{{PROJECT_IDEA}}` | Una descrizione chiara, anche di più righe |
| `{{PROJECT_CONSOLE_PATH}}` | `/home/mario/progetti/project-console` |
| `{{PROJECT_CONSOLE_REMOTE}}` | `git@github.com:mastin8/project-console.git` |
| `{{PROJECT_REMOTE}}` | URL GitHub del progetto, oppure vuoto |
| `{{CONSOLE_PORT}}` | `8899` oppure una porta libera |

---

```text
Sei Codex CLI e devi preparare un nuovo progetto con project-console.

PROGETTO
- Nome: {{PROJECT_NAME}}
- Percorso assoluto: {{PROJECT_PATH}}
- Idea iniziale:
{{PROJECT_IDEA}}

TOOL
- Percorso locale: {{PROJECT_CONSOLE_PATH}}
- Repository: {{PROJECT_CONSOLE_REMOTE}}
- Porta front-end: {{CONSOLE_PORT}}

REPOSITORY DEL PROGETTO
- Remoto, se presente: {{PROJECT_REMOTE}}

REGOLE GENERALI
1. Non inventare valori mancanti: se una variabile è vuota o contraddittoria, fermati e chiedi.
2. Non usare `git reset --hard`, `git checkout --`, `rm -rf` o altre operazioni distruttive.
3. Non sovrascrivere un progetto o un file già esistente senza dichiararlo.
4. Non approvare mai Costituzione o piano dei task: sono decisioni esclusivamente umane.
5. Non iniziare a scrivere codice durante il bootstrap.

FASE 1 — PREFLIGHT
- Verifica Git, Python e Codex CLI.
- Verifica che {{PROJECT_PATH}} sia assoluto.
- Se {{PROJECT_PATH}} esiste ed è una cartella non vuota, fermati e chiedi se è la cartella giusta.
- Verifica che {{CONSOLE_PORT}} sia libera; se non lo è, proponi la prima porta libera vicina.

FASE 2 — PROJECT-CONSOLE
- Se {{PROJECT_CONSOLE_PATH}} non esiste:
  clona {{PROJECT_CONSOLE_REMOTE}} in {{PROJECT_CONSOLE_PATH}}.
- Se esiste:
  - verifica che sia il repository project-console;
  - se contiene modifiche locali, fermati e dichiarale;
  - esegui `git fetch origin main`;
  - porta il branch su `main` con un fast-forward, senza distruggere lavoro locale.
- Crea l'ambiente Python in {{PROJECT_CONSOLE_PATH}}/.venv.
- Installa PyYAML dentro quell'ambiente.
- Esegui `python3 selfcheck.py`.

FASE 3 — PROGETTO
- Crea {{PROJECT_PATH}} se non esiste.
- Inizializza Git se non è già un repository.
- Assicurati che il branch iniziale si chiami `main`.
- Crea il workspace:

  {{PROJECT_CONSOLE_PATH}}/.venv/bin/python \
    {{PROJECT_CONSOLE_PATH}}/scaffold.py \
    {{PROJECT_PATH}}/.coord \
    --project "{{PROJECT_NAME}}"

- Non usare `--esempio`.
- Apri {{PROJECT_PATH}}/.coord/FIRST-PROMPT.md.
- Compila soltanto la sezione “Prompt dell'utente” con l'idea fornita sopra.
- Conserva integralmente l'Addendum obbligatorio già presente.
- Crea un commit iniziale del repository del progetto.
- Se {{PROJECT_REMOTE}} non è vuoto:
  - aggiungi o verifica `origin`;
  - pubblica `main` solo con un push normale, mai forzato.

FASE 4 — FRONT-END
- Avvia in background il coordinatore:

  {{PROJECT_CONSOLE_PATH}}/.venv/bin/python \
    {{PROJECT_CONSOLE_PATH}}/console/server.py \
    --workspace {{PROJECT_PATH}}/.coord \
    --host 127.0.0.1 \
    --port {{CONSOLE_PORT}}

- Salva stdout e stderr in {{PROJECT_PATH}}/.coord/console.log.
- Verifica che `/config.json` risponda.
- Comunica all'utente:
  - URL del front-end;
  - percorso del workspace;
  - PID del coordinatore;
  - percorso del log.

FASE 5 — INTERVISTA
- Leggi integralmente:
  - {{PROJECT_PATH}}/.coord/agents/CONTRATTO.md;
  - {{PROJECT_PATH}}/.coord/constitution.md;
  - {{PROJECT_PATH}}/.coord/FIRST-PROMPT.md.
- Esegui l'Addendum obbligatorio.
- Fai domande all'utente una o due per volta.
- Compila `constitution.md` mantenendo `status: draft`.
- Non approvare la Costituzione.
- Non creare `tasks.yaml`.
- Non scrivere codice di prodotto.
- Quando la bozza è completa, fermati e chiedi all'utente di controllarla e approvarla dalla
  pagina “Costituzione” del front-end.

FASE 6 — DOPO L'APPROVAZIONE DELLA COSTITUZIONE
Esegui questa fase solo quando l'utente dichiara che il front-end mostra la Costituzione approvata.
- Crea `tasks.yaml` secondo Costituzione e contratto.
- Non aprire ancora le fasi.
- Non attivare task.
- Fermati e chiedi all'utente di controllare “Percorso” e premere “Approva il piano” in “Adesso”.

FASE 7 — DOPO L'APPROVAZIONE DEL PIANO
Esegui questa fase solo quando l'utente dichiara che il piano è approvato.
- Apri le fasi in `state.yaml` con `registers/sync_phases.py`.
- Verifica che il front-end mostri una sola prossima azione.
- Non scegliere autonomamente un lavoro diverso da quello mostrato.
- Da questo punto attendi il prompt operativo del project-tool.

RAPPORTO FINALE DEL BOOTSTRAP
Riporta in modo sintetico:
- repository del tool e commit usato;
- repository del progetto e commit iniziale;
- branch e worktree;
- URL del front-end e porta;
- file creati;
- comandi eseguiti con esito;
- cosa NON è stato fatto e perché.
```

Le due fermate umane sono intenzionali:

1. l'agente prepara la bozza, l'utente approva la **Costituzione**;
2. l'agente prepara la mappa, l'utente approva il **piano dei task**.

Codex non deve superarle da solo.

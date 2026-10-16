# Il contratto fra gli agenti e la piattaforma

Questo file e' l'unica cosa da leggere per sapere **cosa scrivere** perche' la piattaforma veda il
lavoro, e **cosa leggere** per sapere cosa fare. Se un comportamento non e' scritto qui, non e'
una regola: chiedilo al coordinamento invece di inventarlo.

## In una riga

**L'interfaccia sono i FILE.** La piattaforma non ti chiama e non ti risponde: legge quello che
scrivi nei posti qui sotto, e scrive nei posti che tu leggi. La pagina web la usano gli umani; un
agente scrive e legge file.

```
  AGENTE ──deposita──►  pending-transitions/     (una presa, un rilascio)
         ──pubblica──►  reports/<fase>/         (il tentativo)
                       reports/<fase>.yaml     (il puntatore: qual e' il tentativo corrente)
         ──lascia in posta──► inbox/            (quello che non entra in un report: un file per messaggio)

  PIATTAFORMA ──scrive──► dispatch-queue/         (l'ordine: cosa fare, con quale prompt)
              ──legge──►  reports/, state.yaml, inbox/   (stato, date, "cosa c'e' da fare dopo", messaggi)
```

## INPUT — quello che scrivi TU, e dove

### 1. Prendere una fase (prima del primo byte)

Depositi una richiesta nella coda delle transizioni. Non scrivi MAI i registri a mano: una
riscrittura libera spegne gli strumenti per tutti.

`pending-transitions/<timestamp>-<tua-corsia>.yaml`:

```yaml
schema: project-console-transition/1.0
requested_by: /nome/della/tua/corsia
requested_at: '2026-01-01T09:00:00+02:00'
file: state.yaml
anchor: "- task_id: ES01T"        # la riga di apertura della voce, RIPRODOTTA ESATTAMENTE
occurrence: 2                     # se la stessa ancora compare piu' volte, quale (1-based)
field: status
text: taken
```

Poi altri campi nella stessa voce, uno per richiesta: `taken_by` (il tuo nome canonico) e
`taken_at`. Se l'ancora non e' unica e non dici `occurrence`, l'applicatore **rifiuta** invece di
scegliere lui. L'ordine completo del ciclo e' in `pending-transitions/README.md`.

Chi applica: il coordinamento, con
`python3 registers/apply_transitions.py --workspace . --dir pending-transitions`.

Lo schema si chiama `project-console-transition/1.0`; l'applicatore accetta anche il nome storico
`binche.ux-transition/1.0`, cosi' le richieste depositate prima della generalizzazione continuano a
valere.

### 2. Consegnare (quando hai finito, e una volta sola)

Due file, e il primo non si riscrive mai:

* `reports/<fase>/attempt-N.yaml` — il tentativo. `N` e' il primo numero libero: un tentativo
  nuovo e' un file nuovo, non la modifica del precedente;
* `reports/<fase>.yaml` — il puntatore, che dice quale tentativo e' quello corrente.

Il tentativo, con i campi che la piattaforma LEGGE:

```yaml
schema: project-console-report/1.0
task_id: ES01T                     # la fase
attempt: 1
status: published                  # published | needs_changes | failed
verdict: pass                      # pass | pass_with_declared_limits | needs_changes
published_at: '2026-01-01T12:00:00+02:00'   # la data che finisce sulla linea del tempo
summary: >-
  Cosa hai fatto e con quale prova.
findings: []                       # uno per problema trovato, con id e testo
next:                              # OBBLIGATORIO: cosa c'e' da fare dopo (vedi sotto)
  - TODO03R: ratifica da una firma distinta, con questo attempt.
```

I campi che la piattaforma legge davvero, e per cosa:

| Campo | Dove finisce |
| --- | --- |
| `status`, `verdict` | lo stato della fase e il verdetto mostrato in pagina |
| `published_at` | la data della barra sulla linea del tempo (senza, vale l'mtime) |
| `next` **o** `next_tasks` | «Cosa c'e' da fare dopo» in testa alla pagina |
| `report`, `report_ref` (nel puntatore) | quale tentativo aprire quando clicchi la fase |
| `attempt` | il numero del prossimo tentativo atteso |

`recommendation` nel puntatore e' il VERDETTO (`accept_unit`, …), non una direzione: per la
direzione si usano `next` / `next_tasks`.

### 3. Lasciare il testimone — l'obbligo che non si salta

Nel report scrivi **sempre** cosa c'e' da fare dopo, in una di queste due forme:

```yaml
next: "ES01R: accettazione dell'unita', con i due residui non bloccanti da giudicare."
```

```yaml
next_tasks:
- id: ES01R
  note: Accettazione dell'unita' da firma distinta; deve giudicare i due residui.
```

Chi apre la pagina dopo di te legge QUELLE righe. Se non ci sono, la pagina lo dichiara come
«consegna senza direzione» e il lavoro si ferma al primo che apre la pagina. Se non hai un report
da scrivere (per esempio hai finito un lavoro di coordinamento), la nota si lascia cosi':

```
python3 registers/handoff.py --workspace . --next <FASE> --note "cosa c'e' da fare dopo"
```

### 4. Rilasciare (alla fine, sempre)

Stessa coda, due campi **insieme**: `status: released` e `released_at`. Una voce viva senza
titolare, o un titolare che non rilascia, blocca la fase per chi viene dopo: la piattaforma conta
«in corso» chi tiene una fase e «attivate» chi l'aspetta, e non confonde le due cose.

### 5. Quello che non entra in un report: la ricevuta

Un report ha dei campi, e non tutti i messaggi hanno la forma di un campo. Se hai qualcosa da dire
che non entra in `summary`, `findings` o `next` — un vincolo scoperto per strada, una decisione che
spetta all'utente, una cosa che hai consegnato fuori dai path dichiarati, un dubbio sul prossimo
passo — **non lasciarlo in una chat**: depositalo in `inbox/`, un file per messaggio, con il testo
parola per parola.

```bash
python3 registers/inbox.py --workspace . --add --file messaggio.md --phase ES01T --from <tua corsia>
```

```markdown
---
ricevuta: 20260101T120000-ES01T
received_at: '2026-01-01T12:00:00+02:00'
sender: <tua corsia>
phase: ES01T
kind: direzione
---

Il messaggio, intero. Non riscritto, non riassunto.
```

Perché esiste questa cassetta e non basta la chat: **la chat non è un archivio.** La piattaforma non
legge i messaggi fra agenti e umani — legge i file. Una cosa detta e non depositata non esiste, e
quello che non esiste non entra nel lavoro di nessuno. La posta è l'unico posto in cui un messaggio
arriva **intero**: nessun campo da indovinare, nessuna riga da quotare, nessun registro da toccare
(per questo non serve nessun lock).

Chi legge la posta la vede in pagina, in **Posta in arrivo**; una ricevuta risulta **lavorata**
quando esiste un report di quella fase scritto dopo di lei. Se riguarda una fase che non esiste
ancora — un prompt nuovo, un'idea — lascia `phase` vuoto: verrà letta lo stesso.

## OUTPUT — quello che leggi TU

| Cosa | Dove | A cosa serve |
| --- | --- | --- |
| **l'ordine** | `dispatch-queue/<data>-<fase>-attivazione.yaml` | il mandato: prompt da incollare, consegna attesa, impronte della revisione |
| il prompt congelato | dentro l'ordine (`prompt`, `prompt_sha256`) | e' il testo che ti e' stato consegnato: **usa quello**, non ricomporlo |
| i registri | `state.yaml`, `tasks.yaml`, `questions.yaml`, `decisions.yaml`, `user_decisions.yaml` | lo stato, i criteri di accettazione, le decisioni |
| i report altrui | `reports/` | cosa e' gia' stato fatto e cosa ha lasciato chi c'e' stato prima |
| la posta | `inbox/` | i messaggi depositati interi: quello che nei report non ci sta |
| il quaderno | `PARALLEL-PROMPTS.md` | i prompt pronti, con il codice di riconoscimento |

E le domande che puoi fare alla piattaforma da riga di comando:

```
python3 registers/next_prompts.py --workspace .            # i prompt e il loro stato
python3 registers/handoff.py --workspace .                 # cosa c'e' da fare dopo
python3 registers/handoff.py --workspace . --gaps           # chi ha consegnato senza direzione
python3 registers/inbox.py --workspace . --list             # i messaggi depositati e non lavorati
python3 registers/activate.py --workspace . --list          # cosa si puo' far partire
python3 registers/mandate.py --workspace . --phase <FASE>   # il prompt di una fase
python3 registers/validate_registries.py --workspace .      # i registri sono leggibili?
```

## Le regole che valgono sempre

| Regola | Se la rompi |
| --- | --- |
| **Prendi la fase prima di scrivere** una voce di claim con `taken_by` e `taken_at` | due corsie sugli stessi byte, e nessuno se ne accorge |
| **Una sola presa viva per fase** | la piattaforma la segnala come doppia presa |
| **Non scrivere i registri a mano**: solo transizioni | una riscrittura libera spegne gli strumenti per tutti |
| **Il tentativo pubblicato non si riscrive**: un tentativo nuovo e' un file nuovo | la storia non e' piu' ricostruibile |
| **Prova solo cio' che tocchi, UNA volta, subito prima di consegnare** | minuti di macchina per nulla, e la coda si ferma |
| **Dichiara cosa NON hai rieseguito, col motivo** | cio' che non e' dichiarato si legge come fatto |
| **Un controllo che non puoi fare si dichiara non fatto** | un fail-open si scopre in produzione |
| **Lascia il testimone** (`next` / `next_tasks`) | la pagina mostra «consegna senza direzione» |
| **Quello che non entra in un report va in `inbox/`** | resta in una chat, cioe' in nessun posto: non lo legge nessuno |

## Un ciclo completo, minimo

```yaml
# 1. pending-transitions/20260101T0900-mia-corsia.yaml  -> prendo la fase
file: state.yaml
anchor: "- task_id: ES01T"
occurrence: 1
field: status
text: taken
```

```yaml
# 2. reports/ES01T/attempt-1.yaml  -> consegno
task_id: ES01T
attempt: 1
status: published
verdict: pass
published_at: '2026-01-01T12:00:00+02:00'
next:
  - ES01R: l'accettazione dell'unita', da una firma distinta.
```

```yaml
# 3. reports/ES01T.yaml  -> il puntatore dice qual e' il tentativo corrente
task_id: ES01T
attempt: 1
report: reports/ES01T/attempt-1.yaml
status: published
verdict: pass
published_at: '2026-01-01T12:00:00+02:00'
```

```yaml
# 4. pending-transitions/20260101T1300-mia-corsia.yaml  -> rilascio
file: state.yaml
anchor: "- task_id: ES01T"
occurrence: 2
field: status
text: released
```

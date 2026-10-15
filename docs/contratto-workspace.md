# Il contratto di un workspace

Un workspace e' una cartella. Dentro ci sono i registri del lavoro e, se vuoi, il marchio e i
comandi di verifica. Il coordinatore la legge; non la crea di nascosto (per quello c'e'
`scaffold.py`) e non scrive mai fuori da essa.

## `console.yaml`

La configurazione: tutto opzionale, e ogni chiave che non esiste ha un valore di convenzione.
Le chiavi ammesse sono esattamente quelle di `workspace.py`, e una chiave scritta male viene
**rifiutata** con l'elenco di quelle valide: un progetto che sembra configurato e non lo e' costa
piu' di un errore all'avvio.

```yaml
project: "Nome del progetto"        # quello che si legge in testa alla pagina
surface: "verifica del percorso"    # cosa si sta guardando
brand: brand                        # dove sta il logo (logo.svg, logo.png, logo-dark.png)
verify:                             # comandi di verifica, mostrati nella vista statica
  - label: "Suite"
    command: "python -m pytest -q"
```

## I registri

### `state.yaml` — cosa sta succedendo

```yaml
active_functional_question: Q001    # la domanda attiva, o null
active_claims:                      # chi sta lavorando su cosa, adesso
  - task_id: ES01A
    status: taken                   # active | taken | ready | pre_registered | released
    taken_by: /corsia               # il titolare, osservabile
    taken_at: '2026-01-01T09:00:00+02:00'
    released_at: null
tasks:                              # una voce per fase: lo stato e l'ultimo report
  ES01A:
    status: accepted                # pending | ready | running | needs_changes | accepted
    attempt: 1
    report: reports/ES01A/attempt-1.yaml
```

Una voce di claim e' VIVA se il suo stato e' fra `active`, `taken`, `ready`, `pre_registered`,
`active_extension` **e** `released_at` e' assente. Il coordinatore considera viva anche una voce
senza `released_at`: e' la differenza fra «rilasciata» e «dimenticata».

### `tasks.yaml` — la mappa del lavoro

Un **blocco** (dominio) contiene **unita'**; ogni unita' attraversa le **fasi** dichiarate in
`console.yaml` (per convenzione `A`, `E`, `T`, `R`). I micro-task si chiamano `<unita><fase>` —
`ES01A`, `ES01T`.

```yaml
units:
  - id: ES01
    domain: esempio
    title: "Cosa fa questa unita'"
    deliverable: "Cosa esiste quando e' accettata"
    depends_on_units: [ES00]
tasks:
  - id: ES01A
    unit_id: ES01
    kind: analysis
    title: "Analisi"
```

Il conto «accettate» compare due volte, di proposito: quello **stretto** (tutte le fasi accettate)
e quello **per ratifica** (l'ultima fase accettata, e le unita' figlie con lei). La pagina dichiara
quale sta usando invece di sceglierne uno in silenzio.

### `questions.yaml` — cosa aspetta l'utente

```yaml
questions:
  - id: Q001
    topic: "Titolo breve"
    question: "La domanda, per esteso"
    why_unresolved: "Perche' non si risolve da soli"
    suggested_answers: ["Opzione A", "Opzione B"]
    affected_tasks: [ES01A]
    status: asked                   # candidate | asked | answered
    answer: null
    decision_ref: null
```

Una sola domanda `asked` per volta: e' la regola che impedisce di chiedere dieci cose insieme e
ricevere risposte incoerenti.

### `user_decisions.yaml` — cosa decide solo l'utente

Scelte sul **modo di lavorare** (chi tiene la penna, cosa si congela, quale garanzia si accetta).
Stanno separate dalle domande di un task proprio perche' non lo sono, e `questions.yaml` ammette una
sola domanda attiva. Chiudendone una dalla pagina si scrivono `status`, `answered_on`, `answer`,
`answer_source`, `decision_ref` e `closed_note`, e si appende la decisione in `decisions.yaml` con
il campo `user_decision_id` che dice a quale voce appartiene.

Se la voce dichiara `options`, la pagina le offre come scelte; se non le dichiara si scrive con
parole proprie. Le alternative **non** si deducono dalla prosa: proporre una scelta sbagliata e'
peggio che chiedere di scriverla.

### `decisions.yaml` — la memoria delle scelte

Append-only: `id`, `date`, `statement`, e il riferimento alla domanda (`question_id`) o alla
decisione di governo (`user_decision_id`). Non si riscrive una decisione: se ne prende un'altra.

### `reports/` — le consegne

Ogni tentativo e' un file: `reports/<fase>/attempt-N.yaml`, con `status`, `verdict` e — quando c'e'
— `published_at`, la data che il coordinatore usa per datare la barra. Accanto, il puntatore
`reports/<fase>.yaml` dice qual e' il tentativo corrente. **Il file del tentativo non si
riscrive**: un tentativo nuovo e' un file nuovo.

### `PARALLEL-PROMPTS.md` — il quaderno

Sezioni numerate; ognuna e' un prompt pronto. Il coordinatore ne ricava lo stato leggendo il
**codice di riconoscimento** (la voce di claim o l'obbligo che il testo nomina), la **consegna**
(una riga `CONSEGNA:` sotto il prefisso dichiarato) e il titolo scritto a mano, di cui dichiara il
disaccordo invece di crederci. Vedi `templates/workspace/PARALLEL-PROMPTS.md`.

### `pending-transitions/` — la coda delle scritture

Nessuno scrive i registri a mano: si deposita una richiesta, l'applicatore la applica con
indentazione calcolata dall'ancora, idempotenza per campo e ripristino se il file non regge piu' la
validazione. Formato in `templates/workspace/pending-transitions/README.md`.

## Il primo giorno di un progetto: aprire le fasi

Una fase non si puo' prendere se il registro non ha la sua voce: `tasks.yaml` dichiara la mappa,
ma `state.yaml#tasks` deve contenere l'entry di ogni fase. Su un progetto nuovo quel blocco e'
vuoto e la prima presa viene **rifiutata** («ancora non trovata»). Dopo aver scritto `tasks.yaml`
il primo passo e':

```bash
python3 registers/sync_phases.py --workspace <progetto>          # mostra cosa aprirebbe
python3 registers/sync_phases.py --workspace <progetto> --apply  # apre le fasi mancanti
```

Apre SOLO le voci mancanti con `status: pending` e non tocca quelle esistenti: la storia di una
fase non si azzera. Backup, validazione e ripristino sono quelli dell'applicatore — se il registro
non regge dopo la scrittura, il file torna com'era e te lo dice.

## Come si scrive (e cosa non si tocca)

| Azione | Chi lo fa | Come |
| --- | --- | --- |
| prendere/rilasciare una fase | un agente | una transizione in `pending-transitions/` |
| registrare una consegna | un agente | un file nuovo in `reports/<fase>/` + il puntatore |
| rispondere a una domanda | l'utente | dalla pagina, o con una transizione |
| chiudere una decisione di governo | l'utente | dalla pagina |
| depositare un ordine di rilancio | l'utente | il tastino «Prepara il rilancio» nella scheda del blocco |

Quello che nessuno fa: riscrivere un tentativo consegnato, cambiare una decisione presa, o
modificare un registro senza passare dalla coda.

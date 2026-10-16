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
| la storia dei ritorni | `reports/<fase>/attempt-*.yaml` letti da `registers/rework.py` | quante volte quella fase e' tornata indietro e per cosa: se l'ostacolo e' sempre lo stesso, non e' un altro tentativo che lo toglie |
| la posta | `inbox/` | i messaggi depositati interi: quello che nei report non ci sta |
| il quaderno | `PARALLEL-PROMPTS.md` | i prompt pronti, con il codice di riconoscimento |

E le domande che puoi fare alla piattaforma da riga di comando:

```
python3 registers/next_prompts.py --workspace .            # i prompt e il loro stato
python3 registers/handoff.py --workspace .                 # cosa c'e' da fare dopo
python3 registers/handoff.py --workspace . --gaps           # chi ha consegnato senza direzione
python3 registers/inbox.py --workspace . --list             # i messaggi depositati e non lavorati
python3 registers/rework.py --workspace .                   # le fasi che tornano indietro, e per cosa
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
| **Un ordine superato si dichiara DENTRO l'ordine** (un campo che comincia per `stale`) | la pagina lo riconsegna, e chi lo riceve brucia un turno per rifiutarlo |
| **Non riconsegnare un ordine che un tentativo ha gia' consumato**: se ne deposita uno nuovo | chi lo riceve lavora su byte e criteri di prima, e il suo atto nasce vecchio |

### Indipendenza: vale la regola SCRITTA, non una piu' stretta

### L'accettazione (`R`) e' un atto corto

Giudicare non e' rimisurare. Quattro passi:

1. **prima il cancello**, una volta: `registers/preflight.py --workspace . --phase <FASE>`. Se dice
   `NON ANCORA`, non si scrive un atto: si deposita il motivo e ci si ferma. Un giudizio su una base
   vecchia nasce respinto — dieci atti di ratifica su una sola unita', tutti per apparato;
2. leggi i **criteri** dell'unita' e i **byte** che il tester ha misurato;
3. **giudica**: accettato, accettato con limiti, respinto;
4. dichiara **limiti e residui**, e cosa NON hai ripercorso col motivo.

**Non** rieseguire le batterie del tester: rifarla e' la stessa misura due volte. Rimisuri solo cio'
che dichiari di rimisurare. Se una prova manca, l'atto e' respinto con quella prova nominata.

E le dipendenze: **da artefatti, non da firme.** Un'unita' di lavoro puo' aspettare il report di
un'altra (E o T), mai la sua **accettazione**. Solo le unita' di integrazione guardano le `R`.

### Dentro un'unita' le fasi sono SEQUENZIALI

`A → E → T → R`, una alla volta: **una sola presa viva per unita'**. Ognuna misura l'output della
precedente, e misurarne una mentre l'altra scrive produce un atto che nasce vecchio — e' costato
undici atti su una sola unita'. Chi prova ad attivare la seconda trova il rifiuto, col motivo.

**L'unica eccezione e' la derivazione dei casi**: la fase `T` puo' scrivere i suoi casi dal design
congelato mentre la `E` lavora, perche' i casi vanno derivati PRIMA di vedere l'esecuzione. Ma
finche' la `E` non ha consegnato, la `T` **non fa girare niente**: derivare e' testo, misurare e'
una presa.

Un atto di verifica o di accettazione deve essere **indipendente da chi ha eseguito**. Cosa vuol dire
"indipendente" non lo decide chi scrive l'atto: lo decide il contratto del progetto, e quello che il
progetto non ha scritto non e' una regola.

L'errore da non ripetere, misurato il 2026-10-16: un progetto scrive «Accettazione analista distinta
dall'esecutore», le corsie traducono "distinta" in «un canonico diverso da quello della sessione di
coordinamento» — e su una macchina in cui ogni agente discende dalla stessa radice quella firma
**non puo' esistere**. Risultato: dieci atti di ratifica respinti uno dopo l'altro per lo stesso
residuo, con la motivazione «non sei un altro», mentre nessuna regola scritta lo chiedeva.

Quindi, quando un atto di verifica e' in dubbio:

1. **cerca la regola nel contratto** del progetto (`tasks.yaml`, `definition_of_done`, i criteri di
   accettazione dell'unita'). Se dice «distinto dall'esecutore», il metro e' quello: chi non ha
   scritto quei byte soddisfa il criterio, anche se discende dalla stessa radice;
2. **se nel registro trovi una richiesta piu' stretta** (per esempio «nessun discendente di X»),
   quella e' una richiesta IN PIU': **dichiara la contraddizione** col contratto nel tuo atto e vai
   avanti sul metro scritto. Non ti bloccare su una regola che nessuno ha scritto, e non riscriverti
   addosso che il criterio non e' soddisfatto;
3. **se davvero serve una distanza maggiore**, quella e' una decisione di governo: si chiede a chi
   decide (`user_decisions.yaml`), non si applica da soli in attesa che qualcun altro la indovini.

Un blocco che nessuno puo' sciogliere dall'interno non e' rigore: e' lavoro fermo.

## Le domande che fai all'utente

Una domanda si scrive per farla capire a chi deve rispondere, non per dimostrare che hai capito tu.
Il testo resta tuo e non viene riscritto: ma **prima** del testo la piattaforma mette tre righe che
deve poter misurare, quindi la domanda deve dichiararle.

| Campo | Cosa contiene | Se manca |
| --- | --- | --- |
| `blocked_scope` | in una riga, cosa resta fermo finché non arriva la risposta | la pagina non puo' dire cosa si sta perdendo ad aspettare |
| `affected_tasks` | i codici delle fasi toccate | non si vedono respinte e ostacoli di quelle fasi |
| `options[].label` | l'alternativa, in poche parole | — |
| `options[].description` | **cosa succede scegliendola**, incluse le conseguenze scomode | la pagina mostra l'alternativa senza il suo prezzo, e chi risponde sceglie alla cieca |

La `description` e' la parte che conta di piu': una domanda che offriva «si fornisce una firma
distinta» senza dire che quella firma *non esisteva* e che le ratifiche sarebbero rimaste respinte
per sempre ha prodotto una risposta che ha bloccato quattro fasi. Se un'alternativa ha un prezzo,
il prezzo va scritto li':

```yaml
options:
- label: "Si fornisce una firma distinta"
  description: >-
    Serve una sessione con un canonico diverso da `/root`, che oggi NON esiste: finche' non c'e',
    le quattro ratifiche restano respinte (misurato: 10 atti, stesso ostacolo).
- label: "Si accetta il debito dichiarato"
  description: >-
    Le ratifiche si chiudono subito, ma come atti NON indipendenti, col debito scritto nel registro
    e nel gate finale.
```

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

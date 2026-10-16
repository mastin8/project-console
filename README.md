# Project Console

Il coordinatore dei progetti: una pagina locale che legge i registri di un progetto e mostra, in un
colpo d'occhio, **a che punto e'**, **cosa aspetta te** e **cosa si puo' far partire adesso**. Dove
serve scrivere — rispondere a una domanda, chiudere una decisione di governo, depositare un ordine
di lavoro — scrive passando dal lock e dalla validazione dei registri.

Non conosce nessun progetto: un **workspace** e' una cartella di dati, e il coordinatore ne serve
quanti vuoi, anche contemporaneamente.

Serve Python 3.11+ e PyYAML. Nessuna rete in uscita, nessun servizio esterno.

---

# ISTRUZIONI

## In trenta secondi, per vedere com'e' fatto

```bash
python3 scaffold.py /tmp/prova --project "Prova" --esempio   # crea un workspace d'esempio
python3 console/server.py --workspace /tmp/prova             # http://127.0.0.1:8899
```

Senza `--workspace` il coordinatore usa `$CONSOLE_WORKSPACE`, o la cartella corrente. Il workspace
d'esempio `examples/demo` e' nel repo: `python3 console/server.py --workspace examples/demo`.

## Il primo giorno di un progetto vero

Parti da un'idea e vuoi la vista accesa, coi TUOI blocchi e i TUOI nomi. Sono quattro passi.

### Passo 1 — la cartella dei registri

```bash
python3 scaffold.py /percorso/mio-progetto --project "Nome del progetto"
```

Crea i registri vuoti, i quattro ruoli degli agenti e il quaderno. Mettila **dentro il repository
del progetto** (per esempio `.coord/`): cosi' la riga dei commit funziona e mostra quali commit
toccano i path che dichiari.

Accendendo subito la vista vedi il vuoto detto bene: *0 di 0 unita' accettate*, *nessuna data da
disegnare*, *nessun prompt nel quaderno*. Non e' un errore: e' un progetto che non ha ancora
scritto niente.

### Passo 2 — la mappa del lavoro: `tasks.yaml`

Qui nascono i tuoi blocchi. Un blocco e' un'area del lavoro (il nome lo scegli tu: sono le schede
in fondo alla pagina), e contiene unita'; ogni unita' attraversa le fasi del ciclo.

```yaml
units:
- id: CAT01
  domain: catalogo                 # <-- il nome del BLOCCO, come lo vuoi tu
  title: "Schede prodotto con foto e prezzi"
  deliverable: "Una scheda prodotto pubblicabile dal pannello"
  requirement_ids: [R001]          # facoltativo
  depends_on_units: []             # facoltativo: chi deve essere chiuso prima
- id: ORD01
  domain: ordini                   # <-- un altro blocco, un altro nome
  title: "Carrello e conferma ordine"
  deliverable: "Ordine confermato con email al cliente"
  depends_on_units: [CAT01]        # l'unita' mostrera' «in attesa di CAT01»
  requirement_ids: [R002]
tasks:
- id: CAT01A
  unit_id: CAT01
  kind: analysis
  title: "Analisi: quali campi servono a una scheda"
- id: CAT01E
  unit_id: CAT01
  kind: implementation
  title: "Esecuzione: pannello e pubblicazione"
- id: CAT01T
  unit_id: CAT01
  kind: independent_verification
  title: "Verifica indipendente: campi mancanti, foto sbagliate"
- id: CAT01R
  unit_id: CAT01
  kind: functional_acceptance
  title: "Accettazione"
```

Le regole che il coordinatore usa davvero:

- **il blocco e' `domain`**: nome libero, diventa la scheda in fondo alla pagina. Lo stesso
  `domain` su piu' unita' le tiene insieme;
- **la fase e' un `task` con `unit_id`**: e' `unit_id` a legarla all'unita' (non il prefisso
  dell'id);
- **l'id della fase comincia con l'id dell'unita'** (`CAT01` + `A`): serve a mostrare la lettera
  giusta nei tastini, quindi vale la pena rispettarlo;
- **i suffissi non devono essere A/E/T/R**: sono i tuoi. Le fasi del ciclo si dichiarano in
  `console.yaml` (`phases:`), e l'ultima e' quella che ratifica l'unita';
- **`kind` e' un'etichetta libera** (per convenzione `analysis`, `implementation`,
  `independent_verification`, `functional_acceptance`), e finisce nel report che si apre cliccando;
- **gli id sono unici** in tutto il file.

### Passo 3 — aprire le fasi nel registro

```bash
python3 registers/sync_phases.py --workspace /percorso/mio-progetto --apply
```

Senza questo, il primo agente che prova a prendere una fase viene **rifiutato** («ancora non
trovata»): `tasks.yaml` dice quali fasi esistono, ma e' `state.yaml#tasks` che ne tiene lo stato, e
su un progetto nuovo e' vuoto. Il comando apre solo le voci mancanti, con `status: pending`, e non
tocca quelle che esistono.

Gia' da qui la vista mostra i blocchi, con le unita' «da fare» e i tastini della fase.

### Passo 4 — il primo prompt: `PARALLEL-PROMPTS.md`

Una sezione numerata per prompt. Perche' il coordinatore lo riconosca servono tre cose:

````
## 1 — CAT01A — DA FARE

```
Lavora in /percorso/mio-progetto. Sei un agente di esecuzione: non coordinare, non chiedere conferme.

REGISTRO: in state.yaml esiste la voce di claim CAT01A. Deposita la presa in pending-transitions/
prima del primo byte, e il rilascio alla fine.

CONSEGNA: reports/CAT01A/attempt-1.yaml (verifica che NON esista) e il puntatore reports/CAT01A.yaml.
```
````

1. **il codice di riconoscimento**: il nome della voce di claim (o dell'obbligo) nel testo, che deve
   esistere nel registro. E' cosi' che la pagina sa a quale fase appartiene quel prompt;
2. **la consegna**: la riga `CONSEGNA:` col file che il prompt deve pubblicare (sotto il prefisso
   `deliverable_prefix`, per convenzione `reports/`);
3. il **titolo scritto a mano**, che viene confrontato con la misura: se dice «fatto» e la consegna
   non esiste, la pagina te lo segnala invece di crederci.

Da qui in poi la pagina e' viva: *da lanciare* finche' nessuno prende, *in azione* quando la presa
e' nel registro, *fatto* quando la consegna esiste, *consegna respinta* se il verdetto dice di no.

### Il vocabolario degli stati

Il coordinatore non indovina: conosce queste parole, e le altre le mostra come sono.

| Dove | Stato | Cosa significa per la vista |
| --- | --- | --- |
| `state.yaml#tasks` | `accepted` | la fase e' chiusa: e' l'unico stato che CHIUDE |
| `state.yaml#tasks` | tutto il resto | la fase e' aperta (qualunque parola tu usi) |
| `state.yaml#tasks` | `needs_changes`, `failed` | respinta in verifica: torna a chi l'esegue |
| `state.yaml#active_claims` | `active`, `taken`, `ready`, `pre_registered`, `active_extension` | presa viva, se `released_at` e' assente |

### Cosa e' obbligatorio e cosa no

| File | Obbligatorio? | A cosa serve |
| --- | --- | --- |
| `tasks.yaml` | si' | i blocchi, le unita', le fasi: e' la mappa |
| `state.yaml` | si' (lo crea lo scaffold) | lo stato delle fasi e le prese vive |
| `PARALLEL-PROMPTS.md` | per la sezione dei prompt | il lavoro da far partire |
| `console.yaml` | no | nome, marchio, comandi di verifica, nomi dei file |
| `questions.yaml` | no | le domande che aspettano l'utente |
| `user_decisions.yaml` | no | le decisioni che appartengono solo all'utente |
| `reports/` | no (lo crea lo scaffold) | le consegne e i puntatori |
| `inbox/` | no | la posta in arrivo: i messaggi depositati interi, uno per file |
| `agents/` | no | i ruoli e la mappa degli agenti |
| `brand/logo.png` | no | il marchio nell'intestazione |

### Gli agenti

I ruoli sono gia' copiati in `agents/roles/` (coordinatore, analista, esecutore, verificatore).
Quello che personalizzi e' `agents/agents.yaml`: un ruolo per voce, con la missione e il perimetro.
Il prompt operativo di un agente e' la somma di tre cose: il suo ruolo, il suo mandato, e il quaderno
dove sta il lavoro da fare.

La regola che tiene insieme tutto: **un agente prende la fase prima di scrivere** (una voce di claim
nel registro, depositata come transizione) e **la rilascia quando consegna**. Senza questa regola
due corsie lavorano sugli stessi byte e la vista mostra due titolari sulla stessa fase.

## Comandi

```bash
python3 console/server.py --workspace <progetto> [--port 8899] [--host 127.0.0.1]
python3 scaffold.py <cartella> --project "Nome" [--esempio]
python3 registers/activate.py --workspace <progetto> --list          # cosa si puo' far partire adesso
python3 registers/activate.py --workspace <progetto> --target <fase> # attiva: ordine + riserva
python3 registers/activate.py --workspace <progetto> --release <fase># toglie la riserva
python3 registers/sync_phases.py --workspace <progetto> [--apply]   # apre le fasi non ancora registrate
python3 registers/validate_registries.py --workspace <progetto>
python3 registers/next_prompts.py --workspace <progetto> [--json|--explain]
python3 registers/handoff.py --workspace <progetto>                          # cosa c'e' da fare dopo
python3 registers/inbox.py --workspace <progetto> --list [--tutte]           # la posta in arrivo
python3 registers/inbox.py --workspace <progetto> --add --file <messaggio> [--phase <FASE>]
python3 registers/rework.py --workspace <progetto> [--fase <FASE>|--json]        # cosa si ripete
python3 registers/static_view.py --workspace <progetto>             # la stessa cosa, in una pagina statica
python3 registers/apply_transitions.py --workspace <progetto> --dir <progetto>/pending-transitions
```

Il servizio manda `index.html`, `app.js` e `style.css` con `Cache-Control: no-store`: dopo un
`git pull` un ricaricamento normale basta, e non si finisce a guardare pulsanti che nel file non ci
sono piu'.

## Se un progetto ha gia' un punto d'ingresso suo

Capita che un progetto abbia imparato un comando proprio — per esempio
`python3 docs/ux-context-pack/review/server.py` — e che quel comando serva una copia vecchia del
coordinatore. Due copie divergono, e chi apre quella vecchia si trova un'interfaccia senza gli
strumenti: pulsanti che falliscono, nessun modo di far partire una fase. E' successo il 2026-10-15.

Il rimedio e' un **inoltro**, non una copia: il vecchio file diventa dieci righe che chiamano il
coordinatore nuovo sul proprio workspace.

Il modello pronto e' **[templates/entrypoint-forward.py](templates/entrypoint-forward.py)**: si
copia al posto del vecchio comando e si cambia una riga (`CONSOLE_PATH`).

```python
CONSOLE = Path("/percorso/project-console")
WORKSPACE = Path(__file__).resolve().parents[1]
subprocess.call([sys.executable, str(CONSOLE / "console" / "server.py"),
                 "--workspace", str(WORKSPACE), *sys.argv[1:]])
```

Cosi' il comando che si e' imparato continua a funzionare, la pagina e' una sola, e il codice non
esiste in due posti.

## Cosa si vede, e cosa puoi fare

Il contenuto e' diviso in cinque pagine, una per domanda. Il testo lungo (prompt, dichiarazioni,
report) non sta mai in pagina: si apre in un dialogo, con **Copia** e **Salva come file** accanto.

- **Adesso** (`/`) — la coda, ed e' la pagina che si guarda tornando. In ordine di leva, tre gruppi:
  *da rifare* (respinte in verifica), *da attivare*, *in attesa di un esecutore*. Una riga per cosa,
  un pulsante per riga: **Attiva** (deposita l'ordine e riserva la fase), **Copia il prompt**,
  **Salva come file**, **Leggi**, **Rilascia**. Sotto: le domande che aspettano te, chi sta lavorando
  adesso, e le risposte che hai gia' dato. E la **Posta in arrivo**: vedi qui sotto.
- **Tempo** (`/tempo`) — il percorso nel tempo: blocchi, unita', fasi, con le barre datate da cio' che
  gli artefatti DICHIARANO (`published_at`) o, in mancanza, dall'mtime; e la riga dei commit del
  repository, con i commit che toccano i path dichiarati da ogni blocco. Nessuna previsione: solo
  misure. Un progetto al primo giorno resta disegnato, senza barre: «nessuna data: non ancora
  iniziata».
- **Testimone** (`/testimone`) — cosa c'e' da fare dopo, parola per parola: quello che chi ha finito
  ha lasciato scritto nel suo report. Filtro (unita' aperte / tutte / senza direzione) e ricerca.
- **Prompt** (`/prompt`) — i prompt del quaderno, raggruppati per stato d'azione: da fare, fatti,
  con consegna respinta. Ognuno col testo da copiare e da salvare come file.
- **Percorso** (`/percorso`) — una scheda per blocco: unita', risultato atteso, fasi che aprono il
  report, respinte in verifica, e i commit che toccano i path dichiarati dal blocco.

«Salva come file» scarica un `.md` col testo esatto del prompt, senza passare dalla clipboard: serve
a isolare dove si rompe un testo — se il file e' giusto e il testo incollato no, il difetto e' nel
posto che lo riceve, non nel prompt.

Nell'intestazione: il marchio (dal tuo `brand/`, o un monogramma), il nome del progetto, quattro
tastini coi conteggi — aperte, respinte, in corso, per te — e il filtro condiviso dalle viste.
Il tastino delle respinte filtra e atterra sulla prima fase `needs_changes`.

## Attivare una fase: l'input

Quando non ci sono domande da rispondere, decisioni da prendere o prompt da lanciare, la pagina
restava muta: nessun campo, nessun pulsante, nessun modo di cominciare. Adesso c'e' «Cosa puoi
attivare»: le fasi senza presa viva, in cima quelle respinte in verifica (sono lavoro da rifare),
ognuna col suo pulsante. Il pulsante c'e' anche su ogni prompt del quaderno, quando il suo codice e'
una fase.

Attivare fa due cose, e non finge la terza:

1. deposita un **ordine durevole** in `<workspace>/dispatch-queue/` con il testo del prompt, il
   perimetro, il file di consegna atteso (`attempt-N`, il prossimo) e le **impronte** dei file di
   prodotto che la fase deve misurare — la revisione che l'ordine si aspetta, congelata;
2. **riserva la fase** nel registro con `status: pre_registered`, lo stato che il registro usa per
   «voce pronta, nessun titolare». Da quel momento una seconda attivazione della stessa fase viene
   rifiutata, invece di produrre due esecutori sugli stessi byte.

Quello che NON fa: non avvia nessun agente. Un ordine e' una promessa in attesa di un esecutore, e
il pannello lo dice con quelle parole. Chi prende la fase la porta a `taken` col proprio nome,
depositando la presa come al solito, ed e' lui che risponde di quei byte.

La riserva si toglie con **Rilascia** (o `--release`): la fase torna disponibile e l'ordine resta
sul disco come prova di cosa era stato chiesto. Un ordine senza riserva viene cancellato da solo se
la scrittura nel registro fallisce: non resta mai sul disco un ordine che qualcuno potrebbe
raccogliere mentre la fase e' libera.

### Un ordine superato si dichiara dentro l'ordine

Chi si accorge che un ordine non va piu' eseguito — perche' il lavoro che ordinava e' atterrato da
un'altra corsia — lo scrive **dentro l'ordine**, con un campo che comincia per `stale`:

```yaml
stale_20260101T1600: >-
  QUEST'ORDINE NON VA PIU' ESEGUITO: il rientro e' atterrato, la prova e' in produzione.
```

L'ordine resta sul disco come storia, ma la pagina non lo riconsegna piu': attivare quella fase ne
deposita uno **nuovo**, con le impronte di adesso. Il motivo di questa regola e' misurato, non
teorico: il 2026-10-16 lo stesso ordine scaduto di una fase era stato consegnato a **quattro**
attivazioni, e **sette sessioni** l'hanno ricevuto e rifiutato — ognuna spendendo il proprio turno
per scrivere che quell'ordine era morto. Un tool che riconsegna un mandato scaduto brucia il lavoro
di chi lo riceve.

E c'e' un secondo modo, che non dipende da nessuna dichiarazione: **un ordine e' consumato quando un
tentativo della sua fase e' stato pubblicato dopo di lui.** Il mandato ha gia' prodotto il suo atto;
riconsegnarlo significa dare a qualcuno un ordine che parla di byte e criteri di prima. La pagina lo
misura da sola (data dell'ordine contro data dichiarata dagli attempt) e non lo riconsegna:
attivare deposita un ordine nuovo, che dichiara dentro di se' quale sostituisce (`replaces`).

Misurato il 2026-10-16 sul progetto di origine: **dodici ordini aperti su diciotto erano consumati**,
e i tre che l'utente vedeva «fallire sempre» erano quelli con piu' consegne: lo stesso mandato di
`NAV03R` riconsegnato a cinque attivazioni, quello di `TODO03E` a quattro, quello di `UPL04ZR` a tre.
Ogni nuovo esecutore riceveva un ordine scritto prima del lavoro che doveva fare.

## Le domande: prima in parole povere, poi il testo

Una domanda che chiede di scegliere parla di cose che nel registro hanno un nome, e chi risponde ha
il diritto di sapere in che stato sono **prima** di scegliere. Sopra il testo della domanda — che
resta quello di chi l'ha scritta, parola per parola, perche' riscriverlo sarebbe mettere in bocca a
qualcun altro una cosa che non ha detto — la pagina mette tre righe misurate:

```
Di cosa si parla: UPL04ZR — needs_changes, respinta 10 volte su 10, ostacolo
  «UPL04Z-T-ON-CURRENT-REVISION» bloccante, lo deve: UPL04ZT attempt 2
Resta fermo finché non rispondi: la ratifica di UPL04Z e la chiusura dell'unità
Firme nel registro: una sola, /root (187 prese). Una firma distinta non esiste
  ancora: una risposta che la pretende la deve anche creare, altrimenti quelle
  fasi restano respinte.
```

Perche' esiste, e non e' un'ipotesi: il 2026-10-15 l'utente ha risposto a una domanda sulle ratifiche
scegliendo «si fornisce una firma distinta», e la domanda non diceva che — senza una seconda firma,
che non esisteva — quelle quattro ratifiche sarebbero rimaste respinte per sempre. Gli servivano tre
numeri: chi tocca, cosa resta fermo, quante firme ci sono. Ora li ha.

Le tre righe si costruiscono cosi': i codici che la domanda nomina (confrontati con i task del
registro, non indovinati), il loro stato con respinte e ostacolo ricorrente, lo `blocked_scope`
dichiarato, e — quando la scelta riguarda firme o indipendenza — quante firme distinte risultano
dalle prese nel registro. Dove una domanda non dichiara `blocked_scope` o le opzioni senza
`description`, la pagina mostra quello che c'e': completare il resto tocca a chi la pone.

## Quando una fase non si sblocca con un altro tentativo

«Respinta in verifica» non distingue una fase respinta ieri dalla prima volta da una che torna
indietro da dieci atti **sempre per lo stesso motivo**. La seconda non e' lavoro da rifare: e' un
ostacolo che nessun tentativo in piu' rimuove, e serve che qualcuno decida. La coda lo dice, con la
misura presa dai report:

```
UPL04ZR  10 tentativi · 10 respinte · lo stesso ostacolo in 10 su 10: UPL04Z-T-ON-CURRENT-REVISION
         · bloccante · chi lo deve: UPL04ZT attempt 2, con un tester distinto dall'autore
```

In pagina, la riga della coda porta tre cose: quanti tentativi e quante respinte, qual e' l'ostacolo
che torna (col nome, non con una parafrasi), e — quando il report lo dichiara — **chi lo deve**. Se
li' c'e' scritto l'utente, vuol dire che nessun agente lo chiude: la leva e' una decisione.

Due avvertenze nei conti, che sono la parte onesta della misura: gli identificatori **locali**
(`R1`, `F2`, `T4`, la numerazione di ogni singolo atto) non si contano insieme — l'`R1` dell'atto 1
e l'`R1` dell'atto 7 sono due cose diverse, e contarle direbbe una cosa falsa. E quando nessun
ostacolo torna con lo stesso nome, la pagina lo dice con quelle parole: «ogni atto nomina punti
nuovi», che e' il segno che la leva sta altrove.

```bash
python3 registers/rework.py --workspace <progetto>            # le fasi che tornano indietro
python3 registers/rework.py --workspace <progetto> --fase X --json
```

## La posta in arrivo: perche' un messaggio non deve morire

La piattaforma **non legge le chat**. Di quello che un agente scrive, arrivano in pagina solo le tre
cose che hanno un campo: la presa, il rilascio, e il `next` del report. Tutto il resto — cosa ha
consegnato, cosa non ha fatto, cosa serve dopo, cosa ha scoperto per strada — resta in un messaggio
che nessuno archivia. Misurato sul primo progetto che ha usato questo strumento: 203 direzioni
dichiarate nei report, e **41 consegne senza direzione**, cioe' 41 messaggi che contenevano qualcosa
e non sono arrivati a nessun file.

`inbox/` e' la cassetta dove quel messaggio si deposita **intero**. Un file per messaggio, il testo
parola per parola, quattro righe di intestazione (chi, quando, quale fase, di che natura):

```bash
python3 registers/inbox.py --workspace <progetto> --list                    # cosa e' arrivato
python3 registers/inbox.py --workspace <progetto> --add --file messaggio.md --phase <FASE>
python3 registers/inbox.py --workspace <progetto> --chiudi <ricevuta> --nota "cosa ne e' stato"
```

Oppure dalla pagina, in **Posta in arrivo** (pagina *Adesso*): si incolla il messaggio e si preme un
pulsante. Una ricevuta risulta **lavorata** quando esiste un report di quella fase che *dichiara* una
data dopo di lei (`published_at`); se la fase non ha report datati, si ripiega sull'mtime. La data
dichiarata, e non l'mtime, e' la misura giusta: un `git pull` o un checkout riscrivono l'mtime senza
che nessuno abbia lavorato, e tutte le ricevute risulterebbero lavorate in un colpo. Quelle non
lavorate stanno in cima, col loro numero.

Tre scelte, e il motivo di ognuna:

1. **Una cartella, non un registro.** I registri sono vivi e contesi: scriverci dentro richiede il
   lock e la validazione, e una scrittura sbagliata ferma le corsie. Il deposito di un messaggio non
   puo' rompere niente di vivo, e non c'e' nessun lock da prendere.
2. **Un file di testo, non un campo.** Dentro un YAML ogni riga andrebbe quotata, e il primo apice
   storto corrompe il messaggio che si voleva salvare. Il testo di un messaggio non si tocca.
3. **Accetta anche i messaggi che non hanno una fase.** Un prompt nuovo, un'idea, un vincolo: nei
   registri non avrebbero dove stare, in posta si'.

La posta non e' un secondo quaderno e non sostituisce il report: e' il posto di quello che nel
report non ci sta. La regola per gli agenti e' in `agents/CONTRATTO.md`, sezione 5, e arriva con lo
scaffolder: un progetto nuovo la eredita senza che nessuno la riscriva.

## Il contratto di un workspace

Tutto quello che il coordinatore legge ha un nome dichiarabile in `console.yaml`; i valori
predefiniti sono la convenzione, e un workspace scritto a mano funziona senza configurazione.

| Cosa | Default | A cosa serve |
| --- | --- | --- |
| `project` / `surface` | — | il nome in testa e il nome della vista |
| `state.yaml` | `state.yaml` | lo stato delle fasi, le prese vive, i report |
| `tasks.yaml` | `tasks.yaml` | i blocchi e le unita', con le fasi del ciclo |
| `questions.yaml` | `questions.yaml` | le domande che aspettano l'utente |
| `decisions.yaml` | `decisions.yaml` | le decisioni prese, in ordine |
| `user_decisions.yaml` | idem | le decisioni di governo, che appartengono all'utente |
| `reports/` | idem | le consegne: `reports/<id>/attempt-N.yaml` e il puntatore `reports/<id>.yaml` |
| `PARALLEL-PROMPTS.md` | idem | il quaderno dei prompt, coi codici di riconoscimento |
| `pending-transitions/` | idem | la coda delle scritture sui registri |
| `brand/` | idem | `logo.svg` o `logo.png`: l'intestazione li usa senza toccare codice |
| `verify` | vuoto | i comandi di verifica del progetto, mostrati nella vista statica |

Il significato di ogni campo, la forma di ogni registro e le regole che rendono un prompt
riconoscibile sono in **[docs/contratto-workspace.md](docs/contratto-workspace.md)**. Il modello
pronto da copiare e' in **[templates/workspace/](templates/workspace/)**.

## Stato

Estratto il 2026-10-15 dal primo progetto che ha usato questo strumento e reso agnostico: il
progetto e' diventato un workspace, i comandi di verifica una voce di configurazione, il nome e il
marchio due caselle. Le prove che funziona su altro sono nel repo: `examples/demo` creato dallo
scaffolder, e due progetti veri (uno con blocchi `catalogo`/`ordini`) usati per scrivere queste
istruzioni.

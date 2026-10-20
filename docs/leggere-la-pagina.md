# Leggere la pagina, e cosa fare

Ogni cosa che vedi in pagina, cosa significa, e il passo che comporta. L'ordine e' quello in cui la
trovi: testata, riquadro della coda, schede, pulsanti. In fondo c'e' la tavola «se vedi X, fai Y».

La regola che tiene insieme tutto: **la pagina non sa niente e non decide niente.** Legge i file del
progetto (registri, report, cartelle) e ti mostra cosa dicono. Quando ti serve un'azione, la fa
*depositando* qualcosa che qualcun altro esegue: un ordine, una risposta, una richiesta.

---

## 1. Da dove vengono i numeri

| Cosa | Dove sta | Chi lo scrive |
| --- | --- | --- |
| stato delle fasi, prese, tentativi | `state.yaml` | le corsie, depositando richieste in `pending-transitions/` |
| unita', blocchi, criteri | `tasks.yaml` | tu, all'inizio del progetto |
| consegne, verdetti, «cosa resta da fare» | `reports/<fase>/attempt-N.yaml` + il puntatore `reports/<fase>.yaml` | chi esegue la fase |
| gli ordini (cosa fare, con quale prompt) | `dispatch-queue/` | la pagina, quando premi **Attiva** |
| i messaggi che non entrano in un report | `inbox/` | chiunque, dalla pagina o da riga di comando |
| le domande e le decisioni | `questions.yaml`, `decisions.yaml`, `user_decisions.yaml` | il coordinamento; le risposte le dai tu |

**Il registro e' sempre un passo indietro ai file**, ed e' normale: un agente scrive il report subito,
ma la modifica al registro passa da una richiesta che qualcuno deve applicare. Ecco perche' esiste il
riquadro della coda (§3), ed ecco perche' in pagina puoi leggere «respinta» di una fase che ha appena
consegnato.

---

## 2. La testata (resta su tutte le pagine)

| Cosa leggi | Cosa significa | Cosa fare |
| --- | --- | --- |
| nome del progetto + la vista | da `console.yaml` (`project`, `surface`) | niente |
| «istantanea di … (adesso)» | quando la pagina ha letto i registri. La pagina si rilegge da sola **ogni 30 secondi** (non mentre stai scrivendo in un campo, ne' con un dialogo aperto) | se vuoi il dato di ora, premi **Ricarica** |
| **15 aperte** | unita' non ancora accettate | clic: filtra su «Aperte» e ti porta alla linea del tempo |
| **4 respinte** | fasi respinte in verifica (`needs_changes`, `failed`): tornano a chi le esegue, non a te | clic: filtra e ti porta sulla prima |
| **3 in corso** | fasi con una **presa viva**: qualcuno ci sta lavorando adesso | clic: vai a «In corso adesso» |
| **0 attivate** | fasi **riservate** e in attesa di un esecutore (`pre_registered`, `ready`): l'ordine c'e', nessuno l'ha raccolto | clic: vai alla coda |
| **0 per te** | domande + decisioni di governo + prompt da lanciare | clic: ti porta sulla prima cosa che aspetta te |
| la barra sottile | percentuale di unita' accettate | niente |
| **Adesso · Svolto · Tempo · Testimone · Prompt · Percorso · Costituzione** | le sette pagine | — |

Attenzione a due parole che sembrano uguali e non lo sono: **«in corso»** = qualcuno *tiene* la fase;
**«attivate»** = la fase e' riservata ma **nessuno** l'ha presa.

---

## 3. Il riquadro «Coda dei registri» (compare solo quando c'e' coda)

**Cosa significa.** Le corsie non scrivono i registri: depositano in `pending-transitions/` una
richiesta per ogni modifica («su questa voce, cambia questo campo con questo testo»). Un programma le
applica, una alla volta, sotto lock, con la validazione dentro la scrittura. Finche' nessuno le
applica, **il registro e' indietro rispetto ai file** — e con lui tutto quello che leggi in pagina.

| Cosa leggi | Cosa significa |
| --- | --- |
| «N richieste mai applicate» | la dimensione dell'arretrato |
| «N ferme da più di 12 ore» | non e' coda fisiologica: e' coda ferma |
| «N da guardare prima di applicare» | richieste che **non** vanno eseguite alla cieca (vedi sotto) |
| le più numerose: `NAV03R 43 · UPL04ZR 33 …` | dove si e' accumulato |
| **Il registro è indietro su N fasi** | per ogni fase, cosa dice il registro e cosa dicono i file: `registro: needs_changes · attempt 3 / file: attempt 9` |
| **N richieste da guardare** | ognuna col motivo, **ordinate per gravità** (prima quelle che possono corrompere il registro) |

**I motivi con cui una richiesta e' segnalata** (tutti misurati, non sospetti):

| Motivo | Perche' conta |
| --- | --- |
| «la fase ha GIA' una presa viva: questa ne aggiunge una seconda» | un **inserimento di presa** crea un titolare che non esiste: la fase resterebbe «in corso» per sempre |
| «inserisce una presa vecchia su una fase già al attempt N» | idem, con una presa di ieri |
| «riporterebbe il registro all'attempt N mentre su disco c'è il M» | applicata per ultima, farebbe tornare indietro il registro |
| «sostituita da `<file>`, depositata dopo» | superata: vale l'ultima |
| «ancora ambigua e nessuna `occurrence`» | l'applicatore la **rifiutera'** da solo |

**I tre passi, nell'ordine, dal pulsante «Copia i due comandi»**:

```bash
# 0. la copia, PRIMA. I registri non sono in git: questa e' l'unica via del ritorno.
cd <progetto> && cp state.yaml /tmp/state-prima-della-coda.yaml

# 1. cosa farebbe, su UNA richiesta (su tutte stamperebbe il registro intero, 2,3 MB, 129 volte)
python3 tools/apply_transitions.py pending-transitions/<una>.yaml --dry-run | head -40

# 2. applica la coda: una riga per richiesta; le riuscite vanno in applied/
python3 tools/registry_runner.py --once
```

**Cosa deve succedere dopo il passo 2**: una riga `APPLICATA <file> -> <campo>` per ogni richiesta
riuscita, `RIFIUTATA <file>: <motivo>` per le altre (che **restano in coda**), le riuscite spostate in
`pending-transitions/applied/`, e `STATUS.html` rigenerato. **In pagina**, entro mezzo minuto: il
numero del riquadro scende, le fasi smettono di risultare respinte quando era il registro a essere
indietro, le prese fantasma escono da «In corso adesso», il conteggio delle unità accettate può
salire.

**Le richieste che decidi di scartare** si spostano a mano in `applied/` (il runner legge solo il
livello superiore): cosi' la coda non conta lavoro che non c'e'.

Il runner e' un programma, non un agente: puo' essere rieseguito quando vuoi, o lasciato in
`--watch 60`. Lo stesso lock delle corsie: non si pestano i piedi.

---

## 4. Le cinque schede di «Adesso»

Il numero tondo su ogni scheda e' **quante righe contiene**: si vede solo quando c'e' qualcosa —
rosso per quello che aspetta te, verde per quello che hai gia' fatto. La scheda scelta sta
nell'indirizzo (`#posta`, `#corso`): la pagina si ricarica da sola, e cosi' non ti riporta alla prima
mentre stai leggendo la terza.

### 4.1 Cosa fare adesso

| Cosa leggi | Cosa significa | Cosa fare |
| --- | --- | --- |
| **Quello che il registro dice che è dovuto** | i `next` dei report, ridotti dal motore unico alla prima fase realmente eseguibile | un solo pulsante per dichiarazione, con la stessa forma `accetta / torna in E / passa a T / chiudi obbligo` |
| `X: in corso` | quella fase ha una presa viva: qualcuno la sta facendo **adesso** | niente: e' in mano a qualcuno |
| `X: consegnata` | la fase si e' mossa **dopo** la dichiarazione che la nominava: l'atto chiesto c'e' gia' | niente: guarda la riga nuova della dichiarazione che segue |
| **Leggi** (accanto) | il testo della dichiarazione, intero | — |
| **Da rifare: respinte in verifica** | fasi respinte, con quante volte e **per cosa** (l'ostacolo che torna, e *chi lo deve*) | **Attiva** se l'atto e' su di lei |
| **Da attivare** | fasi libere i cui prerequisiti sono a posto | **Attiva** |
| **In attesa di un esecutore** | riservate: l'ordine c'e', manca chi lo prende | **Copia il prompt** e dallo a un esecutore, oppure **Rilascia** |
| **Non tocca a queste: …** | fasi non accettate la cui ultima consegna manda ad **altre** fasi (tutte gia' accettate): il prossimo atto e' un tentativo nuovo su quelle | non attivarle: usa i **Prompt** delle righe dovute qui sopra |
| **N consegne senza direzione** | chi ha consegnato non ha lasciato cosa fare dopo | vedi «Testimone» |

### 4.2 Posta in arrivo

Il messaggio di un agente che non e' (ancora) nel suo report: si incolla **intero** e non muore.
Il numero sulla scheda sono le ricevute **non ancora lavorate** (una ricevuta e' lavorata quando
esiste un report di quella fase scritto dopo di lei).

**Cosa fare**: quando un agente ti scrive qualcosa che conta, apri «Deposita un messaggio nella
posta», incolla, premi. Non tocca i registri: scrive un file in `inbox/`.

### 4.3 Cosa aspetta te

Le domande di un task e le decisioni di governo. In cima a ognuna c'e' **«in parole povere»**: di
cosa si parla (i codici nominati, col loro stato: respinte, ostacolo che torna, chi lo deve), cosa
resta fermo finche' non rispondi, e quante **firme distinte** risultano nel registro. Poi il testo
integrale di chi ha chiesto, e le alternative **con cosa succede scegliendole**.

**Cosa fare**: scegli un'alternativa o scrivi la risposta, premi **Registra la decisione**. La
scrittura passa dal lock e dalla validazione: se un registro non regge, la scrittura viene annullata e
te lo dice. La risposta finisce in «Risposte che hai già dato», con la decisione che ha prodotto.

### 4.4 In corso adesso

Le **prese vive**: chi tiene la fase e da quando. Il numero sulla scheda e' quante sono.

**Cosa fare**: leggere. Se una presa e' li' da troppo tempo per il lavoro che e' (o il suo
attempt e' gia' pubblicato), quella e' la misura che qualcuno ha consegnato senza rilasciare: **il
rilascio e' in coda** e si sistema applicando la coda (§3).

### 4.5 Risposte che hai già dato

La storia: le tue risposte con la decisione registrata (`D0xx`) e il contesto. **Non si riscrivono**:
se una va cambiata, si apre una domanda nuova. Il numero e' **verde** perche' non chiede niente.

---

## 5. I pulsanti, uno per uno

| Pulsante | Cosa fa **davvero** | Cosa NON fa |
| --- | --- | --- |
| **Attiva** | deposita un **ordine durevole** in `dispatch-queue/` (prompt, perimetro, impronte di adesso) e **riserva** la fase (`pre_registered`) | **non avvia nessun agente.** E' una promessa in attesa di un esecutore |
| **Prompt** / **Prompt `<FASE>`** | apre il testo da incollare in una chat nuova | non deposita niente |
| **Copia il prompt** | copia quel testo | idem |
| **Salva come file** | scarica lo stesso testo come `.md`, integro | idem |
| **Leggi** | il testo (o la dichiarazione) nel dialogo, con Copia e Salva accanto | idem |
| **Rilascia** | toglie la riserva (l'ordine resta sul disco come storia) | non cancella l'ordine |
| **Invia la risposta** / **Registra la decisione** | scrive la tua risposta nei registri, passando dal lock e dalla validazione | non riapre la fase da sola |
| **Lascia le istruzioni** (Testimone) | deposita una nota di testimone su quella fase | non riscrive il report |
| **Archivia nella posta** | scrive un file in `inbox/` | non tocca i registri |
| **Copia i due comandi** | copia i tre passi della coda | non applica niente |

Due avvertenze che vengono da difetti veri:

- una fase puo' essere **gia' accettata** e avere comunque un atto dovuto (il tentativo nuovo). Il
  pulsante che lo compone e' **Prompt `<FASE>`** dentro il blocco dovuto;
- **Attiva** su una fase con «mandato già eseguito» deposita un ordine **nuovo**, con le impronte di
  adesso. Se ti serve rifare la stessa cosa sugli stessi byte, non e' quello il problema: leggi la
  riga.

---

## 6. Il vocabolario degli stati di una fase

| Stato nel registro | In pagina | Cosa significa |
| --- | --- | --- |
| `pending`, o qualsiasi parola tua | «da fare» | non iniziata, o in attesa a monte |
| `pre_registered`, `ready` | «attivata», «in attesa di un esecutore» | riservata, nessun titolare |
| `taken`, `active` (con `released_at` vuoto) | «in corso» | qualcuno la tiene |
| `needs_changes`, `failed` | «respinta in verifica» | torna a chi la esegue |
| `accepted` | «accettata» | **e' l'unico stato che chiude** |

Una **unita'** e' accettata quando **tutte** le sue fasi lo sono: e' il numero «55 di 70» in testa.

---

## 7. La catena, dal prompt all'accettazione

1. **Tu mandi un prompt** a una corsia (dalla pagina o dal blocco dovuto).
2. **La corsia deposita la presa** sul registro (la busta in testa al prompt glielo impone): la fase
   passa a «in corso», col suo nome e l'ora. Da qui la vedi in «In corso adesso».
3. **Consegna**: pubblica `reports/<fase>/attempt-N.yaml` e aggiorna il puntatore. La pagina la legge
   subito (sono file, non passano dalla coda).
4. **Dichiara cosa resta da fare** nel campo `next` del report — e' l'unico canale per il contenuto di
   quel messaggio. Senza, la pagina lo mette fra le «consegne senza direzione».
5. **Rilascia** la presa (`status: released` + `released_at`): deposita la richiesta, che resta in
   coda finche' qualcuno non la applica (§3).
6. **Il prossimo atto compare** nel blocco «Quello che il registro dice che è dovuto», col pulsante
   per il prompt di quella fase.
7. **La ratifica** (`R`) chiude l'unita' quando il criterio e' soddisfatto. Se chiede una firma
   distinta, vale la regola scritta nel contratto del progetto: distinta **da chi ha eseguito**.

Per una correzione circoscritta il registro puo' dichiarare `lane: fast`: il percorso richiesto
diventa **E → T mirata**. Non e' una scorciatoia sulle prove; evita soltanto l'analisi e
l'accettazione separate quando non aggiungono una decisione. Rischi dichiarati, migrazioni,
sicurezza, release, configurazione o piu' di due file riportano al ciclo completo.

---

## 8. Le altre pagine

| Pagina | Cosa ci trovi |
| --- | --- |
| **Svolto** | tutto ciò che i registri dichiarano concluso, più le misure del metodo: primo colpo, rifacimenti, tempo mediano, copertura dei token e interventi umani |
| **Tempo** | blocchi, unita', fasi con le barre datate dagli artefatti che **dichiarano** una data (`published_at`) o, in mancanza, dall'mtime; la riga dei commit. Nessuna previsione |
| **Testimone** | cosa c'e' da fare dopo, parola per parola: le dichiarazioni dei report, con filtro (unita' aperte / tutte / senza direzione) e ricerca |
| **Prompt** | i prompt del quaderno raggruppati per stato d'azione (da fare, in corso, respinti, fatti), col testo da copiare |
| **Percorso** | una scheda per blocco: unita', risultato atteso, fasi del ciclo, commit che toccano i suoi path |
| **Costituzione** | la bozza del piano si modifica e si salva; **solo l'utente** può approvarla. Dopo l'approvazione il testo è in sola lettura, il console verifica il sigillo SHA-256 e rifiuta ogni modifica |

Le misure del metodo non sono stime. Se un report non dichiara i token, la copertura dice quanti
report li hanno misurati e il totale resta “non misurato”, mai zero. Il tempo mediano è tempo di
calendario fra la prima presa/report e l'accettazione: può includere attese umane e pause.

Finché la Costituzione non è approvata, la pagina **Adesso** mostra soltanto il cancello: nessun
task può essere attivato e nessun prompt può essere composto. I progetti nati prima di questa
regola possono creare la bozza dal modello dentro la pagina Costituzione; l'approvazione resta
sempre un atto separato dell'utente.

Nei progetti nuovi c’è un secondo cancello: dopo che l’agente ha creato `tasks.yaml`, l’utente
controlla la mappa in **Percorso** e la approva da **Adesso**. Il tool salva l’impronta del file;
se il piano cambia, le nuove attivazioni si fermano finché non viene riconfermato.

Ogni report dei progetti nuovi dichiara anche `usage` e provenienza Git. Se il runtime non espone i
token, il report deve dichiararli `unavailable` con il motivo; non può usare zero. La provenienza
Git elenca branch, worktree, commit iniziale/finale, path modificati e stato finale.

---

## 9. Se vedi X, fai Y

| Se vedi | Fai |
| --- | --- |
| il riquadro **Coda dei registri** | copia i comandi, la copia del registro per prima, poi applica. Le richieste segnalate le metti da parte |
| una fase in **«Da rifare»** con «questo non si sblocca con un altro tentativo» | non riattivarla: guarda *chi lo deve*. Se dice l'utente, e' una decisione |
| una fase in **«Non tocca a queste»** | non attivarla: manda il prompt della fase dovuta, che trovi nella riga sopra |
| `X: in corso` in una riga dovuta | niente: qualcuno la sta facendo |
| **consegne senza direzione** | pagina Testimone: scrivi tu la direzione che manca, o chiedila a chi ha consegnato |
| **«mandato già eseguito»** su una fase che vuoi attivare | premi **Attiva**: deposita un ordine nuovo con il prompt e le impronte di adesso |
| una **domanda** con «una firma distinta non esiste ancora» | e' una tua decisione: o la firmi tu, o la fa un attore fuori da questo albero, o decidi chi vale come firmatario |

**E quello che questa pagina non fa**: non applica la coda, non avvia agenti, non prende decisioni al
posto tuo, non riscrive i report. Sono i tre o quattro atti che restano tuoi — ed e' per questo che
ognuno di essi, qui, e' scritto con accanto il comando o il pulsante che lo esegue.

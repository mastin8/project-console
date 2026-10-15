# Il primo giorno di un progetto

Parti da un'idea e vuoi la vista accesa, coi TUOI blocchi e i TUOI nomi. Sono quattro passi, e i
nomi li scegli tu: il coordinatore non ne conosce nessuno.

## 1. La cartella dei registri

```bash
python3 scaffold.py /percorso/mio-progetto --project "Nome del progetto"
```

Crea i registri vuoti, i quattro ruoli degli agenti e il quaderno. Mettila **dentro il repository
del progetto** (per esempio `.coord/`): cosi' la riga dei commit funziona e mostra quali commit
toccano i path che dichiari.

Accendendo subito la vista vedi il vuoto detto bene: *0 di 0 unita' accettate*, *nessuna data da
disegnare*, *nessun prompt nel quaderno*. Non e' un errore: e' un progetto che non ha ancora
scritto niente.

## 2. La mappa del lavoro: `tasks.yaml`

Qui nascono i tuoi blocchi. Un blocco e' un'area del lavoro (il nome lo scegli tu: sono le schede
che vedrai in fondo alla pagina), e contiene unita'; ogni unita' attraversa le fasi del ciclo.

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
- **l'id della fase comincia con l'id dell'unita'** (`CAT01` + `A`): serve solo a mostrare la
  lettera giusta nei tastini, quindi vale la pena rispettarlo;
- **i suffissi non devono essere A/E/T/R**: sono i tuoi. Le fasi del ciclo si dichiarano in
  `console.yaml` (`phases:`), e l'ultima e' quella che ratifica l'unita';
- **`kind` e' un'etichetta libera** (per convenzione `analysis`, `implementation`,
  `independent_verification`, `functional_acceptance`), e finisce nel report che si apre cliccando;
- **gli id sono unici** in tutto il file.

## 3. Aprire le fasi nel registro

```bash
python3 registers/sync_phases.py --workspace /percorso/mio-progetto --apply
```

Senza questo, il primo agente che prova a prendere una fase viene **rifiutato** («ancora non
trovata»): `tasks.yaml` dice quali fasi esistono, ma e' `state.yaml#tasks` che ne tiene lo stato, e
su un progetto nuovo e' vuoto. Il comando apre solo le voci mancanti, con `status: pending`.

Gia' da qui la vista mostra i blocchi, con le unita' «da fare» e i tastini della fase.

## 4. Il primo prompt: `PARALLEL-PROMPTS.md`

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

1. **il codice di riconoscimento**: il nome della voce di claim (o dell'obbligo) nel testo, che
   deve esistere nel registro. E' cosi' che la pagina sa a quale fase appartiene quel prompt;
2. **la consegna**: la riga `CONSEGNA:` col file che il prompt deve pubblicare (sotto il prefisso
   `deliverable_prefix`, per convenzione `reports/`);
3. il **titolo scritto a mano**, che viene confrontato con la misura: se dice «fatto» e la consegna
   non esiste, la pagina te lo segnala invece di crederci.

Da qui in poi la pagina e' viva: *da lanciare* finche' nessuno prende, *in azione* quando la presa
e' nel registro, *fatto* quando la consegna esiste, *consegna respinta* se il verdetto dice di no.

## Gli agenti

I ruoli sono gia' copiati in `agents/roles/` (coordinatore, analista, esecutore, verificatore).
Quello che personalizzi e' `agents/agents.yaml`: un ruolo per voce, con la missione e il perimetro.
Il prompt operativo di un agente e' la somma di tre cose: il suo ruolo, il suo mandato, e il
quaderno dove sta il lavoro da fare.

La regola che tiene insieme tutto: **un agente prende la fase prima di scrivere** (una voce di
claim nel registro, depositata come transizione) e **la rilascia quando consegna**. Senza questa
regola due corsie lavorano sugli stessi byte e la vista mostra due titolari sulla stessa fase.

## Il vocabolario degli stati

Il coordinatore non indovina: conosce queste parole, e le altre le mostra come sono.

| Dove | Stato | Cosa significa per la vista |
| --- | --- | --- |
| `state.yaml#tasks` | `accepted` | la fase e' chiusa: e' l'unico stato che CHIUDE |
| `state.yaml#tasks` | tutto il resto | la fase e' aperta (qualunque parola tu usi) |
| `state.yaml#tasks` | `needs_changes`, `failed` | respinta in verifica: torna a chi l'esegue |
| `state.yaml#active_claims` | `active`, `taken`, `ready`, `pre_registered`, `active_extension` | presa viva, se `released_at` e' assente |

Fuori da queste due liste il coordinatore non presume niente: mostra la parola che trova.

## Cosa e' obbligatorio e cosa no

| File | Obbligatorio? | A cosa serve |
| --- | --- | --- |
| `tasks.yaml` | si' | i blocchi, le unita', le fasi: e' la mappa |
| `state.yaml` | si' (lo crea lo scaffold) | lo stato delle fasi e le prese vive |
| `PARALLEL-PROMPTS.md` | per la sezione dei prompt | il lavoro da far partire |
| `console.yaml` | no | nome, marchio, comandi di verifica, nomi dei file |
| `questions.yaml` | no | le domande che aspettano l'utente |
| `user_decisions.yaml` | no | le decisioni che appartengono solo all'utente |
| `reports/` | no (lo crea lo scaffold) | le consegne e i puntatori |
| `agents/` | no | i ruoli e la mappa degli agenti |
| `brand/logo.png` | no | il marchio nell'intestazione |

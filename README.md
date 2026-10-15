# Project Console

Il coordinatore dei progetti: una pagina locale che legge i registri di un progetto e mostra, in
un colpo d'occhio, **a che punto e'**, **cosa aspetta te** e **cosa si puo' far partire adesso**.
Dove serve scrivere — rispondere a una domanda, chiudere una decisione di governo, depositare un
ordine di lavoro — scrive passando dal lock e dalla validazione dei registri.

Non conosce nessun progetto. Un **workspace** e' una cartella di dati; il coordinatore ne serve
quanti vuoi, anche contemporaneamente, senza sapere niente di nessuno di essi.

## Avvio in trenta secondi

```bash
python3 scaffold.py /tmp/prova --project "Prova" --esempio   # crea un workspace d'esempio
python3 console/server.py --workspace /tmp/prova             # http://127.0.0.1:8899
```

Senza `--workspace` il coordinatore usa `$CONSOLE_WORKSPACE`, o la cartella corrente.

## Il primo giorno di un progetto vero

```bash
python3 scaffold.py /percorso/vattelappesca --project "Vattelappesca"   # la cartella dei registri
# scrivi la mappa del lavoro in tasks.yaml e il primo prompt in PARALLEL-PROMPTS.md
python3 registers/sync_phases.py --workspace /percorso/vattelappesca --apply   # apre le fasi
python3 console/server.py --workspace /percorso/vattelappesca
```

Da li' in poi il coordinatore mostra tutto da solo: gli agenti prendono le fasi depositando una
transizione, consegnano scrivendo un file in `reports/`, e la pagina ne ricava lo stato senza che
nessuno lo aggiorni a mano.

## Cosa si vede

1. **Il percorso nel tempo** — blocchi, unita', fasi, con le barre datate da cio' che gli artefatti
   DICHIARANO (`published_at`) o, in mancanza, dall'mtime; e la riga dei commit del repository, con
   i commit che toccano i path dichiarati da ogni blocco. Nessuna previsione: solo misure.
2. **Cosa aspetta te** — le domande di un task e le decisioni di governo, con il controllo per
   rispondere. La risposta si scrive nei registri e appende una decisione.
3. **I prossimi prompt da eseguire** — i prompt del quaderno, raggruppati per stato d'azione
   (da lanciare, in azione, consegna respinta, gia' consegnati) e con il testo da copiare.
4. **Percorso per blocchi** — una scheda per blocco: unita', risultato atteso, fasi che aprono il
   report, respinte in verifica, e i commit che toccano i path dichiarati dal blocco.

## Come si comanda

```bash
python3 console/server.py --workspace <progetto> [--port 8899] [--host 127.0.0.1]
python3 scaffold.py <cartella> --project "Nome" [--esempio]
python3 registers/sync_phases.py --workspace <progetto> [--apply]   # apre le fasi dichiarate e non ancora registrate
python3 registers/validate_registries.py --workspace <progetto>
python3 registers/next_prompts.py --workspace <progetto> [--json|--explain]
python3 registers/static_view.py --workspace <progetto>          # la stessa cosa, in una pagina statica
python3 registers/apply_transitions.py --workspace <progetto> --dir <progetto>/pending-transitions
```

## Il contratto di un workspace

Tutto quello che il coordinatore legge ha un nome dichiarabile in `console.yaml`; i valori
predefiniti sono la convenzione e un workspace scritto a mano funziona senza configurazione.

| Cosa | Default | A cosa serve |
| --- | --- | --- |
| `state.yaml` | `state.yaml` | lo stato delle fasi, le prese vive, i report |
| `tasks.yaml` | `tasks.yaml` | i blocchi e le unita', con le fasi del ciclo |
| `questions.yaml` | `questions.yaml` | le domande che aspettano l'utente |
| `decisions.yaml` | `decisions.yaml` | le decisioni prese, in ordine |
| `user_decisions.yaml` | `user_decisions.yaml` | le decisioni di governo, che appartengono all'utente |
| `reports/` | `reports/` | le consegne: `reports/<id>/attempt-N.yaml` e il puntatore `reports/<id>.yaml` |
| `PARALLEL-PROMPTS.md` | idem | il quaderno dei prompt, con i codici di riconoscimento |
| `pending-transitions/` | idem | la coda delle scritture sui registri |
| `brand/` | `brand/` | `logo.svg` o `logo.png`: l'intestazione li usa senza toccare codice |
| `verify` | vuoto | i comandi di verifica del progetto, mostrati nella vista statica |

Il significato dei campi, la forma di ogni registro e le regole che rendono un prompt riconoscibile
sono in [`docs/contratto-workspace.md`](docs/contratto-workspace.md). Il modello pronto da copiare
e' in [`templates/workspace/`](templates/workspace/).

## Gli agenti

Il coordinatore non esegue: mostra. Il lavoro lo fanno gli agenti, che sono chat separate a cui si
incolla un prompt del quaderno. Perche' funzioni su un progetto qualunque servono tre cose, e sono
tutte file:

1. i **registri** (chi fa cosa, a che punto e');
2. il **quaderno** (`PARALLEL-PROMPTS.md`), col codice di riconoscimento in ogni sezione;
3. i **ruoli** (`agents/roles/*.md`) e la **mappa** (`agents/agents.yaml`), che dicono come lavora
   un agente e quale perimetro ha.

La regola che tiene insieme il resto: un agente prende la fase PRIMA di scrivere (una voce di claim
nel registro), la rilascia quando consegna, e non tocca i registri con una riscrittura libera —
deposita una transizione. Senza questa regola due corsie lavorano sugli stessi byte e nessuno se ne
accorge. Dettagli in [`agents/README.md`](agents/README.md).

## Stato

Estratto il 2026-10-15 dal primo progetto che ha usato questo strumento, e reso agnostico: il
progetto e' diventato un workspace, i comandi di verifica una voce di configurazione, il nome e il
marchio due caselle. La prova che funziona su altro: `examples/demo` e' un workspace creato da zero
con lo scaffolder, e il coordinatore lo serve senza una riga di codice in piu'.

Serve solo Python 3.11+ e PyYAML. Nessuna rete in uscita, nessun servizio esterno.

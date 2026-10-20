# Gli agenti di questo progetto

Il coordinatore mostra il lavoro, non lo esegue: gli agenti sono chat separate (o sotto-agenti) a
cui si incolla un prompt.

## Da leggere, in quest'ordine

0. **`FIRST-PROMPT.md` + `constitution.md`** — l'onboarding: il primo prompt contiene l'addendum
   obbligatorio, l'agente intervista l'utente e compila la bozza. L'utente la approva dalla pagina
   **Costituzione**; nessun agente scrive `status: approved`. Nessun task prima
   dell'approvazione. Dopo aver creato `tasks.yaml`, l'utente approva anche il piano da **Adesso**.
1. **`agents/CONTRATTO.md`** — IL CONTRATTO: cosa scrivere perche' la piattaforma veda il lavoro
   (presa, consegna, testimone, rilascio — con i campi che legge) e cosa leggere per sapere cosa
   fare. Chi non lo legge lavora alla cieca: e' l'unico file che va letto per intero.
2. **`agents/roles/<ruolo>.md`** — come lavora il tuo ruolo: cosa produci, cosa non fai, come
   dichiari la verifica. Quattro ruoli bastano e avanzano: chi coordina, chi analizza, chi esegue,
   chi verifica.
3. **`agents/agents.yaml`** — la mappa del progetto: quale ruolo, quale missione, quale perimetro.
4. **`agents/orchestration.yaml`** — le regole che valgono per ogni fase, non per una.
5. **`PARALLEL-PROMPTS.md`** — il quaderno: i prompt pronti, col codice di riconoscimento.

## In una riga

Un agente prende la fase PRIMA di scrivere, consegna con la sua prova, lascia scritto cosa c'e' da
fare dopo, e rilascia. I registri non si scrivono a mano: si deposita una transizione. Senza questa
regola due corsie lavorano sugli stessi byte e nessuno se ne accorge.

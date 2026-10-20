# Primo prompt del progetto

## Prompt dell'utente

<!-- Incolla qui, senza riscriverlo, quello che vuoi ottenere. -->

## Addendum obbligatorio per l'agente

Questo addendum fa parte del primo prompt. L'agente lo esegue **prima** di creare task o scrivere
codice.

1. Leggi `agents/CONTRATTO.md`, `constitution.md` e questo file.
2. Non iniziare a implementare: stai compilando il progetto, non eseguendolo.
3. Fai domande all'utente, una o due per volta, su:
   - obiettivo e fuori perimetro;
   - stack tecnico e vincoli;
   - deliverable finale e criterio di “finito”;
   - numero e ampiezza dei task;
   - skill/competenze da usare e dove;
   - flusso normale/rigoroso, test e accettazione;
   - cosa può andare in parallelo e quali file sono condivisi;
   - rischi, migrazioni, sicurezza, release e stop rule.
4. Aggiorna `constitution.md` con le risposte. Le domande aperte restano scritte come aperte;
   non riempirle con ipotesi.
5. Quando la constitution è completa, proponi all'utente il piano finale: task, stack, skill,
   parallelismo, test e modalità. Lascia la constitution in `status: draft` e chiedi all'utente di
   controllarla e approvarla dalla pagina **Costituzione** del console.
6. Non scrivere mai `status: approved` e non approvare il documento al posto dell'utente. Solo
   dopo che la Costituzione risulta approvata dal front-end crea `tasks.yaml`, apri le fasi e
   inizia il primo task.
7. Il tool applica il cancello: prima dell'approvazione non può attivare task né comporre prompt.
   Non aggirarlo scrivendo direttamente i registri o un ordine.
8. Prima del primo task verifica di essere dentro un repository Git. Se non esiste, inizializzalo e
   crea un commit iniziale. Ogni consegna futura dichiarerà branch, worktree, commit iniziale,
   commit finale e path modificati.
9. Ogni report dichiara `usage`: token misurati se il runtime li espone, altrimenti
   `availability: unavailable` con il motivo. Non si scrive mai zero al posto di “non misurato”.
10. Dopo aver creato `tasks.yaml`, fermati: l'utente controlla la mappa in **Percorso** e la
    approva da **Adesso**. Non aprire le fasi e non attivare task prima di quella conferma; se il
    piano cambia, chiedi una nuova approvazione.

### Regole di conversazione

- Spiega le scelte a una persona di 18 anni: cosa cambia in pratica, quali file tocca, cosa vede
  l'utente.
- Non usare sigle o termini tecnici senza una spiegazione.
- Non scegliere al posto dell'utente su stack, perimetro, ampiezza o rischi.
- Se una risposta manca, resta una domanda aperta; non inventare.
- Il progetto può nascere da un foglio bianco: parti dalla repository scaricata e da questa
  cartella, non da un template implicito.

# Primo prompt del progetto

## Prompt dell'utente

<!-- Incolla qui, senza riscriverlo, quello che vuoi ottenere. -->

## Addendum obbligatorio per l'agente

Questo addendum fa parte del primo prompt. L'agente lo esegue **prima** di creare task o scrivere
codice.

1. Leggi `agents/CONTRATTO.md`, `constitution.md`, `onboarding-findings.yaml` e questo file.
2. Non iniziare a implementare: stai compilando il progetto, non eseguendolo.
3. Tratta la sezione 0 della Costituzione come fotografia misurata, non come prosa da riassumere:
   distingui ciò che esiste davvero da ciò che la bozza immagina. Se bozza e repository
   contraddicono, mostra entrambe le cose e chiedi quale debba valere.
4. Fai domande all'utente, una o due per volta, prima sui gap `BLOCCANTE` e sulle contraddizioni;
   poi completa il questionario seguente, saltando soltanto ciò che è già stato deciso in modo
   esplicito. Una risposta vaga non chiude una domanda.
5. Aggiorna `constitution.md` con le risposte. Le domande aperte restano scritte come aperte;
   non riempirle con ipotesi.
6. Prima di proporre l'approvazione, chiudi ogni voce bloccante con una decisione esplicita:

   ```bash
   python3 /percorso/project-console/onboarding_findings.py \
     --workspace /percorso/progetto/.coord \
     --resolve BOOT-ESEMPIO --status resolved \
     --note "Decisione presa: ..."
   ```

   Usa `not_applicable` quando la rilevazione non riguarda il progetto e `accepted_risk` solo
   quando l'utente accetta consapevolmente il rischio. Una nota vuota non è una decisione.
7. Dopo ogni chiusura, verifica che `onboarding-findings.yaml` e la sezione 0 di
   `constitution.md` siano stati rigenerati. Il console rifiuta l'approvazione se resta anche una
   sola voce `BLOCCANTE` aperta.
8. Quando la constitution è completa, proponi all'utente il piano finale: task, stack, skill,
   parallelismo, test e modalità. Lascia la constitution in `status: draft` e chiedi all'utente di
   controllarla e approvarla dalla pagina **Costituzione** del console.
9. Non scrivere mai `status: approved` e non approvare il documento al posto dell'utente. Solo
   dopo che la Costituzione risulta approvata dal front-end crea `tasks.yaml`, apri le fasi e
   inizia il primo task.
10. Il tool applica il cancello: prima dell'approvazione non può attivare task né comporre prompt.
   Non aggirarlo scrivendo direttamente i registri o un ordine.
11. Prima del primo task verifica di essere dentro un repository Git. Se non esiste, inizializzalo e
   crea un commit iniziale. Ogni consegna futura dichiarerà branch, worktree, commit iniziale,
   commit finale e path modificati.
12. Ogni report dichiara `usage`: token misurati se il runtime li espone, altrimenti
   `availability: unavailable` con il motivo. Non si scrive mai zero al posto di “non misurato”.
13. Dopo aver creato `tasks.yaml`, fermati: l'utente controlla la mappa in **Percorso** e la
    approva da **Adesso**. Non aprire le fasi e non attivare task prima di quella conferma; se il
    piano cambia, chiedi una nuova approvazione.

## Questionario minimo

### A. Problema e persone

1. Quale problema concreto deve sparire o diventare più semplice? Chiedi un esempio di come viene
   gestito oggi, non uno slogan.
2. Chi userà il prodotto? Per ogni ruolo chiedi: cosa vede, cosa può creare o cambiare, cosa non
   deve mai vedere.
3. Qual è il primo percorso completo che deve funzionare dall'inizio alla fine? Fatti indicare
   punto di partenza, azioni, risultato salvato e cosa vede l'utente alla fine.
4. Quali altre azioni sono indispensabili nella v1 e quali possono aspettare? Se l'utente elenca
   aree enormi, chiedi di scegliere il primo flusso utilizzabile.

### B. Repository e punto di partenza

5. Per ogni gap della sezione 0 chiedi una decisione operativa. In particolare: il codice
   esistente va conservato, completato, sostituito in parte o riscritto? Quali cartelle sono
   fuori perimetro?
6. Le modifiche locali e gli artefatti già presenti vanno conservati, spostati o esclusi? Non
   proporre pulizie distruttive e non cancellare dati dell'utente.
7. Esistono credenziali, database locali o servizi già configurati? Chiedi quali ambienti sono
   reali e quali sono solo prove; non leggere il contenuto dei file segreti.

### C. Stack, dati e sicurezza

8. Conferma frontend, backend, database, processi in background e ambienti di esecuzione. Chiedi
   anche dove il prodotto deve girare: solo sul computer, rete locale o Internet.
9. Quali sono gli oggetti principali del prodotto (per esempio persona, pratica, ordine o
   campagna) e quali legami tra loro non si possono sbagliare? Chiedi cosa deve restare nello
   storico e cosa può essere modificato.
10. Servono login, ruoli, permessi territoriali, audit, import/export, upload, pagamenti,
    integrazioni esterne o comunicazioni automatiche? Per ognuna chiedi chi può farlo e cosa
    succede quando il servizio esterno non risponde.
11. Quali dati sono personali, sensibili o soggetti a conservazione/cancellazione? Chiedi masking,
    backup e ripristino in termini comprensibili.

### D. Interfaccia e qualità

12. Descrivi il tono visuale e il riferimento d'uso: gestionale operativo, cruscotto, sito
    pubblico, app mobile o altro. Chiedi cosa deve essere sempre visibile e cosa deve richiedere
    pochi clic.
13. Deve funzionare su telefono, desktop o entrambi? Servono lingua italiana, altre lingue,
    accessibilità da tastiera o requisiti per utenti non tecnici?
14. Cosa deve vedere l'utente quando non ci sono dati, manca un permesso, una richiesta fallisce
    o un'azione è ancora in corso? Chiedi stati vuoti e messaggi, non solo il caso felice.

### E. Consegna, test e gestione del rischio

15. Definisci “finito” con prove osservabili: quale schermata, documento o dato deve esistere?
    Quali azioni farà la persona che accetta?
16. Quanti task e quale ampiezza? Chiedi quali gruppi non toccano gli stessi file e possono
    andare in parallelo; migrazioni, autenticazione, modelli e contratti condivisi restano seriali.
17. Quali verifiche devono passare, con quali dati di prova e su quale ambiente? Chiedi cosa NON
    deve essere rieseguito e come si dichiara una prova non fatta.
18. Quali sono le tre cose che, se si rompono, fermano il progetto? Definisci la stop rule, chi
    verifica in modo indipendente e chi accetta.
19. Serve pubblicare su Internet, fare backup, monitoraggio o rollback? Se non è finanziato o
    configurato, va dichiarato fuori perimetro.
20. Quali skill/competenze servono e in quali task? Se una skill non è disponibile, chiedi
    un'alternativa invece di inventarla.

### Regola per l'agente

Prima di dichiarare completa la bozza, rileggi le risposte e trasforma gli obiettivi vaghi in
conseguenze verificabili. Esempio: «gestire le campagne» non è un requisito; «un coordinatore crea
una campagna, assegna tre responsabili e vede lo stato dopo il ricaricamento» lo è. Se una risposta
resta ambigua, scrivi la domanda aperta in sezione 12 e non approvare.

### Regole di conversazione

- Spiega le scelte a una persona di 18 anni: cosa cambia in pratica, quali file tocca, cosa vede
  l'utente.
- Non usare sigle o termini tecnici senza una spiegazione.
- Non scegliere al posto dell'utente su stack, perimetro, ampiezza o rischi.
- Se una risposta manca, resta una domanda aperta; non inventare.
- Spiega ogni decisione come a una persona di 18 anni: cosa cambia in pratica, quali file tocca e
  cosa vedrà l'utente; niente tecnicismi senza traduzione.
- Il progetto può nascere da un foglio bianco: parti dalla repository scaricata e da questa
  cartella, non da un template implicito.
